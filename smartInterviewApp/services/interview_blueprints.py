from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from smartInterviewApp.models import (
    JobInterviewBlueprint,
    JobInterviewSkill,
    QuestionGenerationJob,
    Skill,
    Vacancies,
    normalize_skill_key,
)
from smartInterviewApp.services.cloud_tasks import CloudTasksConfigurationError, CloudTasksScheduler


logger = logging.getLogger('smartInterview.interview_blueprints')

cloud_tasks_scheduler = CloudTasksScheduler()

DEFAULT_DIFFICULTY_MIX = {'basic': 1, 'intermediate': 2, 'advanced': 1}
ENTRY_PRIMARY_DIFFICULTY_MIX = {'basic': 2, 'intermediate': 3, 'advanced': 0}
ENTRY_SUPPORTING_DIFFICULTY_MIX = {'basic': 2, 'intermediate': 1, 'advanced': 0}
MID_PRIMARY_DIFFICULTY_MIX = {'basic': 1, 'intermediate': 3, 'advanced': 1}
MID_SUPPORTING_DIFFICULTY_MIX = {'basic': 1, 'intermediate': 2, 'advanced': 0}
DEFAULT_CODING_DIFFICULTY_MIX = {'easy': 0, 'medium': 1, 'hard': 0}
MAX_DESCRIPTION_CHARS = 7000

ROLE_PRIORITY = {
    'primary': 4,
    'primary_candidate': 3,
    'sub_skill': 2,
    'optional': 1,
}

CANONICAL_SKILL_NAMES = {
    'reactjs': 'React',
    'react-js': 'React',
    'react': 'React',
    'frontend-react': 'React',
    'reactnative': 'React Native',
    'react-native': 'React Native',
    'mobile-app-development': 'React Native',
    'mobile-development': 'React Native',
    'mongodb': 'MongoDB',
    'mongo-db': 'MongoDB',
    'mongo': 'MongoDB',
    'nosql': 'MongoDB',
    'restful-api': 'REST API',
    'restful-apis': 'REST API',
    'rest-api': 'REST API',
    'rest-apis': 'REST API',
    'api': 'REST API',
    'apis': 'REST API',
    'api-integration': 'REST API',
    'web-services': 'REST API',
    'backend-api': 'REST API',
    'nodejs': 'Node.js',
    'node-js': 'Node.js',
    'node': 'Node.js',
    'express': 'Node.js',
    'express-js': 'Node.js',
    'nextjs': 'Next.js',
    'next-js': 'Next.js',
    'next-js-framework': 'Next.js',
    'php': 'PHP',
    'laravel-php': 'Laravel',
    'html-css': 'HTML/CSS',
    'htmlcss': 'HTML/CSS',
    'html': 'HTML/CSS',
    'css': 'HTML/CSS',
    'responsive-ui': 'HTML/CSS',
    'responsive-design': 'HTML/CSS',
    'applicant-tracking-system': 'ATS',
    'recruitment': 'Talent Acquisition',
    'recruiting': 'Talent Acquisition',
    'hiring': 'Talent Acquisition',
    'sourcing': 'Candidate Sourcing',
    'resume-sourcing': 'Candidate Sourcing',
    'profile-sourcing': 'Candidate Sourcing',
    'screening-candidates': 'Candidate Screening',
    'candidate-screening': 'Candidate Screening',
    'interview-scheduling': 'Interview Coordination',
}

NOISY_SKILL_KEYS = {
    'full-time',
    'fulltime',
    'permanent',
    'b-tech',
    'btech',
    'b-e',
    'be',
    'mca',
    'degree',
    'industry-type',
    'department',
    'role-category',
    'quick-learner',
    'hard-working',
    'proactive',
    'self-driven',
    'team-player',
    'tasks',
    'projects',
    'project',
    'documentation',
    'standards',
    'employment-type',
    'education-requirement',
}

TECHNICAL_ROLE_TERMS = {
    'developer',
    'engineer',
    'software',
    'backend',
    'frontend',
    'fullstack',
    'full-stack',
    'devops',
    'data',
    'salesforce',
    'python',
    'java',
}

CENTRAL_SOFT_SKILL_KEYS = {
    'communication-skills',
    'communication',
    'negotiation',
    'client-communication',
}
PROCESS_SKILL_KEYS = {
    'agile',
    'scrum',
    'sdlc',
    'code-review',
    'documentation',
    'collaboration',
    'communication',
    'communication-skills',
}


