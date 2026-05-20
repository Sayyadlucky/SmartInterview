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
from smartInterviewApp.services.blueprint_plan_signature import ensure_blueprint_plan_signature
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
    'etl': 'ETL / ELT',
    'elt': 'ETL / ELT',
    'etl-elt': 'ETL / ELT',
    'sql': 'SQL',
    'data-pipeline': 'Data Pipelines',
    'data-pipelines': 'Data Pipelines',
    'data-modeling': 'Data Modeling',
    'data-modelling': 'Data Modeling',
    'data-quality': 'Data Quality / Validation',
    'data-validation': 'Data Quality / Validation',
    'data-quality-validation': 'Data Quality / Validation',
    'data-warehouse': 'Data Warehousing',
    'data-warehousing': 'Data Warehousing',
    'data-engineer': 'Data Engineering',
    'data-engineering': 'Data Engineering',
    'data-architect': 'Data Architecture',
    'data-architecture': 'Data Architecture',
    'multithreading-and-concurrency': 'Multithreading and Concurrency',
    'collection-framework': 'Collections Framework',
    'collections-framework': 'Collections Framework',
    'java-concurrency-and-collection': 'Java Concurrency and Collections',
    'java-concurrency-and-collections': 'Java Concurrency and Collections',
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
    'api',
    'automation',
    'backend',
    'cloud',
    'code',
    'coding',
    'developer',
    'development',
    'devops',
    'engineer',
    'frontend',
    'fullstack',
    'full-stack',
    'ios',
    'mobile',
    'programmer',
    'qa',
    'salesforce',
    'sdet',
    'software',
}

TECHNICAL_ROLE_PHRASES = {
    'android developer',
    'automation engineer',
    'backend developer',
    'backend engineer',
    'cloud engineer',
    'data engineer',
    'devops engineer',
    'front end developer',
    'front end engineer',
    'frontend developer',
    'frontend engineer',
    'full stack developer',
    'full stack engineer',
    'fullstack developer',
    'fullstack engineer',
    'ios developer',
    'java developer',
    'mobile developer',
    'node developer',
    'python developer',
    'qa automation',
    'react developer',
    'salesforce developer',
    'site reliability engineer',
    'software developer',
    'software engineer',
    'web developer',
}

HIGH_PRIORITY_TECHNICAL_CATEGORIES = {
    'programming_language',
    'framework',
    'backend_framework',
    'frontend_framework',
    'mobile_framework',
    'platform_development',
    'database_query_language',
    'data_engineering_platform',
    'development_platform',
}
MEDIUM_PRIORITY_TECHNICAL_CATEGORIES = {
    'api',
    'api_web_services',
    'backend',
    'backend_development',
    'build_tool',
    'database',
    'devops_tool',
    'frontend',
    'frontend_development',
    'mobile_development',
    'software_development',
    'testing_debugging',
    'web_services',
}
CLOUD_PRIMARY_CATEGORIES = {'cloud', 'cloud_platform'}
AUTOMATION_PRIMARY_CATEGORIES = {'automation_framework', 'test_automation', 'qa_automation'}
CRM_PRIMARY_CATEGORIES = {'crm_platform', 'salesforce', 'salesforce_development', 'development_platform'}
LOW_PRIORITY_TECHNICAL_PRIMARY_CATEGORIES = {
    'agile',
    'communication',
    'documentation',
    'industry_trends',
    'leadership',
    'problem_solving',
    'process',
    'soft_skill',
    'soft_skills',
    'teamwork',
    'version_control',
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
    'communication-skill',
    'communication-skills',
    'industry-trends',
    'industry-trends-awareness',
    'leadership',
    'problem-solving',
    'soft-skill',
    'soft-skills',
    'stakeholder-management',
    'teamwork',
}

SOFT_CODING_TARGET_KEYS = {
    'adaptability',
    'analytical-skill',
    'analytical-skills',
    'collaboration',
    'communication-skill',
    'communication-skills',
    'communication',
    'decision-making',
    'leadership',
    'problem-solving',
    'stakeholder-management',
    'teamwork',
    'time-management',
}

JAVA_CODING_TARGET_KEYS = {
    'collection-framework',
    'collections-framework',
    'concurrency',
    'java-concurrency-and-collection',
    'java-concurrency-and-collections',
    'multithreading',
    'multithreading-and-concurrency',
}

INFRASTRUCTURE_SKILL_EVIDENCE_TERMS = {
    'kubernetes': ['kubernetes', 'k8s', 'container orchestration', 'orchestration platform'],
    'docker': ['docker', 'containerization', 'containerised', 'containerized containers'],
    'ci-cd': ['ci/cd', 'cicd', 'continuous integration', 'continuous delivery', 'continuous deployment'],
    'terraform': ['terraform', 'infrastructure as code', 'iac'],
    'devops': ['devops', 'devsecops'],
    'cloud': ['cloud', 'aws', 'azure', 'gcp', 'google cloud'],
    'microservices': ['microservices', 'microservice architecture'],
}

DATA_ROLE_EVIDENCE_TERMS = [
    'data architect',
    'data architecture',
    'data engineer',
    'data engineering',
    'data modeling',
    'data modelling',
    'data pipeline',
    'data pipelines',
    'data quality',
    'data system',
    'data systems',
    'data validation',
    'data warehouse',
    'data warehousing',
    'database architect',
    'etl',
    'elt',
    'validation',
    'warehousing',
]

DATA_PRIMARY_RULES = [
    ('Data Architecture', 'Data Architecture', ['data architect', 'data architecture', 'database architect', 'data modeling', 'data modelling']),
    ('Data Engineering', 'Data Engineering', ['data engineer', 'data engineering', 'data pipeline', 'data pipelines', 'etl', 'elt']),
    ('Data Warehousing', 'Data Warehousing', ['data warehouse', 'data warehousing', 'warehousing']),
]

DATA_CODING_TARGET_RULES = [
    ('SQL', 'Database Query Language', ['sql', 'database architect', 'data warehouse', 'data warehousing', 'warehousing']),
    ('ETL / ELT', 'Data Engineering', ['etl', 'elt', 'extract transform load']),
    ('Data Pipelines', 'Data Engineering', ['data pipeline', 'data pipelines', 'pipeline development']),
    ('Data Modeling', 'Data Architecture', ['data modeling', 'data modelling', 'schema design', 'dimensional modeling']),
    ('Data Quality / Validation', 'Data Quality', ['data quality', 'data validation', 'validation']),
    ('Data Warehousing', 'Data Warehousing', ['data warehouse', 'data warehousing', 'warehousing']),
]


