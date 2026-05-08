from __future__ import annotations

import hashlib
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, NotSupportedError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from smartInterviewApp.models import (
    CodingQuestion,
    Interview,
    JobInterviewBlueprint,
    JobInterviewSkill,
    QuestionGenerationJob,
    Skill,
    SkillQuestion,
    normalize_skill_key,
)
from smartInterviewApp.services.cloud_tasks import CloudTasksConfigurationError, CloudTasksScheduler


logger = logging.getLogger('smartInterview.question_banks')

cloud_tasks_scheduler = CloudTasksScheduler()

MAX_SKILL_CONTEXT_CHARS = 1200
QUESTION_FILLER_TOKENS = {
    'a',
    'an',
    'and',
    'are',
    'can',
    'could',
    'do',
    'does',
    'explain',
    'how',
    'in',
    'is',
    'of',
    'please',
    'tell',
    'the',
    'to',
    'what',
    'when',
    'where',
    'why',
    'you',
}
TECHNICAL_CODING_CATEGORIES = {
    'backend',
    'backend development',
    'cloud',
    'database',
    'devops',
    'frontend',
    'frontend development',
    'mobile development',
    'operating system',
    'programming language',
    'salesforce',
    'software development',
    'version control',
    'web services',
}
TECHNICAL_CODING_SKILL_KEYS = {
    'angular',
    'apex',
    'core-java',
    'django',
    'django-rest-framework',
    'flutter',
    'html-css',
    'javascript',
    'laravel',
    'linux',
    'mongodb',
    'mysql',
    'next-js',
    'node-js',
    'php',
    'postgresql',
    'python',
    'react',
    'react-native',
    'rest-api',
    'soql',
    'sql',
}
GENERIC_TECHNICAL_ROLE_SKIP_SKILL_KEYS = {
    'agile',
    'communication-skills',
    'industry-trends-awareness',
    'leadership',
    'scrum',
    'stakeholder-management',
    'teamwork',
}
TECHNICAL_ROLE_KEYWORDS = {
    'api',
    'backend',
    'code',
    'coding',
    'database',
    'developer',
    'development',
    'devops',
    'django',
    'engineer',
    'frontend',
    'javascript',
    'python',
    'software',
    'sql',
    'technical',
}


class OpenAIQuestionGenerationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        retryable: bool,
        status_code: int | None = None,
        body_preview: str = '',
    ):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable
        self.status_code = status_code
        self.body_preview = body_preview[:1000]


def ensure_question_bank_for_blueprint(blueprint_id: int) -> list[dict[str, Any]]:
    return enqueue_question_generation_jobs(blueprint_id)


def enqueue_question_generation_jobs(blueprint_id: int) -> list[dict[str, Any]]:
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_ENABLED', True):
        return []
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_AUTO_ENQUEUE_ON_BLUEPRINT', True):
        return [{'ok': True, 'status': 'auto_enqueue_disabled', 'blueprint_id': blueprint_id}]
    blueprint = JobInterviewBlueprint.objects.filter(id=blueprint_id).first()
    if not blueprint:
        return []
    results: list[dict[str, Any]] = []
    eligible_processed = 0
    max_skills = max(1, int(getattr(settings, 'INTERVIEW_QUESTION_BANK_MAX_SKILLS_PER_BLUEPRINT_ENQUEUE', 5)))
    plans = (
        JobInterviewSkill.objects
        .select_related('skill')
        .filter(blueprint=blueprint, is_active=True, skill__is_active=True)
        .order_by('priority', 'id')
    )
    generation_metadata_by_skill_id = _question_bank_generation_metadata_by_skill(blueprint)
    for plan in plans:
        metadata = generation_metadata_by_skill_id.get(plan.skill_id, {})
        interview_weight = str(metadata.get('interview_weight') or 'normal').strip().lower()
        eligible_for_random_sub_skill = bool(metadata.get(
            'eligible_for_random_sub_skill',
            plan.skill_role != JobInterviewSkill.SkillRole.OPTIONAL,
        ))
        if not _should_auto_generate_for_plan(plan, interview_weight, eligible_for_random_sub_skill):
            results.append({
                'ok': True,
                'status': 'skipped_optional_or_low_weight',
                'skill_id': plan.skill_id,
                'skill_key': plan.skill.key,
                'skill_role': plan.skill_role,
                'interview_weight': interview_weight,
                'eligible_for_random_sub_skill': eligible_for_random_sub_skill,
            })
            logger.info(
                'Question bank auto-generation skipped skill_id=%s skill_key=%s skill_role=%s interview_weight=%s eligible_for_random_sub_skill=%s',
                plan.skill_id,
                plan.skill.key,
                plan.skill_role,
                interview_weight,
                eligible_for_random_sub_skill,
            )
            continue
        if eligible_processed >= max_skills:
            results.append({
                'ok': True,
                'status': 'skipped_max_blueprint_enqueue_limit',
                'skill_id': plan.skill_id,
                'skill_key': plan.skill.key,
                'skill_role': plan.skill_role,
                'interview_weight': interview_weight,
                'eligible_for_random_sub_skill': eligible_for_random_sub_skill,
                'max_skills': max_skills,
            })
            logger.info(
                'Question bank auto-generation skipped by max skill cap skill_id=%s skill_key=%s max_skills=%s',
                plan.skill_id,
                plan.skill.key,
                max_skills,
            )
            continue
        eligible_processed += 1
        results.append(ensure_question_bank_for_skill(plan.skill_id, include_coding=plan.coding_questions_to_ask > 0))
    return results


def _question_bank_generation_metadata_by_skill(blueprint: JobInterviewBlueprint) -> dict[int, dict[str, Any]]:
    plan = blueprint.blueprint_plan if isinstance(blueprint.blueprint_plan, dict) else {}
    items: list[dict[str, Any]] = []
    primary = plan.get('primary_skill')
    if isinstance(primary, dict):
        items.append(primary)
    for group_key in ['primary_skill_candidates', 'sub_skills', 'optional_skills']:
        group = plan.get(group_key)
        if isinstance(group, list):
            items.extend(item for item in group if isinstance(item, dict))

    metadata: dict[int, dict[str, Any]] = {}
    for item in items:
        try:
            skill_id = int(item.get('skill_id') or 0)
        except (TypeError, ValueError):
            continue
        if not skill_id:
            continue
        metadata[skill_id] = {
            'interview_weight': str(item.get('interview_weight') or 'normal').strip().lower(),
            'eligible_for_random_sub_skill': bool(item.get('eligible_for_random_sub_skill', True)),
        }
    return metadata


def _should_auto_generate_for_plan(plan: JobInterviewSkill, interview_weight: str, eligible_for_random_sub_skill: bool) -> bool:
    if plan.skill_role == JobInterviewSkill.SkillRole.OPTIONAL:
        return False
    if interview_weight == 'low':
        return False
    if not eligible_for_random_sub_skill:
        return False
    if plan.skill_role in {JobInterviewSkill.SkillRole.PRIMARY, JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE}:
        return True
    return plan.skill_role == JobInterviewSkill.SkillRole.SUB_SKILL