@dataclass(frozen=True)
class ExtractedSkill:
    name: str
    category: str = ''
    skill_role: str = JobInterviewSkill.SkillRole.SUB_SKILL
    priority: int = 1
    questions_to_ask: int = 4
    coding_questions_to_ask: int = 0
    difficulty_mix: dict[str, int] | None = None
    coding_difficulty_mix: dict[str, int] | None = None
    confidence: float | None = None
    reason: str = ''
    original_name: str = ''
    interview_weight: str = 'normal'
    eligible_for_random_sub_skill: bool = True

    @classmethod
    def from_payload(cls, payload: dict[str, Any], priority: int, skill_role: str, experience_level: str = '') -> 'ExtractedSkill | None':
        original_name = _clean_string(payload.get('name'))
        name = _canonical_skill_name(original_name)
        if not name:
            return None
        questions_to_ask = _default_questions_to_ask(skill_role)
        difficulty_mix = _difficulty_mix_for(experience_level, skill_role)
        return cls(
            name=name[:120],
            category=_clean_string(payload.get('category'))[:80],
            skill_role=skill_role,
            priority=_clamp_int(payload.get('priority'), priority, 1, 99),
            questions_to_ask=_clamp_int(payload.get('questions_to_ask'), questions_to_ask, 1, 8),
            coding_questions_to_ask=_clamp_int(payload.get('coding_questions_to_ask'), 0, 0, 3),
            difficulty_mix=_clean_int_map(payload.get('difficulty_mix'), difficulty_mix),
            coding_difficulty_mix=_clean_int_map(payload.get('coding_difficulty_mix'), DEFAULT_CODING_DIFFICULTY_MIX),
            confidence=_clean_confidence(payload.get('confidence')),
            reason=_clean_string(payload.get('reason'))[:500],
            original_name=original_name[:120],
            interview_weight=_clean_string(payload.get('interview_weight'))[:20] or 'normal',
            eligible_for_random_sub_skill=bool(payload.get('eligible_for_random_sub_skill', True)),
        )


def schedule_job_interview_blueprint_after_commit(job_id: int | None) -> None:
    if not job_id or not getattr(settings, 'INTERVIEW_BLUEPRINT_ENABLED', True):
        return

    def _enqueue() -> None:
        try:
            result = enqueue_job_interview_blueprint(job_id)
            logger.info('Interview blueprint enqueue completed job_id=%s result=%s', job_id, result.get('mode'))
        except Exception:
            logger.exception('Interview blueprint enqueue failed job_id=%s', job_id)

    transaction.on_commit(_enqueue)


def enqueue_job_interview_blueprint(job_id: int, scheduler: CloudTasksScheduler | None = None) -> dict[str, Any]:
    if not getattr(settings, 'INTERVIEW_BLUEPRINT_ENABLED', True):
        return {'queued': False, 'mode': 'disabled', 'job_id': job_id}

    if not job_id:
        return {'queued': False, 'mode': 'noop'}

    cache_key = f'interview-blueprint:enqueue:{job_id}'
    if not cache.add(cache_key, '1', timeout=60):
        return {'queued': False, 'mode': 'deduped', 'job_id': job_id}

    generation_job = QuestionGenerationJob.objects.create(
        job_id=job_id,
        task_type=QuestionGenerationJob.TaskType.JD_SKILL_MAPPING,
        status=QuestionGenerationJob.Status.QUEUED,
        payload={'job_id': int(job_id)},
    )
    scheduler = scheduler or cloud_tasks_scheduler

    try:
        task_name = scheduler.create_http_task(
            task_id=scheduler.build_task_id('job-interview-blueprint', generation_job.id, job_id),
            relative_path='/internal/tasks/build-job-interview-blueprint/',
            payload={'generation_job_id': generation_job.id, 'job_id': int(job_id)},
            schedule_for=timezone.now(),
        )
        generation_job.result = {'task_name': task_name, 'mode': 'cloud_tasks'}
        generation_job.save(update_fields=['result', 'updated_at'])
        logger.info('Interview blueprint Cloud Task queued job_id=%s generation_job_id=%s', job_id, generation_job.id)
        return {
            'queued': True,
            'mode': 'cloud_tasks',
            'job_id': job_id,
            'generation_job_id': generation_job.id,
            'task_name': task_name,
        }
    except CloudTasksConfigurationError as exc:
        generation_job.result = {'mode': 'db_queue_only', 'message': str(exc)}
        generation_job.save(update_fields=['result', 'updated_at'])
        logger.warning(
            'Cloud Tasks unavailable for interview blueprint; stored DB queue only job_id=%s generation_job_id=%s',
            job_id,
            generation_job.id,
        )
        return {
            'queued': True,
            'mode': 'db_queue_only',
            'job_id': job_id,
            'generation_job_id': generation_job.id,
            'message': str(exc),
        }
    except Exception as exc:
        generation_job.status = QuestionGenerationJob.Status.FAILED
        generation_job.error_message = str(exc)[:2000]
        generation_job.finished_at = timezone.now()
        generation_job.save(update_fields=['status', 'error_message', 'finished_at', 'updated_at'])
        cache.delete(cache_key)
        logger.exception('Interview blueprint enqueue failed job_id=%s generation_job_id=%s', job_id, generation_job.id)
        raise