@dataclass(frozen=True)
class ExtractedSkill:
    name: str
    category: str = ''
    skill_role: str = JobInterviewSkill.SkillRole.SUB_SKILL
    priority: int = 1
    questions_to_ask: int = 4
    coding_required: bool | None = None
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
        raw_questions_to_ask = payload.get('questions_to_ask')
        if raw_questions_to_ask is None:
            raw_questions_to_ask = payload.get('target_questions')
        difficulty_mix = _difficulty_mix_for(experience_level, skill_role)
        return cls(
            name=name[:120],
            category=_clean_string(payload.get('category'))[:80],
            skill_role=skill_role,
            priority=_clamp_int(payload.get('priority'), priority, 1, 99),
            questions_to_ask=_clamp_int(raw_questions_to_ask, questions_to_ask, 1, 8),
            coding_required=_clean_bool_or_none(payload.get('coding_required')),
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

    extracted_payload = validate_and_repair_blueprint_payload(job, extracted_payload)
    experience_level = _determine_experience_level(job, extracted_payload)
    raw_skills = _normalize_extracted_skill_groups(extracted_payload, experience_level, job)
    selected_skills, unmapped_skills, rejected_skills = _map_extracted_skills(raw_skills, job)
    selected_skills = _apply_runtime_section_selection(selected_skills, extracted_payload, job, experience_level)
    if not _has_authoritative_runtime_sections(extracted_payload) or _primary_selection_needs_repair(selected_skills, job):
        selected_skills = _ensure_primary_skill_selection(selected_skills, job, experience_level)
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
        quality_issue = _clean_string(blueprint.blueprint_plan.get('quality_issue')) if isinstance(blueprint.blueprint_plan, dict) else ''
        blueprint.minimum_ready = bool(snapshot)
        blueprint.fully_ready = bool(snapshot) and not error_message and not quality_issue
        blueprint.status = (
            JobInterviewBlueprint.Status.READY
            if blueprint.fully_ready
            else JobInterviewBlueprint.Status.PARTIAL
            if snapshot
            else JobInterviewBlueprint.Status.FAILED
        )
        if not snapshot and not blueprint.error_message:
            blueprint.error_message = 'No configured Skill records matched the job description.'
        elif quality_issue and not blueprint.error_message:
            blueprint.error_message = quality_issue
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
        'Extract an authoritative generic runtime interview blueprint from this job description for any role or domain. '
        'Return JSON only using the requested schema. Extract skills exactly from the JD and infer only obvious related skills. '
        'Do not limit yourself to any predefined skill list. Do not invent unrelated skills. '
        'Preserve role-specific skills for non-technical roles. Do not force software categories for non-technical roles. '
        'Extract all meaningful skills from the JD; do not collapse the pool into only five items. '
        'Keep one primary skill separate from sub-skills. Include optional or alternate skills when the JD says "or". '
        'Classify role_family as technical, non_technical, or hybrid. Set technical_interview and coding_required from the JD. '
        'Hands-on technical execution roles should generally require coding or practical problem-solving tasks. '
        'Non-technical roles should not require coding unless the JD explicitly requires technical or coding exercises. '
        'coding_skill_targets must contain practical skill names suitable for coding/problem-solving tasks when coding_required is true, otherwise it must be empty. '
        'coding_questions_to_ask must be 3 when coding_required is true and 0 when false. '
        'runtime_sections and interview_sections are the final interview runtime plan: include exactly one primary section and up to three most relevant sub-skill sections. '
        'Every section must include target_questions, selection_basis, reason, coding_required, and coding_questions_to_ask. '
        'For technical roles, choose a concrete hands-on execution skill as primary rather than soft/process skills. '
        'Choose sub-skill runtime sections based on JD relevance and adjacency to the primary skill, not generic availability. '
        'Exclude useful-but-not-critical skills from runtime_sections and list them in excluded_skills with concrete reasons. '
        'Avoid employment type, education, personality adjectives, vague generic phrases, tasks, projects, and compliance boilerplate as skills. '
        'Use concise stable skill names.\n\n'
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
    primary_skill = extracted[0] if extracted else {}
    sub_skills = extracted[1:]
    runtime_sections = []
    if primary_skill:
        runtime_sections.append({
            **primary_skill,
            'skill_role': JobInterviewSkill.SkillRole.PRIMARY,
            'target_questions': _default_questions_to_ask(JobInterviewSkill.SkillRole.PRIMARY),
            'selection_basis': 'fallback_primary_match',
            'reason': 'Best available fallback match from the job description.',
        })
    for item in sub_skills[:3]:
        runtime_sections.append({
            **item,
            'skill_role': JobInterviewSkill.SkillRole.SUB_SKILL,
            'target_questions': _default_questions_to_ask(JobInterviewSkill.SkillRole.SUB_SKILL),
            'selection_basis': 'fallback_sub_skill_match',
            'reason': 'Relevant fallback match from the job description.',
        })
    coding_required = bool(primary_skill and _is_coding_role(job, Skill(name=primary_skill.get('name', ''), category=primary_skill.get('category', ''))))
    role_family = _role_family_for(job, {'coding_required': coding_required})
    coding_targets = [primary_skill.get('name', '')] if coding_required and primary_skill.get('name') else []
    return {
        'role_title': job.role,
        'role_domain': '',
        'role_subdomain': '',
        'role_family': role_family,
        'technical_interview': role_family in {'technical', 'hybrid'},
        'experience_level': _determine_experience_level(job, {}),
        'primary_skill': primary_skill,
        'primary_skill_candidates': extracted[:2],
        'sub_skills': sub_skills,
        'optional_skills': [],
        'runtime_sections': runtime_sections,
        'interview_sections': runtime_sections,
        'coding_required': coding_required,
        'coding_skill_targets': coding_targets,
        'coding_primary_skill': primary_skill.get('name', '') if coding_required else '',
        'coding_questions_to_ask': 3 if coding_required else 0,
        'excluded_skills': [],
    }


def validate_and_repair_blueprint_payload(job: Vacancies, payload: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(payload or {})
    warnings: list[dict[str, Any]] = []
    title_text = _normalized_search_text(' '.join([job.role or '', job.position or '']))
    jd_text = _normalized_search_text(' '.join([
        job.description or '',
        job.experience_required or '',
        job.job_type or '',
        job.location or '',
    ]))
    full_text = _normalized_search_text(f'{title_text} {jd_text}')

    role_family = _role_family_for(job, repaired)
    technical_interview = _technical_interview_for(job, repaired, role_family)
    data_role = _is_data_role_text(full_text)
    if data_role and role_family == 'non_technical':
        role_family = 'technical'
        technical_interview = True
    if not data_role and role_family == 'technical' and not _is_technical_role_text(full_text):
        role_family = 'non_technical'
        technical_interview = False
    coding_required = _clean_bool_or_none(repaired.get('coding_required'))
    if coding_required is None:
        coding_required = bool(technical_interview and _is_hands_on_technical_text(full_text))
    if role_family == 'non_technical' and not _jd_explicitly_requires_coding(full_text):
        coding_required = False
        technical_interview = False
    repaired['role_family'] = role_family
    repaired['technical_interview'] = bool(technical_interview)

    primary_name = _payload_skill_name(repaired.get('primary_skill'))
    unsupported_primary = bool(primary_name and not _primary_skill_supported(primary_name, title_text, jd_text, data_role=data_role))
    if unsupported_primary:
        warnings.append({'code': 'unsupported_primary_skill', 'skill': primary_name})

    repaired_primary = ''
    soft_primary_invalid = role_family in {'technical', 'hybrid'} and _is_soft_or_generic_skill_name(primary_name)
    if data_role and (not primary_name or unsupported_primary or soft_primary_invalid or _is_infrastructure_skill_without_evidence(primary_name, full_text)):
        repaired_primary = _best_data_primary(title_text, jd_text)
    elif unsupported_primary or soft_primary_invalid or _is_infrastructure_skill_without_evidence(primary_name, full_text):
        repaired_primary = _best_supported_primary_from_payload(repaired, title_text, jd_text, data_role=data_role)

    if repaired_primary and _skill_match_key(repaired_primary) != _skill_match_key(primary_name):
        repaired['primary_skill'] = _skill_payload(repaired_primary, _category_for_repaired_skill(repaired_primary), 0.92, 'Repaired to strongest JD-supported primary skill.')
        warnings.append({'code': 'repaired_primary_skill', 'from': primary_name, 'to': repaired_primary})
        _ensure_skill_payload_in_group(repaired, 'primary_skill_candidates', repaired['primary_skill'])

    if data_role:
        _ensure_data_role_skills(repaired, title_text, jd_text)

    raw_targets = _raw_coding_skill_target_names(repaired)
    rejected_targets: list[str] = []
    accepted_targets: list[str] = []
    infra_without_evidence: list[str] = []
    for target in raw_targets:
        if _is_soft_or_generic_skill_name(target):
            rejected_targets.append(target)
            continue
        if _is_infrastructure_skill_without_evidence(target, full_text):
            rejected_targets.append(target)
            infra_without_evidence.append(target)
            continue
        if not _is_concrete_coding_target_name(target, full_text, data_role=data_role):
            rejected_targets.append(target)
            continue
        if _skill_match_key(target) not in {_skill_match_key(item) for item in accepted_targets}:
            accepted_targets.append(_canonical_skill_name(target))

    if rejected_targets:
        warnings.append({'code': 'rejected_coding_targets', 'targets': rejected_targets})
    if infra_without_evidence:
        warnings.append({'code': 'infrastructure_without_jd_evidence', 'targets': infra_without_evidence})

    if not coding_required:
        if raw_targets or accepted_targets:
            warnings.append({'code': 'non_technical_coding_removed', 'targets': raw_targets or accepted_targets})
        accepted_targets = []
        repaired['coding_required'] = False
        repaired['coding_skill_targets'] = []
        repaired['coding_primary_skill'] = ''
        repaired['coding_questions_to_ask'] = 0
        _clear_runtime_section_coding(repaired)
    else:
        if data_role:
            data_targets = _data_coding_targets(title_text, jd_text)
            accepted_targets = _merge_skill_names(accepted_targets, data_targets)
        if not accepted_targets:
            accepted_targets = _best_coding_targets_from_payload(repaired, title_text, jd_text, data_role=data_role)
        repaired['coding_required'] = bool(accepted_targets)
        repaired['coding_skill_targets'] = accepted_targets
        repaired['coding_primary_skill'] = accepted_targets[0] if accepted_targets else ''
        repaired['coding_questions_to_ask'] = 3 if accepted_targets else 0
        if accepted_targets and _skill_keys(raw_targets) != _skill_keys(accepted_targets):
            warnings.append({'code': 'repaired_coding_targets', 'from': raw_targets, 'to': accepted_targets})
        for target in accepted_targets:
            _ensure_skill_payload_in_group(repaired, 'sub_skills', _skill_payload(target, _category_for_repaired_skill(target), 0.88, 'JD-supported coding target.'))
        _repair_runtime_sections_for_coding(repaired, accepted_targets)

    if repaired_primary:
        runtime_sub_names = accepted_targets or [
            _payload_skill_name(item)
            for item in repaired.get('sub_skills') or []
            if isinstance(item, dict) and _skill_match_key(_payload_skill_name(item)) != _skill_match_key(repaired_primary)
        ]
        _replace_runtime_sections_for_primary(repaired, repaired_primary, runtime_sub_names[:3])

    if not _payload_skill_name(repaired.get('primary_skill')):
        repaired.setdefault('_blueprint_quality_issue', 'primary_skill_missing')
    elif unsupported_primary and not repaired_primary:
        repaired.setdefault('_blueprint_quality_issue', 'unsupported_primary_skill')

    if warnings:
        repaired['_blueprint_quality_warnings'] = _dedupe_quality_warnings(warnings)
    return repaired


def _payload_skill_name(value: Any) -> str:
    if isinstance(value, dict):
        return _clean_string(value.get('name') or value.get('skill') or value.get('skill_name'))
    return _clean_string(value)


def _raw_coding_skill_target_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    items = payload.get('coding_skill_targets')
    if not isinstance(items, list):
        return names
    for item in items:
        name = _payload_skill_name(item)
        if name and _skill_match_key(name) not in {_skill_match_key(existing) for existing in names}:
            names.append(name)
    return names


def _skill_payload(name: str, category: str, confidence: float, reason: str) -> dict[str, Any]:
    return {
        'name': _canonical_skill_name(name),
        'category': category,
        'confidence': confidence,
        'reason': reason,
    }


def _category_for_repaired_skill(name: str) -> str:
    key = _skill_match_key(name)
    categories = {
        'sql': 'Database Query Language',
        'etl-elt': 'Data Engineering',
        'data-pipeline': 'Data Engineering',
        'data-pipelines': 'Data Engineering',
        'data-modeling': 'Data Architecture',
        'data-quality-validation': 'Data Quality',
        'data-warehousing': 'Data Warehousing',
        'data-engineering': 'Data Engineering',
        'data-architecture': 'Data Architecture',
        'core-java': 'Programming Language',
        'collection-framework': 'Java Framework',
        'collections-framework': 'Java Framework',
        'concurrency': 'Java Concept',
        'java-concurrency-and-collection': 'Java API',
        'java-concurrency-and-collections': 'Java API',
        'multithreading': 'Java Concept',
        'multithreading-and-concurrency': 'Java Concept',
        'apex': 'Salesforce Development',
        'lwc': 'Salesforce Development',
        'salesforce': 'CRM Platform',
    }
    return categories.get(key, 'Technical Skill')


def _ensure_skill_payload_in_group(payload: dict[str, Any], group_key: str, item: dict[str, Any]) -> None:
    group = payload.get(group_key)
    if not isinstance(group, list):
        group = []
    item_key = _skill_match_key(_payload_skill_name(item))
    if item_key and not any(_skill_match_key(_payload_skill_name(existing)) == item_key for existing in group if isinstance(existing, dict)):
        group.append(item)
    payload[group_key] = group


def _ensure_data_role_skills(payload: dict[str, Any], title_text: str, jd_text: str) -> None:
    primary_name = _payload_skill_name(payload.get('primary_skill'))
    if not primary_name:
        payload['primary_skill'] = _skill_payload(_best_data_primary(title_text, jd_text), 'Data Engineering', 0.9, 'Repaired from data-role evidence.')
    for name in _data_coding_targets(title_text, jd_text):
        _ensure_skill_payload_in_group(payload, 'sub_skills', _skill_payload(name, _category_for_repaired_skill(name), 0.86, 'Supported by data-role JD evidence.'))


def _clear_runtime_section_coding(payload: dict[str, Any]) -> None:
    for key in ['runtime_sections', 'interview_sections']:
        sections = payload.get(key)
        if not isinstance(sections, list):
            continue
        cleaned = []
        for section in sections:
            if isinstance(section, dict):
                section = {**section, 'coding_required': False, 'coding_questions_to_ask': 0}
            cleaned.append(section)
        payload[key] = cleaned


def _repair_runtime_sections_for_coding(payload: dict[str, Any], target_names: list[str]) -> None:
    target_keys = {_skill_match_key(name) for name in target_names}
    for key in ['runtime_sections', 'interview_sections']:
        sections = payload.get(key)
        if not isinstance(sections, list):
            continue
        repaired_sections = []
        for section in sections:
            if not isinstance(section, dict):
                repaired_sections.append(section)
                continue
            section_key = _skill_match_key(_payload_skill_name(section))
            is_target = section_key in target_keys
            repaired_sections.append({
                **section,
                'coding_required': is_target,
                'coding_questions_to_ask': 3 if is_target else 0,
            })
        payload[key] = repaired_sections


def _replace_runtime_sections_for_primary(payload: dict[str, Any], primary_name: str, sub_skill_names: list[str]) -> None:
    sections = [{
        'name': _canonical_skill_name(primary_name),
        'skill': _canonical_skill_name(primary_name),
        'category': _category_for_repaired_skill(primary_name),
        'skill_role': JobInterviewSkill.SkillRole.PRIMARY,
        'role': JobInterviewSkill.SkillRole.PRIMARY,
        'target_questions': _default_questions_to_ask(JobInterviewSkill.SkillRole.PRIMARY),
        'questions_to_ask': _default_questions_to_ask(JobInterviewSkill.SkillRole.PRIMARY),
        'coding_required': _skill_match_key(primary_name) in {_skill_match_key(name) for name in sub_skill_names},
        'coding_questions_to_ask': 3 if _skill_match_key(primary_name) in {_skill_match_key(name) for name in sub_skill_names} else 0,
        'selection_basis': 'blueprint_quality_repair',
        'reason': 'Repaired to strongest JD-supported primary skill.',
        'confidence': 0.92,
    }]
    seen = {_skill_match_key(primary_name)}
    for name in sub_skill_names:
        key = _skill_match_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        sections.append({
            'name': _canonical_skill_name(name),
            'skill': _canonical_skill_name(name),
            'category': _category_for_repaired_skill(name),
            'skill_role': JobInterviewSkill.SkillRole.SUB_SKILL,
            'role': JobInterviewSkill.SkillRole.SUB_SKILL,
            'target_questions': _default_questions_to_ask(JobInterviewSkill.SkillRole.SUB_SKILL),
            'questions_to_ask': _default_questions_to_ask(JobInterviewSkill.SkillRole.SUB_SKILL),
            'coding_required': True,
            'coding_questions_to_ask': 3,
            'selection_basis': 'blueprint_quality_repair',
            'reason': 'JD-supported coding target.',
            'confidence': 0.88,
        })
        if len(sections) >= 4:
            break
    payload['runtime_sections'] = sections
    payload['interview_sections'] = sections


def _dedupe_quality_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for warning in warnings:
        code = _clean_string(warning.get('code'))
        if not code:
            continue
        marker = json.dumps(warning, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(warning)
    return deduped


def _is_data_role_text(text: str) -> bool:
    return any(_term_matches(text, term) for term in DATA_ROLE_EVIDENCE_TERMS)


def _is_java_role_text(text: str) -> bool:
    return any(_term_matches(text, term) for term in ['core java', 'java', 'jvm'])


def _best_data_primary(title_text: str, jd_text: str) -> str:
    combined = _normalized_search_text(f'{title_text} {jd_text}')
    for name, _, terms in DATA_PRIMARY_RULES:
        if any(_term_matches(title_text, term) for term in terms):
            return name
    for name, _, terms in DATA_PRIMARY_RULES:
        if any(_term_matches(combined, term) for term in terms):
            return name
    return 'Data Engineering'


def _data_coding_targets(title_text: str, jd_text: str) -> list[str]:
    combined = _normalized_search_text(f'{title_text} {jd_text}')
    targets: list[str] = []
    for name, _, terms in DATA_CODING_TARGET_RULES:
        if any(_term_matches(combined, term) for term in terms):
            targets.append(name)
    return targets


def _primary_skill_supported(name: str, title_text: str, jd_text: str, *, data_role: bool = False) -> bool:
    combined = _normalized_search_text(f'{title_text} {jd_text}')
    if _is_infrastructure_skill_without_evidence(name, combined):
        return False
    if data_role and _skill_match_key(name) in {'data-engineering', 'data-architecture', 'data-warehousing'}:
        return True
    candidates = _skill_evidence_terms(name)
    title_hit = any(_term_matches(title_text, term) for term in candidates)
    jd_hits = sum(1 for term in candidates if _term_matches(jd_text, term))
    if title_hit or jd_hits >= 1:
        return True
    token_hits = [
        token for token in _skill_match_key(name).split('-')
        if len(token) > 2 and _term_matches(jd_text, token)
    ]
    return len(token_hits) >= 2


def _skill_evidence_terms(name: str) -> list[str]:
    canonical = _canonical_skill_name(name)
    key = _skill_match_key(canonical)
    terms = {canonical, canonical.replace('/', ' '), key.replace('-', ' ')}
    if key == 'etl-elt':
        terms.update({'etl', 'elt', 'extract transform load'})
    if key == 'sql':
        terms.update({'sql', 'database query', 'data warehouse', 'data warehousing'})
    if key == 'data-quality-validation':
        terms.update({'data quality', 'data validation', 'validation'})
    if key in {'data-analysi', 'data-analysis'}:
        terms.update({'data analysis', 'analyze data', 'analytics'})
    if key in JAVA_CODING_TARGET_KEYS:
        terms.update({
            'collection framework',
            'collections framework',
            'collections',
            'concurrency',
            'java collections',
            'java concurrency',
            'multithreading',
        })
    if key in {'communication', 'communication-skill', 'communication-skills'}:
        terms.update({'communicate', 'communication', 'client communication'})
    if key == 'candidate-sourcing':
        terms.update({'source candidates', 'sourcing candidates', 'candidate sourcing'})
    if key == 'talent-acquisition':
        terms.update({'talent acquisition', 'recruitment', 'hiring'})
    return [term for term in terms if term]


def _is_soft_or_generic_skill_name(name: str) -> bool:
    key = _skill_match_key(name)
    return key in SOFT_CODING_TARGET_KEYS or key in PROCESS_SKILL_KEYS


def _is_infrastructure_skill_without_evidence(name: str, text: str) -> bool:
    key = _skill_match_key(name)
    terms = INFRASTRUCTURE_SKILL_EVIDENCE_TERMS.get(key)
    if not terms:
        return False
    return not any(_term_matches(text, term) for term in terms)


def _is_concrete_coding_target_name(name: str, text: str, *, data_role: bool = False) -> bool:
    key = _skill_match_key(name)
    if _is_soft_or_generic_skill_name(name):
        return False
    if _is_infrastructure_skill_without_evidence(name, text):
        return False
    if data_role and key in {'sql', 'etl-elt', 'data-pipeline', 'data-pipelines', 'data-modeling', 'data-quality-validation', 'data-warehousing'}:
        return True
    if key in JAVA_CODING_TARGET_KEYS and _is_java_role_text(text):
        return True
    if key in {'apex', 'core-java', 'java', 'javascript', 'lwc', 'python', 'react', 'rest-api', 'salesforce', 'soql', 'sql'}:
        return True
    return _primary_skill_supported(name, _normalized_search_text(''), text, data_role=data_role)


def _best_supported_primary_from_payload(payload: dict[str, Any], title_text: str, jd_text: str, *, data_role: bool = False) -> str:
    candidates: list[str] = []
    for group_key in ['primary_skill_candidates', 'sub_skills', 'optional_skills', 'runtime_sections', 'interview_sections']:
        group = payload.get(group_key)
        if isinstance(group, list):
            candidates.extend(_payload_skill_name(item) for item in group if isinstance(item, dict))
    for candidate in candidates:
        if _primary_skill_supported(candidate, title_text, jd_text, data_role=data_role):
            return _canonical_skill_name(candidate)
    return ''


def _best_coding_targets_from_payload(payload: dict[str, Any], title_text: str, jd_text: str, *, data_role: bool = False) -> list[str]:
    text = _normalized_search_text(f'{title_text} {jd_text}')
    primary_name = _payload_skill_name(payload.get('primary_skill'))
    if primary_name and _is_concrete_coding_target_name(primary_name, text, data_role=data_role):
        return [_canonical_skill_name(primary_name)]
    for group_key in ['primary_skill_candidates', 'sub_skills']:
        group = payload.get(group_key)
        if not isinstance(group, list):
            continue
        for item in group:
            name = _payload_skill_name(item)
            if name and _is_concrete_coding_target_name(name, text, data_role=data_role):
                return [_canonical_skill_name(name)]
    return []


def _merge_skill_names(existing: list[str], additions: list[str]) -> list[str]:
    merged = list(existing)
    keys = {_skill_match_key(name) for name in merged}
    for name in additions:
        key = _skill_match_key(name)
        if key and key not in keys:
            merged.append(_canonical_skill_name(name))
            keys.add(key)
    return merged


def _skill_keys(names: list[str]) -> set[str]:
    return {_skill_match_key(name) for name in names if _skill_match_key(name)}


def _is_hands_on_technical_text(text: str) -> bool:
    hands_on_terms = [
        'api',
        'build',
        'code',
        'coding',
        'data pipeline',
        'data pipelines',
        'develop',
        'developer',
        'engineer',
        'etl',
        'implementation',
        'programming',
        'sql',
    ]
    return _is_technical_role_text(text) and any(_term_matches(text, term) for term in hands_on_terms)


def _jd_explicitly_requires_coding(text: str) -> bool:
    return any(_term_matches(text, term) for term in ['coding test', 'coding exercise', 'programming', 'write code', 'hands on coding'])


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


def _has_authoritative_runtime_sections(payload: dict[str, Any]) -> bool:
    return bool(_runtime_sections_from_payload(payload))


def _runtime_sections_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sections = payload.get('runtime_sections')
    if not isinstance(sections, list):
        sections = payload.get('interview_sections')
    if not isinstance(sections, list):
        return []
    cleaned: list[dict[str, Any]] = []
    primary_seen = False
    sub_count = 0
    for item in sections:
        if not isinstance(item, dict):
            continue
        name = _clean_string(item.get('name') or item.get('skill') or item.get('skill_name'))
        if not name:
            continue
        role = _clean_string(item.get('skill_role') or item.get('role') or item.get('section_role')).lower()
        if role not in {JobInterviewSkill.SkillRole.PRIMARY, JobInterviewSkill.SkillRole.SUB_SKILL}:
            role = JobInterviewSkill.SkillRole.PRIMARY if not primary_seen else JobInterviewSkill.SkillRole.SUB_SKILL
        if role == JobInterviewSkill.SkillRole.PRIMARY:
            if primary_seen:
                continue
            primary_seen = True
        else:
            if sub_count >= 3:
                continue
            sub_count += 1
        cleaned.append({
            **item,
            'name': name,
            'skill': name,
            'skill_role': role,
            'role': role,
            'target_questions': _clamp_int(
                item.get('target_questions') or item.get('questions_to_ask'),
                _default_questions_to_ask(role),
                1,
                8,
            ),
            'questions_to_ask': _clamp_int(
                item.get('questions_to_ask') or item.get('target_questions'),
                _default_questions_to_ask(role),
                1,
                8,
            ),
            'coding_required': bool(_clean_bool_or_none(item.get('coding_required'))),
            'coding_questions_to_ask': _clamp_int(item.get('coding_questions_to_ask'), 0, 0, 3),
            'selection_basis': _clean_string(item.get('selection_basis'))[:500],
            'reason': _clean_string(item.get('reason'))[:500],
        })
    return cleaned if primary_seen else []


def _apply_runtime_section_selection(
    selected_skills: list[tuple[ExtractedSkill, Skill]],
    payload: dict[str, Any],
    job: Vacancies,
    experience_level: str,
) -> list[tuple[ExtractedSkill, Skill]]:
    sections = _runtime_sections_from_payload(payload)
    if not selected_skills or not sections:
        return selected_skills

    selected_by_key: dict[str, tuple[ExtractedSkill, Skill]] = {}
    for extracted, skill in selected_skills:
        keys = {
            _skill_match_key(extracted.name),
            _skill_match_key(extracted.original_name),
            _skill_match_key(skill.name),
            _skill_match_key(skill.key.replace('-', ' ')),
        }
        keys.update(_skill_match_key(alias) for alias in _json_list(skill.aliases))
        for key in keys:
            if key:
                selected_by_key.setdefault(key, (extracted, skill))

    section_by_skill_id: dict[int, dict[str, Any]] = {}
    for index, section in enumerate(sections, start=1):
        key = _skill_match_key(section['name'])
        matched = selected_by_key.get(key)
        if not matched:
            continue
        _, skill = matched
        section_by_skill_id[skill.id] = {**section, 'priority': index}

    if not any(section['skill_role'] == JobInterviewSkill.SkillRole.PRIMARY for section in section_by_skill_id.values()):
        return selected_skills
    primary_skill_id = next(
        (skill_id for skill_id, section in section_by_skill_id.items() if section['skill_role'] == JobInterviewSkill.SkillRole.PRIMARY),
        None,
    )
    primary_match = next(((extracted, skill) for extracted, skill in selected_skills if skill.id == primary_skill_id), None)
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '', job.experience_required or '']))
    if primary_match and _is_technical_role_text(role_text) and _is_low_priority_technical_primary(primary_match[0], primary_match[1]):
        logger.warning(
            'Rejected impossible runtime primary skill for technical role job_id=%s skill=%s',
            job.id,
            primary_match[1].name,
        )
        return _ensure_primary_skill_selection(selected_skills, job, experience_level)

    coding_required = _clean_bool_or_none(payload.get('coding_required'))
    coding_questions_to_ask = _clamp_int(payload.get('coding_questions_to_ask'), 0, 0, 3)
    if coding_required and coding_questions_to_ask <= 0:
        coding_questions_to_ask = 3
    coding_target_keys = {_skill_match_key(name) for name in _coding_skill_target_names_from_payload(payload)}

    rebalanced: list[tuple[ExtractedSkill, Skill]] = []
    for extracted, skill in selected_skills:
        section = section_by_skill_id.get(skill.id)
        if section:
            is_coding_target = _skill_match_key(skill.name) in coding_target_keys or _skill_match_key(extracted.name) in coding_target_keys
            rebalanced.append((
                _with_runtime_section(
                    extracted,
                    section,
                    experience_level,
                    coding_required=bool(coding_required and is_coding_target),
                    coding_questions_to_ask=coding_questions_to_ask if coding_required and is_coding_target else 0,
                ),
                skill,
            ))
            continue
        if coding_required and (_skill_match_key(skill.name) in coding_target_keys or _skill_match_key(extracted.name) in coding_target_keys):
            rebalanced.append((
                ExtractedSkill(
                    name=extracted.name,
                    category=extracted.category,
                    skill_role=JobInterviewSkill.SkillRole.SUB_SKILL,
                    priority=max(2, extracted.priority),
                    questions_to_ask=_default_questions_to_ask(JobInterviewSkill.SkillRole.SUB_SKILL),
                    coding_required=True,
                    coding_questions_to_ask=coding_questions_to_ask,
                    difficulty_mix=_difficulty_mix_for(experience_level, JobInterviewSkill.SkillRole.SUB_SKILL),
                    coding_difficulty_mix=extracted.coding_difficulty_mix,
                    confidence=extracted.confidence,
                    reason=extracted.reason or 'Included as a blueprint coding target.',
                    original_name=extracted.original_name,
                    interview_weight='normal',
                    eligible_for_random_sub_skill=True,
                ),
                skill,
            ))
            continue
        rebalanced.append((
            ExtractedSkill(
                name=extracted.name,
                category=extracted.category,
                skill_role=JobInterviewSkill.SkillRole.OPTIONAL,
                priority=max(50, extracted.priority),
                questions_to_ask=_default_questions_to_ask(JobInterviewSkill.SkillRole.OPTIONAL),
                coding_required=False,
                coding_questions_to_ask=0,
                difficulty_mix=_difficulty_mix_for(experience_level, JobInterviewSkill.SkillRole.OPTIONAL),
                coding_difficulty_mix=extracted.coding_difficulty_mix,
                confidence=extracted.confidence,
                reason=extracted.reason or 'Excluded from authoritative runtime_sections.',
                original_name=extracted.original_name,
                interview_weight='low',
                eligible_for_random_sub_skill=False,
            ),
            skill,
        ))
    return rebalanced