def ensure_question_bank_for_skill(skill_id: int, include_coding: bool = False) -> dict[str, Any]:
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_ENABLED', True):
        return {'ok': True, 'status': 'disabled', 'skill_id': skill_id}
    skill = Skill.objects.filter(id=skill_id, is_active=True).first()
    if not skill:
        return {'ok': False, 'status': 'missing_skill', 'skill_id': skill_id}

    verbal_target = max(1, int(getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100)))
    coding_target = max(0, int(getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0)))
    verbal_count = SkillQuestion.objects.filter(skill=skill, is_active=True).count()
    coding_count = CodingQuestion.objects.filter(skill=skill, is_active=True).count()
    result: dict[str, Any] = {
        'ok': True,
        'skill_id': skill.id,
        'skill_key': skill.key,
        'verbal_count': verbal_count,
        'coding_count': coding_count,
        'verbal': None,
        'coding': None,
    }

    if verbal_count >= verbal_target:
        logger.info('Question bank enough skill_id=%s skill_key=%s verbal_count=%s target=%s', skill.id, skill.key, verbal_count, verbal_target)
        result['verbal'] = {'queued': False, 'status': 'enough_questions'}
    else:
        result['verbal'] = enqueue_skill_question_generation(skill.id, target_count=verbal_target)

    if include_coding and coding_target > 0 and _is_coding_skill(skill):
        if coding_count >= coding_target:
            logger.info('Coding bank enough skill_id=%s skill_key=%s coding_count=%s target=%s', skill.id, skill.key, coding_count, coding_target)
            result['coding'] = {'queued': False, 'status': 'enough_questions'}
        else:
            result['coding'] = enqueue_skill_coding_generation(skill.id, target_count=coding_target)
    elif include_coding and coding_target <= 0:
        logger.info('Coding question generation auto-enqueue disabled by target_count=0 skill_id=%s', skill.id)
        result['coding'] = {'queued': False, 'status': 'coding_generation_disabled'}
    return result


def enqueue_skill_question_generation(skill_id: int, target_count: int | None = None) -> dict[str, Any]:
    return _enqueue_skill_generation(
        skill_id=skill_id,
        task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
        target_count=target_count or int(getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100)),
        batch_size=max(1, int(getattr(settings, 'INTERVIEW_QUESTION_GENERATION_BATCH_SIZE', 10))),
    )


def enqueue_skill_coding_generation(skill_id: int, target_count: int | None = None) -> dict[str, Any]:
    return _enqueue_skill_generation(
        skill_id=skill_id,
        task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
        target_count=target_count or int(getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0)),
        batch_size=max(1, int(getattr(settings, 'INTERVIEW_CODING_GENERATION_BATCH_SIZE', 2))),
    )


def _enqueue_skill_generation(skill_id: int, task_type: str, target_count: int, batch_size: int) -> dict[str, Any]:
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_ENABLED', True):
        return {'queued': False, 'status': 'disabled', 'skill_id': skill_id}
    skill = Skill.objects.filter(id=skill_id, is_active=True).first()
    if not skill:
        return {'queued': False, 'status': 'missing_skill', 'skill_id': skill_id}
    if task_type == QuestionGenerationJob.TaskType.CODING_GENERATION and int(target_count) <= 0:
        logger.info('Coding question generation is disabled by default until schema is fixed skill_id=%s', skill.id)
        return {'queued': False, 'status': 'coding_generation_disabled', 'skill_id': skill.id, 'target_count': target_count}

    model = SkillQuestion if task_type == QuestionGenerationJob.TaskType.QUESTION_GENERATION else CodingQuestion
    count = model.objects.filter(skill=skill, is_active=True).count()
    missing_count = max(0, int(target_count) - count)
    if missing_count <= 0:
        logger.info('Generation skipped enough questions skill_id=%s task_type=%s count=%s target=%s', skill.id, task_type, count, target_count)
        return {'queued': False, 'status': 'enough_questions', 'skill_id': skill.id, 'count': count, 'target_count': target_count}

    existing = QuestionGenerationJob.objects.filter(
        skill=skill,
        task_type=task_type,
        status__in=[QuestionGenerationJob.Status.QUEUED, QuestionGenerationJob.Status.RUNNING],
    ).order_by('-created_at', '-id').first()
    if existing:
        logger.info('Generation skipped existing queued/running skill_id=%s task_type=%s generation_job_id=%s', skill.id, task_type, existing.id)
        return {
            'queued': False,
            'status': 'already_queued_or_running',
            'skill_id': skill.id,
            'generation_job_id': existing.id,
        }

    payload = {
        'skill_id': skill.id,
        'skill_key': skill.key,
        'target_verbal_questions': int(getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100)),
        'target_coding_questions': int(getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0)),
        'missing_verbal_questions': missing_count if task_type == QuestionGenerationJob.TaskType.QUESTION_GENERATION else 0,
        'missing_coding_questions': missing_count if task_type == QuestionGenerationJob.TaskType.CODING_GENERATION else 0,
        'batch_size': min(batch_size, missing_count),
    }
    generation_job = QuestionGenerationJob.objects.create(
        skill=skill,
        task_type=task_type,
        status=QuestionGenerationJob.Status.QUEUED,
        payload=payload,
    )

    runner_mode = str(getattr(settings, 'INTERVIEW_QUESTION_BANK_RUNNER_MODE', 'worker_only') or 'worker_only').strip().lower()
    if runner_mode == 'worker_only':
        generation_job.result = {'mode': 'db_queue_only', 'runner_mode': runner_mode}
        generation_job.save(update_fields=['result', 'updated_at'])
        logger.info('Generation queued skill_id=%s task_type=%s generation_job_id=%s mode=db_queue_only', skill.id, task_type, generation_job.id)
        return {'queued': True, 'status': 'queued', 'mode': 'db_queue_only', 'skill_id': skill.id, 'generation_job_id': generation_job.id}

    if getattr(settings, 'INTERVIEW_QUESTION_BANK_PROCESS_INLINE', False):
        logger.warning('INTERVIEW_QUESTION_BANK_PROCESS_INLINE is ignored by enqueue path; use the worker command to process generation jobs.')

    try:
        task_name = cloud_tasks_scheduler.create_http_task(
            task_id=cloud_tasks_scheduler.build_task_id('skill-question-bank', generation_job.id, skill.id, task_type),
            relative_path='/internal/tasks/generate-skill-question-bank/',
            payload={'generation_job_id': generation_job.id, 'skill_id': skill.id, 'task_type': task_type},
            schedule_for=timezone.now(),
        )
        generation_job.result = {'task_name': task_name, 'mode': 'cloud_tasks'}
        generation_job.save(update_fields=['result', 'updated_at'])
        logger.info('Generation queued skill_id=%s task_type=%s generation_job_id=%s mode=cloud_tasks', skill.id, task_type, generation_job.id)
        return {'queued': True, 'status': 'queued', 'mode': 'cloud_tasks', 'skill_id': skill.id, 'generation_job_id': generation_job.id, 'task_name': task_name}
    except CloudTasksConfigurationError as exc:
        generation_job.result = {'mode': 'db_queue_only', 'message': str(exc)}
        generation_job.save(update_fields=['result', 'updated_at'])
        logger.info('Generation queued skill_id=%s task_type=%s generation_job_id=%s mode=db_queue_only', skill.id, task_type, generation_job.id)
        return {'queued': True, 'status': 'queued', 'mode': 'db_queue_only', 'skill_id': skill.id, 'generation_job_id': generation_job.id, 'message': str(exc)}
    except Exception as exc:
        generation_job.status = QuestionGenerationJob.Status.FAILED
        generation_job.error_message = str(exc)[:2000]
        generation_job.finished_at = timezone.now()
        generation_job.save(update_fields=['status', 'error_message', 'finished_at', 'updated_at'])
        logger.exception('Generation enqueue failed skill_id=%s task_type=%s generation_job_id=%s', skill.id, task_type, generation_job.id)
        return {'queued': False, 'status': 'enqueue_failed', 'skill_id': skill.id, 'generation_job_id': generation_job.id, 'message': str(exc)}