def process_job_interview_blueprint_task(generation_job_id: int | None, job_id: int | None = None) -> dict[str, Any]:
    generation_job = None
    if generation_job_id:
        generation_job = QuestionGenerationJob.objects.select_related('job').filter(id=generation_job_id).first()

    resolved_job_id = int(job_id or getattr(generation_job, 'job_id', 0) or 0)
    if not resolved_job_id:
        return {'ok': False, 'status': 'invalid_payload', 'message': 'Job id is required.'}

    if generation_job:
        if generation_job.status == QuestionGenerationJob.Status.SUCCESS:
            return {
                'ok': True,
                'status': 'already_processed',
                'job_id': resolved_job_id,
                'generation_job_id': generation_job.id,
                'blueprint_id': generation_job.blueprint_id,
            }
        if (
            generation_job.status == QuestionGenerationJob.Status.RUNNING
            and generation_job.started_at
            and generation_job.started_at >= timezone.now() - timedelta(minutes=10)
        ):
            return {
                'ok': True,
                'status': 'already_running',
                'job_id': resolved_job_id,
                'generation_job_id': generation_job.id,
            }

        generation_job.status = QuestionGenerationJob.Status.RUNNING
        generation_job.attempts += 1
        generation_job.started_at = timezone.now()
        generation_job.error_message = ''
        generation_job.save(update_fields=['status', 'attempts', 'started_at', 'error_message', 'updated_at'])

    try:
        result = build_job_interview_blueprint(resolved_job_id)
        if generation_job:
            generation_job.blueprint_id = result.get('blueprint_id')
            generation_job.status = QuestionGenerationJob.Status.SUCCESS if result.get('ok') else QuestionGenerationJob.Status.FAILED
            generation_job.result = result
            generation_job.error_message = '' if result.get('ok') else str(result.get('message') or '')[:2000]
            generation_job.finished_at = timezone.now()
            generation_job.save(update_fields=['blueprint', 'status', 'result', 'error_message', 'finished_at', 'updated_at'])
        return result
    except Exception as exc:
        logger.exception('Interview blueprint background task failed job_id=%s', resolved_job_id)
        if generation_job:
            generation_job.status = QuestionGenerationJob.Status.FAILED
            generation_job.error_message = str(exc)[:2000]
            generation_job.finished_at = timezone.now()
            generation_job.save(update_fields=['status', 'error_message', 'finished_at', 'updated_at'])
        return {'ok': False, 'status': 'failed', 'job_id': resolved_job_id, 'message': str(exc)}


def process_queued_interview_blueprint_jobs(limit: int = 25) -> list[dict[str, Any]]:
    jobs = list(
        QuestionGenerationJob.objects
        .filter(task_type=QuestionGenerationJob.TaskType.JD_SKILL_MAPPING, status=QuestionGenerationJob.Status.QUEUED)
        .order_by('created_at', 'id')[:limit]
    )
    return [process_job_interview_blueprint_task(job.id, job.job_id) for job in jobs]


def build_job_interview_blueprint(job_id: int) -> dict[str, Any]:
    logger.info('Interview blueprint generation started job_id=%s', job_id)
    job = Vacancies.objects.filter(id=job_id).first()
    if not job:
        logger.info('Interview blueprint skipped missing job_id=%s', job_id)
        return {'ok': True, 'status': 'skipped', 'job_id': job_id, 'message': 'Job no longer exists.'}

    extraction_source = JobInterviewBlueprint.GenerationSource.SYSTEM
    extracted_payload: dict[str, Any]
    error_message = ''

    try:
        if getattr(settings, 'INTERVIEW_BLUEPRINT_OPENAI_ENABLED', True) and getattr(settings, 'OPENAI_API_KEY', ''):
            extracted_payload = extract_skills_with_openai(job)
            extraction_source = JobInterviewBlueprint.GenerationSource.OPENAI
            logger.info('OpenAI skill extraction succeeded job_id=%s', job_id)
        else:
            raise RuntimeError('OpenAI skill extraction is disabled or not configured.')
    except Exception as exc:
        error_message = str(exc)[:2000]
        extracted_payload = fallback_extract_skills(job)
        extraction_source = JobInterviewBlueprint.GenerationSource.SYSTEM
        logger.info('Fallback skill mapping used job_id=%s reason=%s', job_id, error_message[:200])

    experience_level = _determine_experience_level(job, extracted_payload)
    raw_skills = _normalize_extracted_skill_groups(extracted_payload, experience_level, job)
    selected_skills, unmapped_skills, rejected_skills = _map_extracted_skills(raw_skills, job)
    selected_skills = sorted(selected_skills, key=lambda item: item[0].priority)
    selected_skill_ids = {skill.id for _, skill in selected_skills}
    selected_by_role = _selected_by_role(selected_skills, job, experience_level)
    blueprint_plan = _build_blueprint_plan(
        extracted_payload=extracted_payload,
        job=job,
        experience_level=experience_level,
        selected_by_role=selected_by_role,
        unmapped_skills=unmapped_skills,
        rejected_skills=rejected_skills,
    )

    with transaction.atomic():
        blueprint, _ = JobInterviewBlueprint.objects.select_for_update().get_or_create(
            job=job,
            defaults={'status': JobInterviewBlueprint.Status.PENDING},
        )
        blueprint.status = JobInterviewBlueprint.Status.GENERATING
        blueprint.role_title = _clean_string(extracted_payload.get('role_title'))[:255] or job.role
        blueprint.experience_level = experience_level[:80] or job.experience_required
        blueprint.raw_extracted_skills = [_skill_snapshot(skill) for skill in raw_skills]
        blueprint.blueprint_plan = blueprint_plan
        blueprint.generation_source = extraction_source
        blueprint.model_name = getattr(settings, 'OPENAI_MODEL', '') if extraction_source == JobInterviewBlueprint.GenerationSource.OPENAI else ''
        blueprint.error_message = error_message
        blueprint.save(update_fields=[
            'status',
            'role_title',
            'experience_level',
            'raw_extracted_skills',
            'blueprint_plan',
            'generation_source',
            'model_name',
            'error_message',
            'updated_at',
        ])

        for extracted, skill in selected_skills:
            JobInterviewSkill.objects.update_or_create(
                blueprint=blueprint,
                skill=skill,
                defaults={
                    'job': job,
                    'skill_role': extracted.skill_role,
                    'priority': extracted.priority,
                    'questions_to_ask': extracted.questions_to_ask,
                    'coding_questions_to_ask': _coding_questions_to_ask_for(job, extracted, skill),
                    'difficulty_mix': extracted.difficulty_mix or DEFAULT_DIFFICULTY_MIX,
                    'coding_difficulty_mix': _coding_difficulty_mix_for(blueprint.experience_level, _coding_questions_to_ask_for(job, extracted, skill)),
                    'source': (
                        JobInterviewSkill.Source.OPENAI
                        if extraction_source == JobInterviewBlueprint.GenerationSource.OPENAI
                        else JobInterviewSkill.Source.SYSTEM
                    ),
                    'confidence': extracted.confidence,
                    'is_required': True,
                    'is_active': True,
                },
            )

        JobInterviewSkill.objects.filter(blueprint=blueprint).exclude(skill_id__in=selected_skill_ids).update(is_active=False)

        snapshot = [
            {
                **_mapped_skill_snapshot(extracted, skill, job, blueprint.experience_level),
                'mapped': True,
            }
            for extracted, skill in selected_skills
        ]
        blueprint.selected_skills_snapshot = snapshot
        blueprint.blueprint_plan = _build_blueprint_plan(
            extracted_payload=extracted_payload,
            job=job,
            experience_level=experience_level,
            selected_by_role=_selected_by_role(selected_skills, job, experience_level),
            unmapped_skills=unmapped_skills,
            rejected_skills=rejected_skills,
        )
        blueprint.minimum_ready = bool(snapshot)
        blueprint.fully_ready = bool(snapshot) and not error_message
        blueprint.status = (
            JobInterviewBlueprint.Status.READY
            if blueprint.fully_ready
            else JobInterviewBlueprint.Status.PARTIAL
            if snapshot
            else JobInterviewBlueprint.Status.FAILED
        )
        if not snapshot and not blueprint.error_message:
            blueprint.error_message = 'No configured Skill records matched the job description.'
        blueprint.save(update_fields=[
            'selected_skills_snapshot',
            'blueprint_plan',
            'minimum_ready',
            'fully_ready',
            'status',
            'error_message',
            'updated_at',
        ])
        blueprint_id = blueprint.id
        transaction.on_commit(lambda: _enqueue_question_bank_coverage_check(blueprint_id))

    logger.info('Interview blueprint completed job_id=%s status=%s selected_skills=%s', job_id, blueprint.status, len(selected_skills))
    return {
        'ok': blueprint.status != JobInterviewBlueprint.Status.FAILED,
        'status': blueprint.status,
        'job_id': job.id,
        'blueprint_id': blueprint.id,
        'selected_skill_count': len(selected_skills),
        'source': extraction_source,
    }