def _with_runtime_section(
    skill: ExtractedSkill,
    section: dict[str, Any],
    experience_level: str,
    *,
    coding_required: bool | None,
    coding_questions_to_ask: int,
) -> ExtractedSkill:
    skill_role = section['skill_role']
    return ExtractedSkill(
        name=skill.name,
        category=skill.category or _clean_string(section.get('category'))[:80],
        skill_role=skill_role,
        priority=_clamp_int(section.get('priority'), skill.priority, 1, 99),
        questions_to_ask=_clamp_int(section.get('target_questions'), _default_questions_to_ask(skill_role), 1, 8),
        coding_required=coding_required,
        coding_questions_to_ask=coding_questions_to_ask,
        difficulty_mix=_difficulty_mix_for(experience_level, skill_role),
        coding_difficulty_mix=skill.coding_difficulty_mix,
        confidence=skill.confidence,
        reason=_clean_string(section.get('reason'))[:500] or skill.reason,
        original_name=skill.original_name,
        interview_weight='normal',
        eligible_for_random_sub_skill=True,
    )


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
        coding_required=skill.coding_required,
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
    for item in _coding_skill_target_payloads(payload):
        raw_entries.append((JobInterviewSkill.SkillRole.SUB_SKILL, item))
    for item in payload.get('primary_skill_candidates') or []:
        if isinstance(item, dict):
            raw_entries.append((JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE, item))
    for item in payload.get('sub_skills') or []:
        if isinstance(item, dict):
            raw_entries.append((JobInterviewSkill.SkillRole.SUB_SKILL, item))
    for item in payload.get('optional_skills') or []:
        if isinstance(item, dict):
            raw_entries.append((JobInterviewSkill.SkillRole.OPTIONAL, item))
    for item in _runtime_sections_from_payload(payload):
        raw_entries.append((item['skill_role'], item))
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
            if skill.coding_required or skill.coding_questions_to_ask > 0:
                normalized_by_key[key] = ExtractedSkill(
                    name=existing.name,
                    category=existing.category or skill.category,
                    skill_role=existing.skill_role,
                    priority=min(existing.priority, skill.priority),
                    questions_to_ask=existing.questions_to_ask,
                    coding_required=True,
                    coding_questions_to_ask=max(existing.coding_questions_to_ask, skill.coding_questions_to_ask, 3),
                    difficulty_mix=existing.difficulty_mix,
                    coding_difficulty_mix=skill.coding_difficulty_mix or existing.coding_difficulty_mix,
                    confidence=max(existing.confidence or 0, skill.confidence or 0),
                    reason=existing.reason or skill.reason,
                    original_name=existing.original_name or skill.original_name,
                    interview_weight=existing.interview_weight,
                    eligible_for_random_sub_skill=existing.eligible_for_random_sub_skill,
                )
            continue
        if existing:
            skill = ExtractedSkill(
                name=skill.name,
                category=skill.category or existing.category,
                skill_role=skill.skill_role,
                priority=min(existing.priority, skill.priority),
                questions_to_ask=_default_questions_to_ask(skill.skill_role),
                coding_required=skill.coding_required if skill.coding_required is not None else existing.coding_required,
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


def _ensure_primary_skill_selection(
    selected_skills: list[tuple[ExtractedSkill, Skill]],
    job: Vacancies,
    experience_level: str,
) -> list[tuple[ExtractedSkill, Skill]]:
    if not selected_skills:
        return selected_skills

    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '', job.experience_required or '']))
    is_technical_role = _is_technical_role_text(role_text)
    chosen_skill_id: int | None = None

    if is_technical_role:
        technical_candidates = [
            (_technical_primary_score(extracted, skill, job), extracted.priority, skill.id)
            for extracted, skill in selected_skills
            if _is_concrete_technical_primary_candidate(extracted, skill, job)
        ]
        if technical_candidates:
            chosen_skill_id = max(technical_candidates, key=lambda item: (item[0], -item[1]))[2]

    if chosen_skill_id is None:
        current_primary = next((skill.id for extracted, skill in selected_skills if extracted.skill_role == JobInterviewSkill.SkillRole.PRIMARY), None)
        chosen_skill_id = current_primary or min(selected_skills, key=lambda item: item[0].priority)[1].id

    rebalanced: list[tuple[ExtractedSkill, Skill]] = []
    primary_priority = min(extracted.priority for extracted, _ in selected_skills)
    for extracted, skill in selected_skills:
        if skill.id == chosen_skill_id:
            rebalanced.append((_with_skill_role(extracted, JobInterviewSkill.SkillRole.PRIMARY, experience_level, primary_priority), skill))
            continue
        if extracted.skill_role == JobInterviewSkill.SkillRole.PRIMARY:
            demoted_role = _demoted_primary_role(extracted, skill, job, is_technical_role)
            rebalanced.append((_with_skill_role(extracted, demoted_role, experience_level), skill))
            continue
        rebalanced.append((extracted, skill))
    return rebalanced