def process_question_generation_task(
    generation_job_id: int | None = None,
    skill_id: int | None = None,
    task_type: str | None = None,
) -> dict[str, Any]:
    generation_job = None
    if generation_job_id:
        generation_job = QuestionGenerationJob.objects.filter(id=generation_job_id).first()

    resolved_skill_id = int(skill_id or getattr(generation_job, 'skill_id', 0) or 0)
    resolved_task_type = task_type or getattr(generation_job, 'task_type', '') or QuestionGenerationJob.TaskType.QUESTION_GENERATION
    if not resolved_skill_id:
        return {'ok': False, 'status': 'invalid_payload', 'message': 'Skill id is required.'}
    if resolved_task_type not in {QuestionGenerationJob.TaskType.QUESTION_GENERATION, QuestionGenerationJob.TaskType.CODING_GENERATION}:
        return {'ok': False, 'status': 'invalid_payload', 'message': 'Task type is invalid.'}
    if (
        resolved_task_type == QuestionGenerationJob.TaskType.CODING_GENERATION
        and int(getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0)) <= 0
    ):
        result = {
            'ok': True,
            'status': 'coding_generation_disabled',
            'skill_id': resolved_skill_id,
            'task_type': resolved_task_type,
            'generation_job_id': getattr(generation_job, 'id', None),
            'message': 'Coding question generation is disabled because INTERVIEW_SKILL_CODING_TARGET_COUNT is 0.',
        }
        if generation_job and generation_job.status != QuestionGenerationJob.Status.SKIPPED:
            generation_job.status = QuestionGenerationJob.Status.SKIPPED
            generation_job.result = result
            generation_job.error_message = result['message']
            generation_job.finished_at = timezone.now()
            generation_job.save(update_fields=['status', 'result', 'error_message', 'finished_at', 'updated_at'])
        logger.info(
            'Question generation worker skipped coding job because coding disabled generation_job_id=%s skill_id=%s',
            getattr(generation_job, 'id', None),
            resolved_skill_id,
        )
        return result

    if generation_job:
        max_attempts = max(1, int(getattr(settings, 'INTERVIEW_QUESTION_GENERATION_MAX_ATTEMPTS', 3)))
        stale_minutes = max(1, int(getattr(settings, 'INTERVIEW_QUESTION_GENERATION_STALE_RUNNING_MINUTES', 20)))
        if generation_job.status == QuestionGenerationJob.Status.SUCCESS:
            return {
                'ok': True,
                'status': 'already_processed',
                'skill_id': resolved_skill_id,
                'generation_job_id': generation_job.id,
            }
        if (
            generation_job.status == QuestionGenerationJob.Status.RUNNING
            and generation_job.started_at
            and generation_job.started_at >= timezone.now() - timedelta(minutes=stale_minutes)
        ):
            return {
                'ok': True,
                'status': 'already_running',
                'skill_id': resolved_skill_id,
                'generation_job_id': generation_job.id,
            }
        if generation_job.status == QuestionGenerationJob.Status.FAILED:
            if generation_job.attempts >= max_attempts:
                return {
                    'ok': False,
                    'status': 'max_attempts_reached',
                    'skill_id': resolved_skill_id,
                    'generation_job_id': generation_job.id,
                    'attempts': generation_job.attempts,
                }
            if not _failed_job_can_retry(generation_job):
                return {
                    'ok': False,
                    'status': 'not_retryable',
                    'skill_id': resolved_skill_id,
                    'generation_job_id': generation_job.id,
                    'attempts': generation_job.attempts,
                    'error_type': _job_error_type(generation_job),
                }
        if generation_job.status == QuestionGenerationJob.Status.SKIPPED:
            return {
                'ok': True,
                'status': 'skipped',
                'skill_id': resolved_skill_id,
                'generation_job_id': generation_job.id,
            }
        with transaction.atomic():
            generation_job = QuestionGenerationJob.objects.select_for_update().get(id=generation_job.id)
            if generation_job.status == QuestionGenerationJob.Status.SUCCESS:
                return {
                    'ok': True,
                    'status': 'already_processed',
                    'skill_id': resolved_skill_id,
                    'generation_job_id': generation_job.id,
                }
            if (
                generation_job.status == QuestionGenerationJob.Status.RUNNING
                and generation_job.started_at
                and generation_job.started_at >= timezone.now() - timedelta(minutes=stale_minutes)
            ):
                return {
                    'ok': True,
                    'status': 'already_running',
                    'skill_id': resolved_skill_id,
                    'generation_job_id': generation_job.id,
                }
            generation_job.status = QuestionGenerationJob.Status.RUNNING
            generation_job.attempts += 1
            generation_job.started_at = timezone.now()
            generation_job.finished_at = None
            generation_job.error_message = ''
            generation_job.save(update_fields=['status', 'attempts', 'started_at', 'finished_at', 'error_message', 'updated_at'])

    try:
        result = build_skill_question_bank(resolved_skill_id, resolved_task_type, generation_job.payload if generation_job else {})
        if generation_job:
            generation_job.status = QuestionGenerationJob.Status.SUCCESS if result.get('ok') else QuestionGenerationJob.Status.FAILED
            generation_job.result = result
            generation_job.error_message = '' if result.get('ok') else str(result.get('message') or '')[:2000]
            generation_job.finished_at = timezone.now()
            generation_job.save(update_fields=['status', 'result', 'error_message', 'finished_at', 'updated_at'])
        return result
    except OpenAIQuestionGenerationError as exc:
        result = _question_generation_error_result(exc, resolved_skill_id, resolved_task_type)
        logger.warning(
            'Question generation OpenAI call failed skill_id=%s task_type=%s error_type=%s retryable=%s status_code=%s message=%s',
            resolved_skill_id,
            resolved_task_type,
            exc.error_type,
            exc.retryable,
            exc.status_code,
            str(exc)[:300],
        )
        if generation_job:
            _save_question_generation_failure(generation_job, result, exc)
        return result
    except Exception as exc:
        result = _question_generation_exception_result(exc, resolved_skill_id, resolved_task_type)
        logger.exception('Question generation task failed skill_id=%s task_type=%s', resolved_skill_id, resolved_task_type)
        if generation_job:
            _save_question_generation_failure(generation_job, result, exc)
        return result


def _pending_generation_jobs_filter(stale_cutoff) -> Q:
    return (
        Q(status=QuestionGenerationJob.Status.QUEUED)
        | Q(status=QuestionGenerationJob.Status.RUNNING, started_at__isnull=True)
        | Q(status=QuestionGenerationJob.Status.RUNNING, started_at__lt=stale_cutoff)
    )


def _worker_lock_queryset(task_types: list[str], stale_cutoff):
    return (
        QuestionGenerationJob.objects
        .filter(_pending_generation_jobs_filter(stale_cutoff), task_type__in=task_types)
        .order_by('created_at', 'id')
    )


def _select_question_generation_job_ids(limit: int, *, task_types: list[str], stale_cutoff) -> list[int]:
    if limit <= 0 or not task_types:
        return []
    with transaction.atomic():
        queryset = _worker_lock_queryset(task_types, stale_cutoff)
        if connection.features.has_select_for_update_skip_locked:
            queryset = queryset.select_for_update(skip_locked=True)
        else:
            queryset = queryset.select_for_update()
        try:
            return list(queryset.values_list('id', flat=True)[:limit])
        except NotSupportedError:
            fallback_queryset = _worker_lock_queryset(task_types, stale_cutoff).select_for_update()
            return list(fallback_queryset.values_list('id', flat=True)[:limit])


def process_question_generation_queue(limit: int | None = None) -> list[dict[str, Any]]:
    limit = max(1, int(limit or getattr(settings, 'INTERVIEW_QUESTION_BANK_WORKER_LIMIT', 1)))
    stale_cutoff = timezone.now() - timedelta(minutes=max(1, int(getattr(settings, 'INTERVIEW_QUESTION_GENERATION_STALE_RUNNING_MINUTES', 20))))
    task_types = [QuestionGenerationJob.TaskType.QUESTION_GENERATION]
    coding_target = int(getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0))
    if coding_target > 0:
        task_types.append(QuestionGenerationJob.TaskType.CODING_GENERATION)

    selected_job_ids = _select_question_generation_job_ids(limit, task_types=task_types, stale_cutoff=stale_cutoff)
    if len(selected_job_ids) < limit and coding_target <= 0:
        selected_job_ids.extend(
            _select_question_generation_job_ids(
                limit - len(selected_job_ids),
                task_types=[QuestionGenerationJob.TaskType.CODING_GENERATION],
                stale_cutoff=stale_cutoff,
            )
        )

    jobs_by_id = QuestionGenerationJob.objects.in_bulk(selected_job_ids)
    jobs = [jobs_by_id[job_id] for job_id in selected_job_ids if job_id in jobs_by_id]

    results: list[dict[str, Any]] = []
    for job in jobs:
        logger.info(
            'Question generation worker selected job generation_job_id=%s skill_id=%s task_type=%s status=%s attempts=%s',
            job.id,
            job.skill_id,
            job.task_type,
            job.status,
            job.attempts,
        )
        results.append(process_question_generation_task(job.id, job.skill_id, job.task_type))
    failed_count = sum(1 for result in results if not result.get('ok'))
    logger.info('Question generation worker completed limit=%s processed=%s failed=%s', limit, len(results), failed_count)
    return results