def _enqueue_question_bank_coverage_check(blueprint_id: int) -> None:
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_ENABLED', True):
        return
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_AUTO_ENQUEUE_ON_BLUEPRINT', True):
        return
    try:
        from smartInterviewApp.services.question_banks import enqueue_question_generation_jobs

        enqueue_question_generation_jobs(blueprint_id)
    except Exception:
        logger.exception('Question bank coverage enqueue failed blueprint_id=%s', blueprint_id)


def extract_skills_with_openai(job: Vacancies) -> dict[str, Any]:
    api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
    model = getattr(settings, 'OPENAI_MODEL', '').strip() or 'gpt-4.1-mini'
    timeout = max(1, int(getattr(settings, 'INTERVIEW_BLUEPRINT_OPENAI_TIMEOUT_SECONDS', 20)))
    if not api_key:
        raise RuntimeError('OpenAI API key is not configured.')

    prompt = (
        'Extract interview skill requirements from this job description for any role or domain. '
        'Return JSON only using the requested schema. Extract skills exactly from the JD and infer only obvious related skills. '
        'Do not limit yourself to any predefined skill list. Do not invent unrelated skills. '
        'Preserve role-specific skills for non-technical roles. Do not force software categories for non-technical roles. '
        'Extract all meaningful skills from the JD; do not collapse the pool into only five items. '
        'Keep one primary skill separate from sub-skills. Include optional or alternate skills when the JD says "or". '
        'For full-stack roles, the primary skill should usually be a central programming/backend/frontend skill, not a database. '
        'Avoid employment type, education, personality adjectives, vague generic phrases, tasks, projects, and compliance boilerplate as skills. '
        'Use concise stable skill names such as REST API, React, React Native, Node.js, MongoDB, Talent Acquisition, SEO, Tally, GST, or Communication Skills.\n\n'
        f'Job title: {job.role}\n'
        f'Experience: {job.experience_required}\n'
        f'Job type: {job.job_type}\n'
        f'Location: {job.location}\n'
        f'Description:\n{(job.description or "")[:MAX_DESCRIPTION_CHARS]}'
    )
    body = json.dumps({
        'model': model,
        'input': prompt,
        'temperature': 0.1,
        'text': {
            'format': {
                'type': 'json_schema',
                'name': 'job_interview_skill_extract',
                'strict': True,
                'schema': _openai_response_schema(),
            },
        },
    }).encode('utf-8')
    request = urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            last_error = RuntimeError(f'OpenAI skill extraction HTTP error {exc.code}: {detail[:400]}')
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 1:
                raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = RuntimeError(f'OpenAI skill extraction network error: {exc.reason}')
            if attempt == 1:
                raise last_error from exc
        time.sleep(0.5)
    if payload is None:
        raise RuntimeError(str(last_error or 'OpenAI skill extraction failed.'))

    output_text = _extract_output_text(payload)
    if not output_text:
        raise RuntimeError('OpenAI skill extraction returned no structured output.')
    parsed = json.loads(output_text)
    if not isinstance(parsed, dict):
        raise RuntimeError('OpenAI skill extraction returned invalid JSON.')
    return parsed