def _primary_selection_needs_repair(selected_skills: list[tuple[ExtractedSkill, Skill]], job: Vacancies) -> bool:
    if not selected_skills:
        return False
    primary = next(((extracted, skill) for extracted, skill in selected_skills if extracted.skill_role == JobInterviewSkill.SkillRole.PRIMARY), None)
    if not primary:
        return True
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '', job.experience_required or '']))
    return _is_technical_role_text(role_text) and _is_low_priority_technical_primary(primary[0], primary[1])


def _with_skill_role(
    skill: ExtractedSkill,
    skill_role: str,
    experience_level: str,
    priority: int | None = None,
) -> ExtractedSkill:
    return ExtractedSkill(
        name=skill.name,
        category=skill.category,
        skill_role=skill_role,
        priority=skill.priority if priority is None else priority,
        questions_to_ask=_default_questions_to_ask(skill_role),
        coding_required=skill.coding_required,
        coding_questions_to_ask=skill.coding_questions_to_ask,
        difficulty_mix=_difficulty_mix_for(experience_level, skill_role),
        coding_difficulty_mix=skill.coding_difficulty_mix,
        confidence=skill.confidence,
        reason=skill.reason,
        original_name=skill.original_name,
        interview_weight=skill.interview_weight,
        eligible_for_random_sub_skill=skill.eligible_for_random_sub_skill,
    )