def process_queued_question_generation_jobs(limit: int | None = None) -> list[dict[str, Any]]:
    return process_question_generation_queue(limit=limit)


def process_missing_question_bank_for_interview(interview_id: int, *, apply: bool = False) -> dict[str, Any]:
    interview = Interview.objects.select_related('role').filter(id=interview_id).first()
    if not interview:
        return {'ok': False, 'status': 'not_found', 'interview_id': interview_id, 'message': 'Interview not found.'}

    job = interview.role
    role_title = _job_title(job)
    if not job:
        return {
            'ok': False,
            'status': 'not_ready',
            'interview_id': interview.id,
            'role': role_title,
            'planned_gaps': [],
            'generated_count': 0,
            'approved_count': 0,
            'rejected_count': 0,
            'skipped_skills': [],
            'remaining_not_ready_reasons': ['no_job'],
            'message': 'Interview has no related job.',
        }

    blueprint = JobInterviewBlueprint.objects.filter(job=job).first()
    if not blueprint:
        return {
            'ok': True,
            'status': 'preview' if not apply else 'completed',
            'interview_id': interview.id,
            'role': role_title,
            'primary_skill': '',
            'selected_sub_skills': [],
            'planned_gaps': [],
            'generated_count': 0,
            'approved_count': 0,
            'rejected_count': 0,
            'skipped_skills': [],
            'remaining_not_ready_reasons': ['no_blueprint'],
        }

    plans = list(
        JobInterviewSkill.objects
        .select_related('skill')
        .filter(blueprint=blueprint, is_active=True, skill__is_active=True)
        .order_by('priority', 'id')
    )
    primary_plan = next((plan for plan in plans if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY), None)
    sub_skill_plans = [plan for plan in plans if plan.skill_role == JobInterviewSkill.SkillRole.SUB_SKILL]
    selected_plans = ([primary_plan] if primary_plan else []) + sub_skill_plans

    skipped_skills: list[dict[str, Any]] = []
    planned_gaps: list[dict[str, Any]] = []
    remaining_not_ready_reasons: list[str] = []
    if not selected_plans:
        remaining_not_ready_reasons.append('no_selected_skills')
    if not primary_plan:
        remaining_not_ready_reasons.append('no_primary_skill')

    for plan in selected_plans:
        audit = _question_bank_readiness_for_plan(plan)
        if not audit['reasons']:
            skipped_skills.append(_skip_summary(plan, 'ready', audit))
            continue
        if _should_skip_missing_only_skill(job, plan):
            skipped_skills.append(_skip_summary(plan, 'technical_role_skill_not_explicit_in_jd', audit))
            remaining_not_ready_reasons.extend(_skill_reason_labels(plan, audit['reasons']))
            continue
        missing_count = _missing_question_count_for_plan(plan.skill_role, audit)
        if missing_count <= 0:
            skipped_skills.append(_skip_summary(plan, 'no_question_count_gap', audit))
            remaining_not_ready_reasons.extend(_skill_reason_labels(plan, audit['reasons']))
            continue
        planned_gaps.append({
            'skill_id': plan.skill_id,
            'skill_name': plan.skill.name,
            'skill_key': plan.skill.key,
            'skill_role': plan.skill_role,
            'approved_count': audit['approved_count'],
            'distinct_family_count': audit['distinct_family_count'],
            'coverage_area_count': audit['coverage_area_count'],
            'missing_count': missing_count,
            'reasons': audit['reasons'],
        })

    generated_count = 0
    approved_count = 0
    rejected_count = 0
    generation_results: list[dict[str, Any]] = []
    if apply:
        for gap in planned_gaps:
            plan = next((item for item in selected_plans if item and item.skill_id == gap['skill_id']), None)
            if not plan:
                continue
            generated = generate_missing_skill_questions_with_openai(job, blueprint, plan, gap['missing_count'])
            inserted = insert_missing_skill_questions(job, plan.skill, generated)
            generated_count += inserted['generated_count']
            approved_count += inserted['approved_count']
            rejected_count += inserted['rejected_count']
            generation_results.append({
                'skill_id': plan.skill_id,
                'skill_name': plan.skill.name,
                **inserted,
            })

    if apply:
        remaining_not_ready_reasons = []
        for plan in selected_plans:
            audit = _question_bank_readiness_for_plan(plan)
            if audit['reasons']:
                remaining_not_ready_reasons.extend(_skill_reason_labels(plan, audit['reasons']))
    elif planned_gaps:
        for gap in planned_gaps:
            remaining_not_ready_reasons.extend(_skill_reason_labels_from_gap(gap))

    return {
        'ok': True,
        'status': 'completed' if apply else 'preview',
        'interview_id': interview.id,
        'role': role_title,
        'primary_skill': primary_plan.skill.name if primary_plan else '',
        'selected_sub_skills': [plan.skill.name for plan in sub_skill_plans],
        'planned_gaps': planned_gaps,
        'generated_count': generated_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'skipped_skills': skipped_skills,
        'remaining_not_ready_reasons': remaining_not_ready_reasons,
        'generation_results': generation_results,
        'apply': apply,
    }


def generate_missing_skill_questions_with_openai(
    job,
    blueprint: JobInterviewBlueprint,
    plan: JobInterviewSkill,
    missing_count: int,
) -> list[dict[str, Any]]:
    prompt = _missing_question_prompt(job, blueprint, plan, missing_count)
    parsed = _call_openai_json(prompt, _missing_verbal_question_schema(), 'missing_skill_question_bank')
    questions = parsed.get('questions') if isinstance(parsed, dict) else []
    return [item for item in questions or [] if isinstance(item, dict)]


def insert_missing_skill_questions(job, skill: Skill, questions: list[dict[str, Any]]) -> dict[str, Any]:
    batch_id = f'missing-{timezone.now().strftime("%Y%m%d%H%M%S%f")[:20]}-{skill.id}'
    stats: dict[str, Any] = {
        'generation_batch_id': batch_id,
        'generated_count': len(questions),
        'approved_count': 0,
        'rejected_count': 0,
        'duplicate_skipped_count': 0,
        'failed_count': 0,
        'rejections': [],
    }
    existing = list(SkillQuestion.objects.filter(skill=skill).values('question_text', 'question_hash', 'family_key'))
    seen_normalized = {_normalize_question_text(item['question_text']) for item in existing}
    seen_hashes = {item['question_hash'] for item in existing if item['question_hash']}
    seen_family_texts = [(normalize_skill_key(item['family_key'] or ''), _normalize_question_text(item['question_text'])) for item in existing]

    for item in questions:
        validation = _validate_missing_skill_question(job, skill, item, seen_normalized, seen_hashes, seen_family_texts)
        if not validation['ok']:
            stats['rejected_count'] += 1
            stats['rejections'].append(validation['reason'])
            if validation['reason'] == 'duplicate_question':
                stats['duplicate_skipped_count'] += 1
            continue
        try:
            with transaction.atomic():
                SkillQuestion.objects.create(
                    skill=skill,
                    question_text=validation['question_text'][:4000],
                    question_hash=validation['question_hash'],
                    difficulty=_choice(item.get('difficulty'), SkillQuestion.Difficulty.values, SkillQuestion.Difficulty.INTERMEDIATE),
                    question_type=_choice(item.get('question_type'), SkillQuestion.QuestionType.values, SkillQuestion.QuestionType.SCENARIO),
                    family_key=validation['family_key'][:120],
                    coverage_area=validation['coverage_area'][:80],
                    expected_signal=validation['expected_signal'][:2000],
                    ideal_answer_points=_json_list(item.get('ideal_answer_points')),
                    evaluation_rubric=item.get('evaluation_rubric') if isinstance(item.get('evaluation_rubric'), dict) else {},
                    tags=_json_list(item.get('tags'))[:12],
                    source=SkillQuestion.Source.OPENAI,
                    quality_status=SkillQuestion.QualityStatus.APPROVED,
                    generation_batch_id=batch_id,
                    is_active=True,
                )
            seen_normalized.add(validation['normalized'])
            seen_hashes.add(validation['question_hash'])
            seen_family_texts.append((validation['family_key'], validation['normalized']))
            stats['approved_count'] += 1
        except IntegrityError:
            stats['rejected_count'] += 1
            stats['duplicate_skipped_count'] += 1
            stats['rejections'].append('duplicate_question')
        except Exception:
            logger.exception('Missing-only SkillQuestion insert failed skill_id=%s', skill.id)
            stats['rejected_count'] += 1
            stats['failed_count'] += 1
            stats['rejections'].append('insert_failed')
    return stats