def fallback_extract_skills(job: Vacancies) -> dict[str, Any]:
    text = _normalized_search_text(' '.join([
        job.role or '',
        job.description or '',
        job.experience_required or '',
        job.job_type or '',
        job.location or '',
    ]))
    extracted: list[dict[str, Any]] = []
    max_extracted = max(1, int(getattr(settings, 'INTERVIEW_BLUEPRINT_MAX_EXTRACTED_SKILLS', 20)))
    for skill in Skill.objects.filter(is_active=True).order_by('name'):
        terms = [skill.name, skill.key, *(_json_list(skill.aliases))]
        if any(_term_matches(text, term) for term in terms):
            extracted.append({
                'name': skill.name,
                'category': skill.category,
                'priority': len(extracted) + 1,
                'questions_to_ask': _default_questions_to_ask(JobInterviewSkill.SkillRole.PRIMARY if not extracted else JobInterviewSkill.SkillRole.SUB_SKILL),
                'coding_questions_to_ask': 1 if _is_coding_role(job, skill) else 0,
                'difficulty_mix': _difficulty_mix_for(_determine_experience_level(job, {}), JobInterviewSkill.SkillRole.PRIMARY if not extracted else JobInterviewSkill.SkillRole.SUB_SKILL),
                'coding_difficulty_mix': DEFAULT_CODING_DIFFICULTY_MIX,
                'confidence': 0.72,
            })
        if len(extracted) >= max_extracted:
            break
    return {
        'role_title': job.role,
        'experience_level': _determine_experience_level(job, {}),
        'primary_skill': extracted[0] if extracted else {},
        'primary_skill_candidates': extracted[:2],
        'sub_skills': extracted[1:],
        'optional_skills': [],
    }


def _map_extracted_skills(extracted_skills: list[ExtractedSkill], job: Vacancies) -> tuple[list[tuple[ExtractedSkill, Skill]], list[dict[str, Any]], list[dict[str, Any]]]:
    mapped: list[tuple[ExtractedSkill, Skill]] = []
    seen_skill_ids: set[int] = set()
    unmapped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    create_missing = bool(getattr(settings, 'INTERVIEW_BLUEPRINT_CREATE_MISSING_SKILLS', True))
    lookup = _skill_lookup()

    for extracted in extracted_skills:
        key = _skill_match_key(extracted.name)
        if _is_noisy_skill(extracted, job):
            rejected.append({**_skill_snapshot(extracted), 'reason': 'Rejected as noisy/non-skill phrase.'})
            continue
        skill = lookup.get(key)
        if not skill and create_missing and _safe_new_skill_key(key):
            aliases = []
            if extracted.original_name and extracted.original_name != extracted.name:
                aliases.append(extracted.original_name)
            skill, _ = Skill.objects.get_or_create(
                key=key,
                defaults={
                    'name': extracted.name[:120],
                    'category': extracted.category[:80],
                    'aliases': aliases,
                    'description': 'Auto-created from JD skill extraction.',
                    'is_active': True,
                },
            )
            lookup[key] = skill
            for alias in aliases:
                lookup[_skill_match_key(alias)] = skill
            logger.info('Interview blueprint created missing Skill key=%s', key)
        if not skill:
            unmapped.append({**_skill_snapshot(extracted), 'reason': 'No matching Skill record and auto-create disabled.'})
            continue
        if skill.id in seen_skill_ids:
            continue
        seen_skill_ids.add(skill.id)
        mapped.append((extracted, skill))
    return mapped, unmapped, rejected


def _skill_lookup() -> dict[str, Skill]:
    lookup: dict[str, Skill] = {}
    for skill in Skill.objects.filter(is_active=True):
        keys = [skill.key, normalize_skill_key(skill.name), _skill_match_key(skill.name)]
        keys.extend(_skill_match_key(alias) for alias in _json_list(skill.aliases))
        for key in keys:
            if key:
                lookup.setdefault(key, skill)
    return lookup


def _apply_blueprint_skill_quality_rules(skill: ExtractedSkill, job: Vacancies) -> ExtractedSkill:
    key = _skill_match_key(skill.name)
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '']))
    is_technical_role = _is_technical_role_text(role_text)
    skill_role = skill.skill_role
    interview_weight = skill.interview_weight or 'normal'
    eligible_for_random_sub_skill = skill.eligible_for_random_sub_skill

    if is_technical_role and key in {'php', 'laravel'} and _appears_as_low_confidence_or_alternative(key, role_text):
        skill_role = JobInterviewSkill.SkillRole.OPTIONAL
    if is_technical_role and key in PROCESS_SKILL_KEYS:
        skill_role = JobInterviewSkill.SkillRole.OPTIONAL
        interview_weight = 'low'
        eligible_for_random_sub_skill = False

    return ExtractedSkill(
        name=skill.name,
        category=skill.category,
        skill_role=skill_role,
        priority=skill.priority,
        questions_to_ask=_default_questions_to_ask(skill_role),
        coding_questions_to_ask=skill.coding_questions_to_ask,
        difficulty_mix=_difficulty_mix_for(job.experience_required, skill_role) if skill_role != skill.skill_role else skill.difficulty_mix,
        coding_difficulty_mix=skill.coding_difficulty_mix,
        confidence=skill.confidence,
        reason=skill.reason,
        original_name=skill.original_name,
        interview_weight=interview_weight,
        eligible_for_random_sub_skill=eligible_for_random_sub_skill,
    )