def _demoted_primary_role(extracted: ExtractedSkill, skill: Skill, job: Vacancies, is_technical_role: bool) -> str:
    if not is_technical_role:
        return JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE
    if _is_low_priority_technical_primary(extracted, skill):
        return JobInterviewSkill.SkillRole.OPTIONAL if _is_soft_or_process_skill(extracted, skill) else JobInterviewSkill.SkillRole.SUB_SKILL
    return JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE


def _is_concrete_technical_primary_candidate(extracted: ExtractedSkill, skill: Skill, job: Vacancies) -> bool:
    return _technical_primary_score(extracted, skill, job) > 0


def _technical_primary_score(extracted: ExtractedSkill, skill: Skill, job: Vacancies) -> int:
    if _is_low_priority_technical_primary(extracted, skill):
        return 0

    categories = _category_keys(extracted.category, skill.category)
    key = _skill_match_key(skill.name)
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '', job.experience_required or '']))
    score = 0

    if _is_cloud_or_devops_role(role_text) and categories & CLOUD_PRIMARY_CATEGORIES:
        score = max(score, 1000)
    if _is_qa_automation_role(role_text) and categories & AUTOMATION_PRIMARY_CATEGORIES:
        score = max(score, 1000)
    if _is_salesforce_role(role_text) and (categories & CRM_PRIMARY_CATEGORIES or key in {'apex', 'lwc', 'salesforce', 'soql'}):
        score = max(score, 1000)
    if categories & HIGH_PRIORITY_TECHNICAL_CATEGORIES:
        score = max(score, 900)
    if _is_technical_skill(skill):
        score = max(score, 800)
    if categories & MEDIUM_PRIORITY_TECHNICAL_CATEGORIES:
        score = max(score, 500)

    if score <= 0:
        return 0

    title_text = _normalized_search_text(job.role or '')
    candidates = [skill.name, skill.key.replace('-', ' '), extracted.original_name, extracted.name]
    candidates.extend(_json_list(skill.aliases))
    if any(_term_matches(title_text, candidate) for candidate in candidates):
        score += 250
    elif any(_term_matches(role_text, candidate) for candidate in candidates):
        score += 80
    score += max(0, 50 - int(extracted.priority or 0))
    score += int((extracted.confidence or 0) * 20)
    return score