def _question_bank_readiness_for_plan(plan: JobInterviewSkill) -> dict[str, Any]:
    questions = SkillQuestion.objects.filter(
        skill=plan.skill,
        is_active=True,
        quality_status=SkillQuestion.QualityStatus.APPROVED,
    )
    approved_count = questions.count()
    coverage_area_count = (
        questions
        .exclude(coverage_area='')
        .values('coverage_area')
        .distinct()
        .count()
    )
    distinct_family_count = (
        questions
        .exclude(family_key='')
        .values('family_key')
        .distinct()
        .count()
    )
    reasons: list[str] = []
    if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY:
        if approved_count < 12:
            reasons.append('approved_question_count_below_12')
        if coverage_area_count == 0:
            reasons.append('coverage_area_missing_or_unclassified')
        elif coverage_area_count < 5:
            reasons.append('coverage_area_count_too_low')
    elif plan.skill_role == JobInterviewSkill.SkillRole.SUB_SKILL:
        if approved_count < 4:
            reasons.append('approved_question_count_below_4')
        if coverage_area_count == 0:
            reasons.append('coverage_area_missing_or_unclassified')
        if distinct_family_count < 2:
            reasons.append('distinct_family_count_too_low')
    return {
        'approved_count': approved_count,
        'coverage_area_count': coverage_area_count,
        'distinct_family_count': distinct_family_count,
        'reasons': reasons,
    }


def _missing_question_count_for_plan(skill_role: str, audit: dict[str, Any]) -> int:
    approved_count = int(audit.get('approved_count') or 0)
    distinct_family_count = int(audit.get('distinct_family_count') or 0)
    coverage_area_count = int(audit.get('coverage_area_count') or 0)
    if skill_role == JobInterviewSkill.SkillRole.PRIMARY:
        approved_gap = max(0, 12 - approved_count)
        coverage_gap = max(0, 5 - coverage_area_count) if coverage_area_count > 0 else 1
        return max(approved_gap, coverage_gap)
    if skill_role == JobInterviewSkill.SkillRole.SUB_SKILL:
        return max(0, 4 - approved_count, 2 - distinct_family_count)
    return 0


def _skip_summary(plan: JobInterviewSkill, reason: str, audit: dict[str, Any]) -> dict[str, Any]:
    return {
        'skill_id': plan.skill_id,
        'skill_name': plan.skill.name,
        'skill_key': plan.skill.key,
        'skill_role': plan.skill_role,
        'reason': reason,
        'readiness_reasons': audit.get('reasons') or [],
        'approved_count': audit.get('approved_count', 0),
        'distinct_family_count': audit.get('distinct_family_count', 0),
        'coverage_area_count': audit.get('coverage_area_count', 0),
    }


def _skill_reason_labels(plan: JobInterviewSkill, reasons: list[str]) -> list[str]:
    return [f'{plan.skill.name}:{reason}' for reason in reasons]


def _skill_reason_labels_from_gap(gap: dict[str, Any]) -> list[str]:
    return [f'{gap["skill_name"]}:{reason}' for reason in gap.get('reasons') or []]


def _should_skip_missing_only_skill(job, plan: JobInterviewSkill) -> bool:
    if not _is_technical_role_job(job):
        return False
    skill = plan.skill
    category = (skill.category or '').strip().lower()
    generic_category = category in {'soft skills', 'human resources', 'digital marketing', 'sales', 'operations'}
    generic_key = skill.key in GENERIC_TECHNICAL_ROLE_SKIP_SKILL_KEYS
    if not generic_key and not generic_category:
        return False
    return not _skill_explicitly_mentioned(job, skill)


def _is_technical_role_job(job) -> bool:
    text = _search_text(' '.join([
        getattr(job, 'role', '') or '',
        getattr(job, 'position', '') or '',
        getattr(job, 'description', '') or '',
        getattr(job, 'experience_required', '') or '',
    ]))
    return any(f' {keyword} ' in text for keyword in TECHNICAL_ROLE_KEYWORDS)


def _skill_explicitly_mentioned(job, skill: Skill) -> bool:
    text = _search_text(' '.join([
        getattr(job, 'role', '') or '',
        getattr(job, 'position', '') or '',
        getattr(job, 'description', '') or '',
    ]))
    candidates = [skill.name, skill.key.replace('-', ' ')]
    candidates.extend(_json_list(skill.aliases))
    for candidate in candidates:
        phrase = _search_text(candidate).strip()
        if phrase and f' {phrase} ' in text:
            return True
    return False


def _missing_question_prompt(job, blueprint: JobInterviewBlueprint, plan: JobInterviewSkill, missing_count: int) -> str:
    role_title = _job_title(job)
    experience_level = blueprint.experience_level or getattr(job, 'experience_required', '') or ''
    description = (getattr(job, 'description', '') or '')[:MAX_SKILL_CONTEXT_CHARS]
    return (
        f'Generate exactly {missing_count} missing interview question(s) for this job-specific question bank gap.\n'
        'Generate only for the requested skill. Do not generate broad, random, culture-fit, or generic soft-skill questions. '
        'Questions must be practical and job-relevant, using scenario, debugging, implementation, or tradeoff framing. '
        'Do not include coding tasks that require writing a complete program. '
        'Each question must include non-empty expected_signal, family_key, question_type, difficulty, and coverage_area. '
        'coverage_area must be a short snake_case label for the exact concept being tested. '
        'family_key must be short, stable, snake_case, and group near-equivalent questions. '
        'question_type must be one of scenario, debugging, practical, or concept, preferring scenario/debugging/practical. '
        'No duplicate questions within the response.\n\n'
        f'Role title: {role_title}\n'
        f'Experience level: {experience_level}\n'
        f'Skill name: {plan.skill.name}\n'
        f'Skill category: {plan.skill.category}\n'
        f'Skill role: {plan.skill_role}\n'
        f'Missing count: {missing_count}\n'
        f'Job description context:\n{description}'
    )


def _validate_missing_skill_question(
    job,
    skill: Skill,
    item: dict[str, Any],
    seen_normalized: set[str],
    seen_hashes: set[str],
    seen_family_texts: list[tuple[str, str]],
) -> dict[str, Any]:
    question_text = _clean_string(item.get('question_text'))
    expected_signal = _clean_string(item.get('expected_signal'))
    family_key = normalize_skill_key(_clean_string(item.get('family_key'))[:120])
    coverage_area = normalize_skill_key(_clean_string(item.get('coverage_area'))[:80])
    if not question_text:
        return {'ok': False, 'reason': 'question_text_empty'}
    if not expected_signal:
        return {'ok': False, 'reason': 'expected_signal_empty'}
    if not family_key:
        return {'ok': False, 'reason': 'family_key_empty'}
    if not coverage_area:
        return {'ok': False, 'reason': 'coverage_area_empty'}
    if _is_technical_role_job(job) and _should_skip_missing_only_skill(job, _PlanLike(skill)):
        return {'ok': False, 'reason': 'generic_soft_skill_for_technical_role'}

    normalized = _normalize_question_text(question_text)
    question_hash = _hash_text(normalized)
    if (
        not normalized
        or question_hash in seen_hashes
        or _is_near_duplicate(normalized, seen_normalized)
        or _is_family_duplicate(family_key, normalized, seen_family_texts)
    ):
        return {'ok': False, 'reason': 'duplicate_question'}
    return {
        'ok': True,
        'question_text': question_text,
        'expected_signal': expected_signal,
        'family_key': family_key,
        'coverage_area': coverage_area,
        'normalized': normalized,
        'question_hash': question_hash,
    }