def _appears_as_low_confidence_or_alternative(key: str, role_text: str) -> bool:
    token = key.replace('-', ' ')
    mentions = role_text.count(f' {token} ')
    if mentions >= 2:
        return False
    return bool(re.search(r'\b(node\.?js|javascript|python|php|laravel)\s+or\s+(node\.?js|javascript|python|php|laravel)\b', role_text))


def _normalize_extracted_skill_groups(payload: dict[str, Any], experience_level: str, job: Vacancies) -> list[ExtractedSkill]:
    raw_entries: list[tuple[str, dict[str, Any]]] = []
    if isinstance(payload.get('primary_skill'), dict):
        raw_entries.append((JobInterviewSkill.SkillRole.PRIMARY, payload['primary_skill']))
    for item in payload.get('primary_skill_candidates') or []:
        if isinstance(item, dict):
            raw_entries.append((JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE, item))
    for item in payload.get('sub_skills') or []:
        if isinstance(item, dict):
            raw_entries.append((JobInterviewSkill.SkillRole.SUB_SKILL, item))
    for item in payload.get('optional_skills') or []:
        if isinstance(item, dict):
            raw_entries.append((JobInterviewSkill.SkillRole.OPTIONAL, item))
    for item in payload.get('skills') or []:
        if not isinstance(item, dict):
            continue
        raw_entries.append((JobInterviewSkill.SkillRole.SUB_SKILL, item))

    max_extracted = max(1, int(getattr(settings, 'INTERVIEW_BLUEPRINT_MAX_EXTRACTED_SKILLS', 20)))
    normalized_by_key: dict[str, ExtractedSkill] = {}
    for idx, (skill_role, item) in enumerate(raw_entries, start=1):
        skill = ExtractedSkill.from_payload(item, idx, skill_role, experience_level)
        if not skill:
            continue
        skill = _apply_blueprint_skill_quality_rules(skill, job)
        key = _skill_match_key(skill.name)
        existing = normalized_by_key.get(key)
        if existing and ROLE_PRIORITY.get(existing.skill_role, 0) >= ROLE_PRIORITY.get(skill.skill_role, 0):
            continue
        if existing:
            skill = ExtractedSkill(
                name=skill.name,
                category=skill.category or existing.category,
                skill_role=skill.skill_role,
                priority=min(existing.priority, skill.priority),
                questions_to_ask=_default_questions_to_ask(skill.skill_role),
                coding_questions_to_ask=max(existing.coding_questions_to_ask, skill.coding_questions_to_ask),
                difficulty_mix=_difficulty_mix_for(experience_level, skill.skill_role),
                coding_difficulty_mix=skill.coding_difficulty_mix or existing.coding_difficulty_mix,
                confidence=max(existing.confidence or 0, skill.confidence or 0),
                reason=skill.reason or existing.reason,
                original_name=skill.original_name or existing.original_name,
                interview_weight=skill.interview_weight,
                eligible_for_random_sub_skill=skill.eligible_for_random_sub_skill,
            )
        normalized_by_key[key] = skill

    return sorted(normalized_by_key.values(), key=lambda skill: skill.priority)[:max_extracted]


def _openai_response_schema() -> dict[str, Any]:
    skill_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'name': {'type': 'string'},
            'category': {'type': 'string'},
            'confidence': {'type': 'number'},
            'reason': {'type': 'string'},
        },
        'required': ['name', 'category', 'confidence', 'reason'],
    }
    candidate_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'name': {'type': 'string'},
            'category': {'type': 'string'},
            'confidence': {'type': 'number'},
        },
        'required': ['name', 'category', 'confidence'],
    }
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'role_title': {'type': 'string'},
            'experience_level': {'type': 'string'},
            'primary_skill': skill_schema,
            'primary_skill_candidates': {'type': 'array', 'items': candidate_schema, 'maxItems': 8},
            'sub_skills': {'type': 'array', 'items': candidate_schema, 'maxItems': 20},
            'optional_skills': {'type': 'array', 'items': candidate_schema, 'maxItems': 12},
        },
        'required': ['role_title', 'experience_level', 'primary_skill', 'primary_skill_candidates', 'sub_skills', 'optional_skills'],
    }


def _determine_experience_level(job: Vacancies, payload: dict[str, Any]) -> str:
    explicit_text = ' '.join([
        job.experience_required or '',
        job.description or '',
        job.role or '',
    ]).lower()
    explicit_text = explicit_text.replace('+', ' plus ')
    if re.search(r'\b(fresher|freshers|entry[- ]?level)\b', explicit_text):
        return 'Entry-level (0-3 years)'
    if re.search(r'\b(0\s*(?:-|to)\s*[123]|1\s*(?:-|to)\s*[23])\s*(years?|yrs?)?\b', explicit_text):
        return 'Entry-level (0-3 years)'
    if re.search(r'\b(8\s*(plus|and above)|8\s*(?:-|to)\s*(?:12|15|20)|8\s*(?:years?|yrs?)?\s*plus|8\s*\+|10\s*\+|10\s*(?:years?|yrs?)?\s*plus)\b', explicit_text):
        return 'Lead/Principal (8+ years)'
    if re.search(r'\b(5\s*(?:-|to)\s*8|6\s*(?:-|to)\s*8|5\s*(?:years?|yrs?)?\s*plus)\s*(years?|yrs?)?\b', explicit_text):
        return 'Senior (5-8 years)'
    if re.search(r'\b(3\s*(?:-|to)\s*5|4\s*(?:-|to)\s*5)\s*(years?|yrs?)?\b', explicit_text):
        return 'Mid-level (3-5 years)'
    return _clean_string(payload.get('experience_level'))[:80] or job.experience_required or ''