def _category_keys(*values: str) -> set[str]:
    keys: set[str] = set()
    for value in values:
        normalized = normalize_skill_key(value or '').replace('-', '_')
        if normalized:
            keys.add(normalized)
    return keys


def _is_low_priority_technical_primary(extracted: ExtractedSkill, skill: Skill) -> bool:
    key = _skill_match_key(skill.name)
    categories = _category_keys(extracted.category, skill.category)
    return (
        key in PROCESS_SKILL_KEYS
        or key in {'debugging', 'git', 'problem-solving', 'version-control'}
        or bool(categories & LOW_PRIORITY_TECHNICAL_PRIMARY_CATEGORIES)
    )


def _is_soft_or_process_skill(extracted: ExtractedSkill, skill: Skill) -> bool:
    key = _skill_match_key(skill.name)
    categories = _category_keys(extracted.category, skill.category)
    return key in PROCESS_SKILL_KEYS or bool(categories & {
        'agile',
        'communication',
        'documentation',
        'industry_trends',
        'leadership',
        'process',
        'soft_skill',
        'soft_skills',
        'teamwork',
    })


def _is_cloud_or_devops_role(role_text: str) -> bool:
    return any(_term_matches(role_text, term) for term in ['cloud', 'cloud engineer', 'devops', 'devops engineer', 'site reliability engineer', 'sre'])