class _PlanLike:
    def __init__(self, skill: Skill):
        self.skill = skill


def _job_title(job) -> str:
    if not job:
        return ''
    return getattr(job, 'role', '') or getattr(job, 'position', '') or ''


def _search_text(value: str) -> str:
    cleaned = re.sub(r'[^a-z0-9+#.]+', ' ', (value or '').lower()).strip()
    return f' {cleaned} '


def _job_error_type(generation_job: QuestionGenerationJob) -> str:
    result = generation_job.result if isinstance(generation_job.result, dict) else {}
    return str(result.get('error_type') or result.get('status') or '').strip()


def _failed_job_can_retry(generation_job: QuestionGenerationJob) -> bool:
    result = generation_job.result if isinstance(generation_job.result, dict) else {}
    if result.get('retryable') is False:
        return False
    return _job_error_type(generation_job) not in {
        'failed_schema_or_bad_request',
        'bad_request',
        'invalid_json',
        'openai_invalid_json',
        'missing_skill',
        'openai_disabled',
    }


def _question_generation_error_result(
    exc: OpenAIQuestionGenerationError,
    skill_id: int,
    task_type: str,
) -> dict[str, Any]:
    return {
        'ok': False,
        'status': exc.error_type,
        'skill_id': skill_id,
        'task_type': task_type,
        'error_type': exc.error_type,
        'retryable': exc.retryable,
        'status_code': exc.status_code,
        'body_preview': exc.body_preview,
        'message': str(exc)[:500],
    }


def _question_generation_exception_result(exc: Exception, skill_id: int, task_type: str) -> dict[str, Any]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        error_type = 'timeout'
        retryable = True
        status_code = None
        body_preview = ''
    elif isinstance(exc, urllib.error.HTTPError):
        status_code = exc.code
        retryable = status_code in {429, 500, 502, 503, 504}
        error_type = 'failed_schema_or_bad_request' if status_code == 400 else ('retryable_http_error' if retryable else 'http_error')
        try:
            body_preview = exc.read().decode('utf-8', errors='ignore')[:1000]
        except Exception:
            body_preview = ''
    elif isinstance(exc, json.JSONDecodeError):
        error_type = 'invalid_json'
        retryable = False
        status_code = None
        body_preview = getattr(exc, 'doc', '')[:1000]
    elif isinstance(exc, ValueError):
        error_type = 'value_error'
        retryable = False
        status_code = None
        body_preview = ''
    elif isinstance(exc, RuntimeError):
        error_type = 'runtime_error'
        retryable = True
        status_code = None
        body_preview = ''
    else:
        error_type = 'unexpected_error'
        retryable = True
        status_code = None
        body_preview = ''
    return {
        'ok': False,
        'status': error_type,
        'skill_id': skill_id,
        'task_type': task_type,
        'error_type': error_type,
        'retryable': retryable,
        'status_code': status_code,
        'body_preview': body_preview,
        'message': str(exc)[:500],
    }


def _save_question_generation_failure(generation_job: QuestionGenerationJob, result: dict[str, Any], exc: Exception) -> None:
    max_attempts = max(1, int(getattr(settings, 'INTERVIEW_QUESTION_GENERATION_MAX_ATTEMPTS', 3)))
    retryable = bool(result.get('retryable'))
    will_retry = retryable and generation_job.attempts < max_attempts
    result['generation_job_id'] = generation_job.id
    result['attempts'] = generation_job.attempts
    result['max_attempts'] = max_attempts
    result['will_retry'] = will_retry
    generation_job.status = QuestionGenerationJob.Status.QUEUED if will_retry else QuestionGenerationJob.Status.FAILED
    generation_job.result = result
    generation_job.error_message = str(exc)[:2000]
    generation_job.finished_at = timezone.now()
    generation_job.save(update_fields=['status', 'result', 'error_message', 'finished_at', 'updated_at'])
    logger.warning(
        'Question generation worker job failed generation_job_id=%s skill_id=%s task_type=%s error_type=%s retryable=%s will_retry=%s attempts=%s max_attempts=%s',
        generation_job.id,
        generation_job.skill_id,
        generation_job.task_type,
        result.get('error_type'),
        retryable,
        will_retry,
        generation_job.attempts,
        max_attempts,
    )


def build_skill_question_bank(skill_id: int, task_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_ENABLED', True):
        return {'ok': True, 'status': 'disabled', 'skill_id': skill_id, 'task_type': task_type}
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_OPENAI_ENABLED', True) or not getattr(settings, 'OPENAI_API_KEY', ''):
        return {'ok': False, 'status': 'openai_disabled', 'skill_id': skill_id, 'task_type': task_type, 'message': 'Question bank OpenAI generation is disabled or not configured.'}

    skill = Skill.objects.filter(id=skill_id, is_active=True).first()
    if not skill:
        return {'ok': False, 'status': 'missing_skill', 'skill_id': skill_id, 'task_type': task_type}
    payload = payload or {}
    if task_type == QuestionGenerationJob.TaskType.CODING_GENERATION:
        target = int(payload.get('target_coding_questions') or getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0))
        batch_size = min(max(1, int(payload.get('batch_size') or getattr(settings, 'INTERVIEW_CODING_GENERATION_BATCH_SIZE', 2))), max(0, target - CodingQuestion.objects.filter(skill=skill, is_active=True).count()))
        if batch_size <= 0:
            return {'ok': True, 'status': 'enough_questions', 'skill_id': skill.id, 'task_type': task_type}
        generated = generate_coding_questions_with_openai(skill, batch_size)
        inserted = insert_coding_questions(skill, generated)
    else:
        target = int(payload.get('target_verbal_questions') or getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100))
        batch_size = min(max(1, int(payload.get('batch_size') or getattr(settings, 'INTERVIEW_QUESTION_GENERATION_BATCH_SIZE', 10))), max(0, target - SkillQuestion.objects.filter(skill=skill, is_active=True).count()))
        if batch_size <= 0:
            return {'ok': True, 'status': 'enough_questions', 'skill_id': skill.id, 'task_type': task_type}
        generated = generate_skill_questions_with_openai(skill, batch_size)
        inserted = insert_skill_questions(skill, generated)

    logger.info(
        'Question generation completed skill_id=%s task_type=%s generated_count=%s inserted_count=%s duplicate_skipped_count=%s failed_count=%s',
        skill.id,
        task_type,
        inserted['generated_count'],
        inserted['inserted_count'],
        inserted['duplicate_skipped_count'],
        inserted['failed_count'],
    )
    return {
        'ok': True,
        'status': 'completed',
        'skill_id': skill.id,
        'skill_key': skill.key,
        'task_type': task_type,
        **inserted,
    }


def generate_skill_questions_with_openai(skill: Skill, batch_size: int) -> list[dict[str, Any]]:
    prompt = (
        f'Generate {batch_size} reusable interview questions for the skill {skill.name}. '
        'These questions should be suitable across many jobs where this skill is required. '
        'Generate only for the requested Skill. Do not mention any company, job, candidate, or job description. '
        'Do not generate coding tasks here. Avoid generic useless questions. Mix basic, intermediate, and advanced difficulty. '
        'Include practical, scenario, and debugging questions where relevant. For non-technical skills, generate role-appropriate interview questions. '
        'family_key must be short and stable and group similar questions. question_text should be concise and interviewer-friendly. '
        'No duplicate questions within the response.\n\n'
        f'Skill category: {skill.category}\n'
        f'Skill aliases: {", ".join(_json_list(skill.aliases))[:MAX_SKILL_CONTEXT_CHARS]}'
    )
    parsed = _call_openai_json(prompt, _verbal_question_schema(), 'skill_question_bank')
    questions = parsed.get('questions') if isinstance(parsed, dict) else []
    return [item for item in questions or [] if isinstance(item, dict)]