def _default_questions_to_ask(skill_role: str) -> int:
    if skill_role == JobInterviewSkill.SkillRole.PRIMARY:
        return max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_PRIMARY_QUESTIONS', 5)))
    return max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_SUB_SKILL_QUESTIONS', 3)))


def _difficulty_mix_for(experience_level: str, skill_role: str) -> dict[str, int]:
    normalized = (experience_level or '').lower()
    is_primary = skill_role == JobInterviewSkill.SkillRole.PRIMARY
    if 'entry-level' in normalized or '0-3' in normalized:
        return dict(ENTRY_PRIMARY_DIFFICULTY_MIX if is_primary else ENTRY_SUPPORTING_DIFFICULTY_MIX)
    if 'mid-level' in normalized or '3-5' in normalized:
        return dict(MID_PRIMARY_DIFFICULTY_MIX if is_primary else MID_SUPPORTING_DIFFICULTY_MIX)
    return dict(DEFAULT_DIFFICULTY_MIX if is_primary else MID_SUPPORTING_DIFFICULTY_MIX)


def _selected_by_role(selected_skills: list[tuple[ExtractedSkill, Skill]], job: Vacancies | None = None, experience_level: str = '') -> dict[str, list[dict[str, Any]]]:
    grouped = {
        JobInterviewSkill.SkillRole.PRIMARY: [],
        JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE: [],
        JobInterviewSkill.SkillRole.SUB_SKILL: [],
        JobInterviewSkill.SkillRole.OPTIONAL: [],
    }
    for extracted, skill in selected_skills:
        grouped.setdefault(extracted.skill_role, []).append(_mapped_skill_snapshot(extracted, skill, job, experience_level))
    if not grouped[JobInterviewSkill.SkillRole.PRIMARY]:
        for role in [JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE, JobInterviewSkill.SkillRole.SUB_SKILL, JobInterviewSkill.SkillRole.OPTIONAL]:
            if grouped.get(role):
                promoted = dict(grouped[role][0])
                promoted['skill_role'] = JobInterviewSkill.SkillRole.PRIMARY
                grouped[JobInterviewSkill.SkillRole.PRIMARY].append(promoted)
                break
    return grouped


def _build_blueprint_plan(
    extracted_payload: dict[str, Any],
    job: Vacancies,
    experience_level: str,
    selected_by_role: dict[str, list[dict[str, Any]]],
    unmapped_skills: list[dict[str, Any]],
    rejected_skills: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = (selected_by_role.get(JobInterviewSkill.SkillRole.PRIMARY) or [{}])[0]
    return {
        'blueprint_version': 2,
        'role_title': _clean_string(extracted_payload.get('role_title'))[:255] or job.role,
        'experience_level': experience_level,
        'primary_skill': primary,
        'primary_skill_candidates': selected_by_role.get(JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE, []),
        'sub_skills': selected_by_role.get(JobInterviewSkill.SkillRole.SUB_SKILL, []),
        'optional_skills': selected_by_role.get(JobInterviewSkill.SkillRole.OPTIONAL, []),
        'unmapped_skills': unmapped_skills,
        'rejected_skills': rejected_skills,
        'runtime_policy': {
            'selection_strategy': 'primary_plus_random_sub_skills',
            'primary_questions_to_ask': max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_PRIMARY_QUESTIONS', 5))),
            'sub_skills_to_pick': max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_SUB_SKILLS_TO_PICK', 3))),
            'questions_per_sub_skill': max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_SUB_SKILL_QUESTIONS', 3))),
            'coding_questions_per_primary': 1,
            'prefer_mapped_skills': True,
            'prefer_skills_with_question_bank': True,
            'avoid_same_family_key_repeats': True,
        },
    }


def _mapped_skill_snapshot(extracted: ExtractedSkill, skill: Skill, job: Vacancies | None = None, experience_level: str = '') -> dict[str, Any]:
    snapshot = _skill_snapshot(extracted)
    snapshot['name'] = skill.name
    snapshot['mapped_name'] = skill.name
    snapshot['original_name'] = extracted.original_name or extracted.name
    if job:
        coding_count = _coding_questions_to_ask_for(job, extracted, skill)
        snapshot['coding_questions_to_ask'] = coding_count
        snapshot['coding_difficulty_mix'] = _coding_difficulty_mix_for(experience_level, coding_count)
    return {
        **snapshot,
        'mapped': True,
        'skill_id': skill.id,
        'skill_key': skill.key,
    }


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


def _skill_snapshot(skill: ExtractedSkill) -> dict[str, Any]:
    return {
        'name': skill.name,
        'category': skill.category,
        'skill_role': skill.skill_role,
        'priority': skill.priority,
        'questions_to_ask': skill.questions_to_ask,
        'coding_questions_to_ask': skill.coding_questions_to_ask,
        'difficulty_mix': skill.difficulty_mix or DEFAULT_DIFFICULTY_MIX,
        'coding_difficulty_mix': skill.coding_difficulty_mix or DEFAULT_CODING_DIFFICULTY_MIX,
        'confidence': skill.confidence,
        'reason': skill.reason,
        'original_name': skill.original_name,
        'interview_weight': skill.interview_weight,
        'eligible_for_random_sub_skill': skill.eligible_for_random_sub_skill,
    }


def _canonical_skill_name(value: str) -> str:
    cleaned = _clean_string(value)
    if not cleaned:
        return ''
    key = normalize_skill_key(cleaned)
    compact_key = re.sub(r'[^a-z0-9]+', '', key.lower())
    canonical = CANONICAL_SKILL_NAMES.get(key) or CANONICAL_SKILL_NAMES.get(compact_key)
    if canonical:
        return canonical
    if cleaned.lower() == 'php':
        return 'PHP'
    if cleaned.lower() in {'html css', 'html/css', 'html-css'}:
        return 'HTML/CSS'
    return cleaned[:1].upper() + cleaned[1:] if cleaned.islower() else cleaned


def _skill_match_key(value: str) -> str:
    canonical = _canonical_skill_name(value)
    key = normalize_skill_key(canonical)
    if key in CANONICAL_SKILL_NAMES:
        key = normalize_skill_key(CANONICAL_SKILL_NAMES[key])
    compact_key = re.sub(r'[^a-z0-9]+', '', key.lower())
    if compact_key in CANONICAL_SKILL_NAMES:
        key = normalize_skill_key(CANONICAL_SKILL_NAMES[compact_key])
    return _singularize_skill_key(key)


def _singularize_skill_key(key: str) -> str:
    if key in {'apis', 'restful-apis', 'rest-apis'}:
        return 'rest-api'
    if key.endswith('ies') and len(key) > 4:
        return f'{key[:-3]}y'
    if key.endswith('s') and not key.endswith(('ss', 'css', 'js')) and len(key) > 3:
        return key[:-1]
    return key


def _is_noisy_skill(extracted: ExtractedSkill, job: Vacancies) -> bool:
    key = _skill_match_key(extracted.name)
    if key in NOISY_SKILL_KEYS:
        return True
    if len(key) <= 1:
        return True
    if re.fullmatch(r'\d+[-+]?\d*\s*(years?|yrs?)?', extracted.name.lower()):
        return True
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '']))
    role_tokens = set(role_text.split())
    is_technical_role = bool(role_tokens & TECHNICAL_ROLE_TERMS)
    if is_technical_role and key in CENTRAL_SOFT_SKILL_KEYS:
        return True
    return False