def _is_qa_automation_role(role_text: str) -> bool:
    return any(_term_matches(role_text, term) for term in ['qa automation', 'automation engineer', 'sdet', 'test automation'])


def _is_salesforce_role(role_text: str) -> bool:
    return any(_term_matches(role_text, term) for term in ['salesforce', 'apex', 'lwc'])


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
    runtime_section_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'name': {'type': 'string'},
            'skill': {'type': 'string'},
            'category': {'type': 'string'},
            'skill_role': {'type': 'string', 'enum': [JobInterviewSkill.SkillRole.PRIMARY, JobInterviewSkill.SkillRole.SUB_SKILL]},
            'role': {'type': 'string', 'enum': [JobInterviewSkill.SkillRole.PRIMARY, JobInterviewSkill.SkillRole.SUB_SKILL]},
            'target_questions': {'type': 'integer', 'minimum': 1, 'maximum': 8},
            'questions_to_ask': {'type': 'integer', 'minimum': 1, 'maximum': 8},
            'coding_required': {'type': 'boolean'},
            'coding_questions_to_ask': {'type': 'integer', 'minimum': 0, 'maximum': 3},
            'selection_basis': {'type': 'string'},
            'reason': {'type': 'string'},
            'confidence': {'type': 'number'},
        },
        'required': ['name', 'skill', 'category', 'skill_role', 'role', 'target_questions', 'questions_to_ask', 'coding_required', 'coding_questions_to_ask', 'selection_basis', 'reason', 'confidence'],
    }
    excluded_skill_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'name': {'type': 'string'},
            'category': {'type': 'string'},
            'reason': {'type': 'string'},
        },
        'required': ['name', 'category', 'reason'],
    }
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'role_title': {'type': 'string'},
            'role_domain': {'type': 'string'},
            'role_subdomain': {'type': 'string'},
            'role_family': {'type': 'string', 'enum': ['technical', 'non_technical', 'hybrid']},
            'technical_interview': {'type': 'boolean'},
            'experience_level': {'type': 'string'},
            'primary_skill': skill_schema,
            'primary_skill_candidates': {'type': 'array', 'items': candidate_schema, 'maxItems': 8},
            'sub_skills': {'type': 'array', 'items': candidate_schema, 'maxItems': 20},
            'optional_skills': {'type': 'array', 'items': candidate_schema, 'maxItems': 12},
            'runtime_sections': {'type': 'array', 'items': runtime_section_schema, 'minItems': 1, 'maxItems': 4},
            'interview_sections': {'type': 'array', 'items': runtime_section_schema, 'minItems': 1, 'maxItems': 4},
            'coding_required': {'type': 'boolean'},
            'coding_skill_targets': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 8},
            'coding_primary_skill': {'type': 'string'},
            'coding_questions_to_ask': {'type': 'integer', 'minimum': 0, 'maximum': 3},
            'excluded_skills': {'type': 'array', 'items': excluded_skill_schema, 'maxItems': 20},
        },
        'required': [
            'role_title',
            'role_domain',
            'role_subdomain',
            'role_family',
            'technical_interview',
            'experience_level',
            'primary_skill',
            'primary_skill_candidates',
            'sub_skills',
            'optional_skills',
            'runtime_sections',
            'interview_sections',
            'coding_required',
            'coding_skill_targets',
            'coding_primary_skill',
            'coding_questions_to_ask',
            'excluded_skills',
        ],
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


def _role_family_for(job: Vacancies, extracted_payload: dict[str, Any]) -> str:
    raw = _clean_string(extracted_payload.get('role_family')).lower()
    if raw in {'technical', 'non_technical', 'hybrid'}:
        return raw
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '', job.experience_required or '']))
    return 'technical' if _is_technical_role_text(role_text) else 'non_technical'


def _technical_interview_for(job: Vacancies, extracted_payload: dict[str, Any], role_family: str) -> bool:
    explicit = _clean_bool_or_none(extracted_payload.get('technical_interview'))
    if explicit is not None:
        return explicit
    return role_family in {'technical', 'hybrid'} or _is_technical_role_text(_normalized_search_text(' '.join([job.role or '', job.description or ''])))