def generate_coding_questions_with_openai(skill: Skill, batch_size: int) -> list[dict[str, Any]]:
    prompt = (
        f'Generate {batch_size} reusable coding interview tasks for the skill {skill.name}. '
        'These tasks should be suitable across many jobs where this skill is required. '
        'Generate only for the requested Skill. Do not mention any company, job, candidate, or job description. '
        'Be conservative and practical. Avoid duplicate tasks within the response.\n\n'
        f'Skill category: {skill.category}\n'
        f'Skill aliases: {", ".join(_json_list(skill.aliases))[:MAX_SKILL_CONTEXT_CHARS]}'
    )
    parsed = _call_openai_json(prompt, _coding_question_schema(), 'skill_coding_question_bank')
    questions = parsed.get('coding_questions') if isinstance(parsed, dict) else []
    return [item for item in questions or [] if isinstance(item, dict)]


def insert_skill_questions(skill: Skill, questions: list[dict[str, Any]]) -> dict[str, int]:
    stats = {'generated_count': len(questions), 'inserted_count': 0, 'duplicate_skipped_count': 0, 'failed_count': 0}
    existing = list(SkillQuestion.objects.filter(skill=skill).values('question_text', 'question_hash', 'family_key'))
    seen_normalized = {_normalize_question_text(item['question_text']) for item in existing}
    seen_hashes = {item['question_hash'] for item in existing if item['question_hash']}
    seen_family_texts = [(normalize_skill_key(item['family_key'] or ''), _normalize_question_text(item['question_text'])) for item in existing]

    for item in questions:
        question_text = _clean_string(item.get('question_text'))
        normalized = _normalize_question_text(question_text)
        question_hash = _hash_text(normalized)
        family_key = normalize_skill_key(_clean_string(item.get('family_key'))[:120] or skill.key)
        if not normalized or question_hash in seen_hashes or _is_near_duplicate(normalized, seen_normalized) or _is_family_duplicate(family_key, normalized, seen_family_texts):
            stats['duplicate_skipped_count'] += 1
            logger.info('Duplicate SkillQuestion skipped skill_id=%s family_key=%s question=%s', skill.id, family_key, question_text[:120])
            continue
        try:
            with transaction.atomic():
                SkillQuestion.objects.create(
                    skill=skill,
                    question_text=question_text[:4000],
                    question_hash=question_hash,
                    difficulty=_choice(item.get('difficulty'), SkillQuestion.Difficulty.values, SkillQuestion.Difficulty.INTERMEDIATE),
                    question_type=_choice(item.get('question_type'), SkillQuestion.QuestionType.values, SkillQuestion.QuestionType.CONCEPT),
                    family_key=family_key[:120],
                    expected_signal=_clean_string(item.get('expected_signal'))[:2000],
                    ideal_answer_points=_json_list(item.get('ideal_answer_points')),
                    evaluation_rubric=item.get('evaluation_rubric') if isinstance(item.get('evaluation_rubric'), dict) else {},
                    tags=_json_list(item.get('tags'))[:12],
                    source=SkillQuestion.Source.OPENAI,
                    is_active=True,
                )
            seen_normalized.add(normalized)
            seen_hashes.add(question_hash)
            seen_family_texts.append((family_key, normalized))
            stats['inserted_count'] += 1
        except IntegrityError:
            stats['duplicate_skipped_count'] += 1
        except Exception:
            logger.exception('SkillQuestion insert failed skill_id=%s', skill.id)
            stats['failed_count'] += 1
    return stats


def insert_coding_questions(skill: Skill, questions: list[dict[str, Any]]) -> dict[str, int]:
    stats = {'generated_count': len(questions), 'inserted_count': 0, 'duplicate_skipped_count': 0, 'failed_count': 0}
    existing = list(CodingQuestion.objects.filter(skill=skill).values('title', 'prompt', 'prompt_hash', 'family_key'))
    seen_prompts = {_normalize_question_text(item['prompt']) for item in existing}
    seen_hashes = {item['prompt_hash'] for item in existing if item['prompt_hash']}
    seen_titles = {normalize_skill_key(item['title']) for item in existing}

    for item in questions:
        title = _clean_string(item.get('title'))[:255]
        prompt = _clean_string(item.get('prompt'))
        normalized = _normalize_question_text(prompt)
        prompt_hash = _hash_text(normalized)
        family_key = normalize_skill_key(_clean_string(item.get('family_key'))[:120] or title or skill.key)
        title_key = normalize_skill_key(title)
        if not title or not normalized or prompt_hash in seen_hashes or title_key in seen_titles or _is_near_duplicate(normalized, seen_prompts):
            stats['duplicate_skipped_count'] += 1
            logger.info('Duplicate CodingQuestion skipped skill_id=%s family_key=%s title=%s', skill.id, family_key, title[:120])
            continue
        try:
            with transaction.atomic():
                CodingQuestion.objects.create(
                    skill=skill,
                    title=title,
                    slug=_unique_coding_slug(skill, title, prompt_hash),
                    prompt=prompt[:6000],
                    prompt_hash=prompt_hash,
                    difficulty=_choice(item.get('difficulty'), CodingQuestion.Difficulty.values, CodingQuestion.Difficulty.MEDIUM),
                    question_type=_choice(item.get('question_type'), CodingQuestion.QuestionType.values, CodingQuestion.QuestionType.FRAMEWORK_TASK),
                    topic=_clean_string(item.get('topic'))[:120],
                    family_key=family_key[:120],
                    input_format=_clean_string(item.get('input_format'))[:2000],
                    output_format=_clean_string(item.get('output_format'))[:2000],
                    constraints=_clean_string(item.get('constraints'))[:2000],
                    starter_code=item.get('starter_code') if isinstance(item.get('starter_code'), dict) else {},
                    test_cases=item.get('test_cases') if isinstance(item.get('test_cases'), list) else [],
                    hidden_test_cases=item.get('hidden_test_cases') if isinstance(item.get('hidden_test_cases'), list) else [],
                    expected_solution=_clean_string(item.get('expected_solution'))[:6000],
                    explanation=_clean_string(item.get('explanation'))[:3000],
                    time_limit_ms=_clamp_int(item.get('time_limit_ms'), 2000, 500, 10000),
                    memory_limit_mb=_clamp_int(item.get('memory_limit_mb'), 256, 64, 2048),
                    tags=_json_list(item.get('tags'))[:12],
                    source=CodingQuestion.Source.OPENAI,
                    is_active=True,
                )
            seen_prompts.add(normalized)
            seen_hashes.add(prompt_hash)
            seen_titles.add(title_key)
            stats['inserted_count'] += 1
        except IntegrityError:
            stats['duplicate_skipped_count'] += 1
        except Exception:
            logger.exception('CodingQuestion insert failed skill_id=%s', skill.id)
            stats['failed_count'] += 1
    return stats