def _is_technical_role_text(normalized_role_text: str) -> bool:
    return bool(set(normalized_role_text.split()) & TECHNICAL_ROLE_TERMS)


def _is_technical_skill(skill: Skill) -> bool:
    key = _skill_match_key(skill.name)
    category = (skill.category or '').lower()
    return key in {
        'angular',
        'apex',
        'core-java',
        'django',
        'django-rest-framework',
        'flutter',
        'html-css',
        'javascript',
        'laravel',
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
    } or any(term in category for term in ['backend', 'frontend', 'programming', 'database', 'mobile', 'web services', 'salesforce'])


def _coding_questions_to_ask_for(job: Vacancies, extracted: ExtractedSkill, skill: Skill) -> int:
    if extracted.skill_role != JobInterviewSkill.SkillRole.PRIMARY:
        return 0
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '', skill.name or '', skill.category or '']))
    if _is_technical_role_text(role_text) and _is_technical_skill(skill):
        return 1
    return 0


def _coding_difficulty_mix_for(experience_level: str, coding_questions_to_ask: int) -> dict[str, int]:
    if coding_questions_to_ask <= 0:
        return dict(DEFAULT_CODING_DIFFICULTY_MIX)
    normalized = (experience_level or '').lower()
    if 'entry-level' in normalized or '0-3' in normalized:
        return {'easy': 1, 'medium': 0, 'hard': 0}
    if 'senior' in normalized or '5-8' in normalized or 'lead' in normalized or '8+' in normalized:
        return {'easy': 0, 'medium': 1, 'hard': 1} if coding_questions_to_ask > 1 else {'easy': 0, 'medium': 1, 'hard': 0}
    return {'easy': 0, 'medium': 1, 'hard': 0}


def _clean_string(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clean_int_map(value: Any, default: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        return dict(default)
    return {key: max(0, int(value.get(key, fallback) or 0)) for key, fallback in default.items()}


def _clean_confidence(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, parsed))


def _json_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or '').strip()]


def _normalized_search_text(value: str) -> str:
    cleaned = re.sub(r'[^a-z0-9+#.]+', ' ', (value or '').lower())
    normalized = re.sub(r'\s+', ' ', cleaned).strip()
    return f' {normalized} '


def _term_matches(search_text: str, term: str) -> bool:
    normalized = _normalized_search_text(term).strip()
    if not normalized:
        return False
    return f' {normalized} ' in search_text


def _is_coding_role(job: Vacancies, skill: Skill) -> bool:
    text = _normalized_search_text(' '.join([job.role or '', job.description or '', skill.category or '', skill.name or '']))
    return any(term in text for term in [' developer ', ' engineer ', ' backend ', ' frontend ', ' fullstack ', ' software ', ' api '])


def _safe_new_skill_key(key: str) -> bool:
    return bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{1,118}[a-z0-9]', key or ''))