def _coding_skill_target_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get('coding_skill_targets')
    if not isinstance(items, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            name = _clean_string(item.get('name') or item.get('skill') or item.get('skill_name'))
            category = _clean_string(item.get('category'))[:80]
            confidence = item.get('confidence')
            reason = _clean_string(item.get('reason'))[:500]
        else:
            name = _clean_string(item)
            category = ''
            confidence = 0.8
            reason = 'Selected by blueprint as a coding target.'
        name = _canonical_skill_name(name)
        if not name:
            continue
        cleaned.append({
            'name': name[:120],
            'category': category,
            'priority': index + 1,
            'questions_to_ask': _default_questions_to_ask(JobInterviewSkill.SkillRole.SUB_SKILL),
            'coding_required': True,
            'coding_questions_to_ask': 3,
            'confidence': confidence,
            'reason': reason,
        })
    return cleaned


def _coding_skill_target_names_from_payload(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in _coding_skill_target_payloads(payload):
        name = _clean_string(item.get('name'))
        if name and name not in names:
            names.append(name)
    return names


def _coding_skill_target_details(
    selected_by_role: dict[str, list[dict[str, Any]]],
    target_names: list[str],
    coding_required: bool,
) -> list[dict[str, Any]]:
    if not coding_required:
        return []
    target_keys = {_skill_match_key(name) for name in target_names if _skill_match_key(name)}
    all_skills = [
        *(selected_by_role.get(JobInterviewSkill.SkillRole.PRIMARY) or []),
        *(selected_by_role.get(JobInterviewSkill.SkillRole.SUB_SKILL) or []),
        *(selected_by_role.get(JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE) or []),
    ]
    details: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in all_skills:
        key = _skill_match_key(item.get('name') or item.get('skill_key') or '')
        if target_keys and key not in target_keys:
            continue
        if not target_keys and not item.get('coding_questions_to_ask') and item.get('skill_role') != JobInterviewSkill.SkillRole.PRIMARY:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        details.append(item)
    if not details and all_skills:
        details.append(all_skills[0])
    return details


def _build_blueprint_plan(
    extracted_payload: dict[str, Any],
    job: Vacancies,
    experience_level: str,
    selected_by_role: dict[str, list[dict[str, Any]]],
    unmapped_skills: list[dict[str, Any]],
    rejected_skills: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = (selected_by_role.get(JobInterviewSkill.SkillRole.PRIMARY) or [{}])[0]
    primary_coding_questions = _clamp_int(primary.get('coding_questions_to_ask'), 0, 0, 3) if primary else 0
    role_family = _role_family_for(job, extracted_payload)
    technical_interview = _technical_interview_for(job, extracted_payload, role_family)
    coding_required = _clean_bool_or_none(extracted_payload.get('coding_required'))
    if coding_required is None:
        coding_required = bool(primary_coding_questions > 0)
    coding_questions_to_ask = _clamp_int(extracted_payload.get('coding_questions_to_ask'), primary_coding_questions, 0, 3)
    if coding_required and coding_questions_to_ask <= 0:
        coding_questions_to_ask = 3
    elif coding_required:
        coding_questions_to_ask = 3
    target_names = _coding_skill_target_names_from_payload(extracted_payload)
    target_details = _coding_skill_target_details(selected_by_role, target_names, bool(coding_required))
    if coding_required and not target_names:
        target_names = [item.get('name', '') for item in target_details if item.get('name')]
    runtime_sections = _build_runtime_sections(
        extracted_payload,
        selected_by_role,
        coding_required=bool(coding_required),
        coding_target_names=target_names,
        coding_questions_to_ask=coding_questions_to_ask if coding_required else 0,
    )
    return ensure_blueprint_plan_signature({
        'blueprint_version': 2,
        'role_title': _clean_string(extracted_payload.get('role_title'))[:255] or job.role,
        'role_domain': _clean_string(extracted_payload.get('role_domain'))[:120],
        'role_subdomain': _clean_string(extracted_payload.get('role_subdomain'))[:120],
        'role_family': role_family,
        'technical_interview': bool(technical_interview),
        'experience_level': experience_level,
        'primary_skill': primary,
        'primary_skill_candidates': selected_by_role.get(JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE, []),
        'sub_skills': selected_by_role.get(JobInterviewSkill.SkillRole.SUB_SKILL, []),
        'optional_skills': selected_by_role.get(JobInterviewSkill.SkillRole.OPTIONAL, []),
        'runtime_sections': runtime_sections,
        'interview_sections': runtime_sections,
        'coding_required': bool(coding_required),
        'coding_skill_targets': target_names if coding_required else [],
        'coding_skill_target_details': target_details if coding_required else [],
        'coding_primary_skill': _clean_string(extracted_payload.get('coding_primary_skill'))[:120] or (primary.get('name') if coding_required and primary else ''),
        'coding_questions_to_ask': coding_questions_to_ask if coding_required else 0,
        'excluded_skills': _excluded_skills_from_payload(extracted_payload),
        'unmapped_skills': unmapped_skills,
        'rejected_skills': rejected_skills,
        'quality_warnings': extracted_payload.get('_blueprint_quality_warnings', []),
        'quality_issue': _clean_string(extracted_payload.get('_blueprint_quality_issue')),
        'runtime_policy': {
            'selection_strategy': 'authoritative_runtime_sections',
            'runtime_sections_authoritative': bool(runtime_sections),
            'primary_questions_to_ask': max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_PRIMARY_QUESTIONS', 5))),
            'sub_skills_to_pick': len([section for section in runtime_sections if section.get('skill_role') == JobInterviewSkill.SkillRole.SUB_SKILL]) or max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_SUB_SKILLS_TO_PICK', 3))),
            'questions_per_sub_skill': max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_SUB_SKILL_QUESTIONS', 3))),
            'coding_questions_per_primary': coding_questions_to_ask if coding_required else 0,
            'prefer_mapped_skills': True,
            'prefer_skills_with_question_bank': False,
            'avoid_same_family_key_repeats': True,
        },
    })


def _build_runtime_sections(
    extracted_payload: dict[str, Any],
    selected_by_role: dict[str, list[dict[str, Any]]],
    *,
    coding_required: bool = False,
    coding_target_names: list[str] | None = None,
    coding_questions_to_ask: int = 0,
) -> list[dict[str, Any]]:
    payload_sections = _runtime_sections_from_payload(extracted_payload)
    metadata_by_key = {
        _skill_match_key(section.get('name', '')): section
        for section in payload_sections
        if _skill_match_key(section.get('name', ''))
    }
    mapped_sections: list[dict[str, Any]] = []
    primary = (selected_by_role.get(JobInterviewSkill.SkillRole.PRIMARY) or [])[:1]
    sub_skills = (selected_by_role.get(JobInterviewSkill.SkillRole.SUB_SKILL) or [])[:3]
    coding_target_keys = {_skill_match_key(name) for name in (coding_target_names or [])}
    for item in [*primary, *sub_skills]:
        key = _skill_match_key(item.get('original_name') or item.get('name') or item.get('skill_key') or '')
        metadata = metadata_by_key.get(key) or metadata_by_key.get(_skill_match_key(item.get('name', ''))) or {}
        role = item.get('skill_role') or metadata.get('skill_role') or JobInterviewSkill.SkillRole.SUB_SKILL
        section_coding_required = bool(coding_required and (key in coding_target_keys or _skill_match_key(item.get('name', '')) in coding_target_keys))
        target_questions = _clamp_int(
            metadata.get('target_questions') or metadata.get('questions_to_ask') or item.get('questions_to_ask'),
            _default_questions_to_ask(role),
            1,
            8,
        )
        mapped_sections.append({
            **item,
            'skill': item.get('name', ''),
            'skill_role': role,
            'role': role,
            'target_questions': target_questions,
            'questions_to_ask': target_questions,
            'coding_required': section_coding_required,
            'coding_questions_to_ask': coding_questions_to_ask if section_coding_required else 0,
            'selection_basis': _clean_string(metadata.get('selection_basis'))[:500] or 'mapped_runtime_section',
            'reason': _clean_string(metadata.get('reason'))[:500] or item.get('reason', ''),
        })
    return mapped_sections


def _excluded_skills_from_payload(extracted_payload: dict[str, Any]) -> list[dict[str, str]]:
    excluded = extracted_payload.get('excluded_skills')
    if not isinstance(excluded, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in excluded:
        if not isinstance(item, dict):
            continue
        name = _clean_string(item.get('name') or item.get('skill_name'))[:120]
        reason = _clean_string(item.get('reason'))[:500]
        if not name or not reason:
            continue
        cleaned.append({
            'name': name,
            'category': _clean_string(item.get('category'))[:80],
            'reason': reason,
        })
    return cleaned[:20]


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
        'coding_required': skill.coding_required,
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
    if key in {'kubernetes', 'microservices'}:
        return key
    if key in {'apis', 'restful-apis', 'rest-apis'}:
        return 'rest-api'
    if key.endswith('ies') and len(key) > 4:
        return f'{key[:-3]}y'
    if key.endswith('s') and not key.endswith(('ss', 'css', 'js', 'sis')) and len(key) > 3:
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
    return False


def _is_technical_role_text(normalized_role_text: str) -> bool:
    text = normalized_role_text if normalized_role_text.startswith(' ') else _normalized_search_text(normalized_role_text)
    if set(text.split()) & TECHNICAL_ROLE_TERMS:
        return True
    return any(_term_matches(text, phrase) for phrase in TECHNICAL_ROLE_PHRASES)


def _is_technical_skill(skill: Skill) -> bool:
    key = _skill_match_key(skill.name)
    category = (skill.category or '').lower()
    return key in {
        'angular',
        'apex',
        'core-java',
        'data-architecture',
        'data-engineering',
        'data-modeling',
        'data-pipeline',
        'data-quality-validation',
        'data-warehousing',
        'django',
        'etl-elt',
        'django-rest-framework',
        'flutter',
        'html-css',
        'javascript',
        'java',
        'laravel',
        'lwc',
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
        'salesforce',
        'soql',
        'spring',
        'spring-boot',
        'sql',
    } or any(term in category for term in ['backend', 'frontend', 'programming', 'framework', 'database', 'data engineering', 'data architecture', 'data warehousing', 'mobile', 'web services', 'salesforce', 'cloud', 'devops', 'automation'])


def _coding_questions_to_ask_for(job: Vacancies, extracted: ExtractedSkill, skill: Skill) -> int:
    if extracted.coding_required is False:
        return 0
    if extracted.coding_required is True:
        return _clamp_int(extracted.coding_questions_to_ask, 3, 1, 3)
    if extracted.skill_role != JobInterviewSkill.SkillRole.PRIMARY:
        return 0
    role_text = _normalized_search_text(' '.join([job.role or '', job.description or '', skill.name or '', skill.category or '']))
    if _is_technical_role_text(role_text) and _is_technical_skill(skill):
        return 3
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


def _clean_bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes'}:
            return True
        if normalized in {'false', '0', 'no'}:
            return False
    return None


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