def _call_openai_json(prompt: str, schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
    api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
    model = getattr(settings, 'OPENAI_MODEL', '').strip() or 'gpt-4.1-mini'
    if 'coding' in schema_name:
        timeout = max(1, int(getattr(settings, 'INTERVIEW_CODING_GENERATION_TIMEOUT_SECONDS', 60)))
    else:
        timeout = max(1, int(getattr(settings, 'INTERVIEW_QUESTION_GENERATION_TIMEOUT_SECONDS', 60)))
    if not api_key:
        raise RuntimeError('OpenAI API key is not configured.')
    body = json.dumps({
        'model': model,
        'input': prompt,
        'temperature': 0.2,
        'text': {
            'format': {
                'type': 'json_schema',
                'name': schema_name,
                'strict': True,
                'schema': schema,
            },
        },
    }).encode('utf-8')
    request = urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=body,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        if exc.code == 400:
            raise OpenAIQuestionGenerationError(
                f'OpenAI question generation bad request HTTP 400: {detail[:400]}',
                error_type='failed_schema_or_bad_request',
                retryable=False,
                status_code=exc.code,
                body_preview=detail,
            ) from exc
        retryable = exc.code in {429, 500, 502, 503, 504}
        raise OpenAIQuestionGenerationError(
            f'OpenAI question generation HTTP error {exc.code}: {detail[:400]}',
            error_type='retryable_http_error' if retryable else 'http_error',
            retryable=retryable,
            status_code=exc.code,
            body_preview=detail,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OpenAIQuestionGenerationError(
            f'OpenAI question generation timed out provider=openai model={model} timeout_seconds={timeout}.',
            error_type='timeout',
            retryable=True,
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise OpenAIQuestionGenerationError(
                f'OpenAI question generation timed out provider=openai model={model} timeout_seconds={timeout}.',
                error_type='timeout',
                retryable=True,
            ) from exc
        raise OpenAIQuestionGenerationError(
            f'OpenAI question generation network error: {reason}',
            error_type='network_error',
            retryable=True,
        ) from exc
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise OpenAIQuestionGenerationError(
            'OpenAI question generation returned invalid response JSON.',
            error_type='openai_invalid_json',
            retryable=False,
            body_preview=response_text,
        ) from exc
    output_text = _extract_output_text(payload)
    if not output_text:
        raise OpenAIQuestionGenerationError(
            'OpenAI question generation returned no structured output.',
            error_type='missing_structured_output',
            retryable=True,
            body_preview=json.dumps(payload)[:1000],
        )
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIQuestionGenerationError(
            'OpenAI question generation returned invalid structured JSON.',
            error_type='invalid_json',
            retryable=False,
            body_preview=output_text,
        ) from exc
    if not isinstance(parsed, dict):
        raise OpenAIQuestionGenerationError(
            'OpenAI question generation returned invalid JSON shape.',
            error_type='invalid_json',
            retryable=False,
            body_preview=output_text,
        )
    return parsed


def _verbal_question_schema() -> dict[str, Any]:
    question_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'question_text': {'type': 'string'},
            'difficulty': {'type': 'string', 'enum': SkillQuestion.Difficulty.values},
            'question_type': {'type': 'string', 'enum': SkillQuestion.QuestionType.values},
            'family_key': {'type': 'string'},
            'expected_signal': {'type': 'string'},
            'ideal_answer_points': {'type': 'array', 'items': {'type': 'string'}},
            'evaluation_rubric': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'strong': {'type': 'string'},
                    'average': {'type': 'string'},
                    'weak': {'type': 'string'},
                },
                'required': ['strong', 'average', 'weak'],
            },
            'tags': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['question_text', 'difficulty', 'question_type', 'family_key', 'expected_signal', 'ideal_answer_points', 'evaluation_rubric', 'tags'],
    }
    return {'type': 'object', 'additionalProperties': False, 'properties': {'questions': {'type': 'array', 'items': question_schema}}, 'required': ['questions']}


def _missing_verbal_question_schema() -> dict[str, Any]:
    question_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'question_text': {'type': 'string'},
            'difficulty': {'type': 'string', 'enum': SkillQuestion.Difficulty.values},
            'question_type': {'type': 'string', 'enum': SkillQuestion.QuestionType.values},
            'family_key': {'type': 'string'},
            'coverage_area': {'type': 'string'},
            'expected_signal': {'type': 'string'},
            'ideal_answer_points': {'type': 'array', 'items': {'type': 'string'}},
            'evaluation_rubric': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'strong': {'type': 'string'},
                    'average': {'type': 'string'},
                    'weak': {'type': 'string'},
                },
                'required': ['strong', 'average', 'weak'],
            },
            'tags': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': [
            'question_text',
            'difficulty',
            'question_type',
            'family_key',
            'coverage_area',
            'expected_signal',
            'ideal_answer_points',
            'evaluation_rubric',
            'tags',
        ],
    }
    return {'type': 'object', 'additionalProperties': False, 'properties': {'questions': {'type': 'array', 'items': question_schema}}, 'required': ['questions']}


def _coding_question_schema() -> dict[str, Any]:
    question_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'title': {'type': 'string'},
            'prompt': {'type': 'string'},
            'difficulty': {'type': 'string', 'enum': CodingQuestion.Difficulty.values},
            'question_type': {'type': 'string', 'enum': CodingQuestion.QuestionType.values},
            'topic': {'type': 'string'},
            'family_key': {'type': 'string'},
            'input_format': {'type': 'string'},
            'output_format': {'type': 'string'},
            'constraints': {'type': 'string'},
            'starter_code': {'type': 'object'},
            'test_cases': {'type': 'array'},
            'hidden_test_cases': {'type': 'array'},
            'expected_solution': {'type': 'string'},
            'explanation': {'type': 'string'},
            'time_limit_ms': {'type': 'integer'},
            'memory_limit_mb': {'type': 'integer'},
            'tags': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': [
            'title',
            'prompt',
            'difficulty',
            'question_type',
            'topic',
            'family_key',
            'input_format',
            'output_format',
            'constraints',
            'starter_code',
            'test_cases',
            'hidden_test_cases',
            'expected_solution',
            'explanation',
            'time_limit_ms',
            'memory_limit_mb',
            'tags',
        ],
    }
    return {'type': 'object', 'additionalProperties': False, 'properties': {'coding_questions': {'type': 'array', 'items': question_schema}}, 'required': ['coding_questions']}


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = str(payload.get('output_text') or '').strip()
    if output_text:
        return output_text
    for item in payload.get('output') or []:
        for content in item.get('content') or []:
            text = str(content.get('text') or '').strip()
            if text:
                return text
    return ''


def _normalize_question_text(value: str) -> str:
    text = re.sub(r'[^a-z0-9+#.]+', ' ', (value or '').lower())
    tokens = []
    for token in re.sub(r'\s+', ' ', text).strip().split():
        if token in QUESTION_FILLER_TOKENS:
            continue
        if token.endswith('ies') and len(token) > 4:
            token = f'{token[:-3]}y'
        elif token.endswith('s') and not token.endswith(('ss', 'css', 'js')) and len(token) > 3:
            token = token[:-1]
        tokens.append(token)
    return ' '.join(tokens)


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or '').encode('utf-8')).hexdigest()


def _is_near_duplicate(normalized: str, existing_normalized: set[str], threshold: float = 0.85) -> bool:
    if normalized in existing_normalized:
        return True
    tokens = set(normalized.split())
    if not tokens:
        return True
    for existing in existing_normalized:
        existing_tokens = set(existing.split())
        if not existing_tokens:
            continue
        if normalized.startswith(existing) or existing.startswith(normalized):
            return True
        union = tokens | existing_tokens
        if union and len(tokens & existing_tokens) / len(union) >= threshold:
            return True
    return False


def _is_family_duplicate(family_key: str, normalized: str, family_texts: list[tuple[str, str]]) -> bool:
    same_family = {text for existing_family, text in family_texts if existing_family == family_key}
    return _is_near_duplicate(normalized, same_family, threshold=0.72)


def _unique_coding_slug(skill: Skill, title: str, prompt_hash: str) -> str:
    base = normalize_skill_key(f'{skill.key}-{title}')[:220] or f'{skill.key}-coding-question'
    slug = base
    suffix = prompt_hash[:8]
    if CodingQuestion.objects.filter(slug=slug).exists():
        slug = f'{base[:246]}-{suffix}'
    return slug[:255]


def _is_coding_skill(skill: Skill) -> bool:
    category = (skill.category or '').strip().lower()
    return category in TECHNICAL_CODING_CATEGORIES or skill.key in TECHNICAL_CODING_SKILL_KEYS


def _choice(value: Any, allowed: list[str], default: str) -> str:
    item = str(value or '').strip()
    return item if item in allowed else default


def _clean_string(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _json_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or '').strip()]


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
