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
from smartInterviewApp.services.blueprint_plan_signature import blueprint_plan_signature, ensure_blueprint_plan_signature
from smartInterviewApp.services.cloud_tasks import CloudTasksConfigurationError, CloudTasksScheduler


logger = logging.getLogger('smartInterview.question_banks')

cloud_tasks_scheduler = CloudTasksScheduler()

MAX_SKILL_CONTEXT_CHARS = 1200
DEFAULT_PRIMARY_CODING_BANK_TARGET = 10
DEFAULT_LITIO_CODING_ASK_COUNT = 3
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
    'backend framework',
    'cloud',
    'cloud platform',
    'database',
    'database query language',
    'data engineering platform',
    'data engineering',
    'data architecture',
    'data quality',
    'data warehousing',
    'devops',
    'frontend',
    'frontend development',
    'frontend framework',
    'framework',
    'java api',
    'java concept',
    'java framework',
    'mobile development',
    'mobile framework',
    'operating system',
    'programming language',
    'crm platform',
    'salesforce',
    'salesforce development',
    'software development',
    'web services',
}
TECHNICAL_CODING_SKILL_KEYS = {
    'angular',
    'apex',
    'apex-development',
    'collection-framework',
    'collections-framework',
    'concurrency',
    'core-java',
    'data-architecture',
    'data-engineering',
    'data-modeling',
    'data-pipeline',
    'data-pipelines',
    'data-quality-validation',
    'data-warehousing',
    'django',
    'django-rest-framework',
    'etl-elt',
    'express',
    'fastapi',
    'flask',
    'flutter',
    'html-css',
    'java',
    'java-concurrency-and-collection',
    'java-concurrency-and-collections',
    'javascript',
    'laravel',
    'linux',
    'mern-stack-development',
    'lightning-web-components-development',
    'lightning-web-components-lwc',
    'lightning-web-components-lwc-development',
    'lwc',
    'mongodb',
    'multithreading',
    'multithreading-and-concurrency',
    'mysql',
    'next-js',
    'node-js',
    'php',
    'postgresql',
    'python',
    'react',
    'react-js',
    'react-native',
    'rest-api',
    'salesforce',
    'salesforce-apex-development',
    'salesforce-integration-and-web-service',
    'salesforce-integration-using-web-service',
    'salesforce-integration-web-services-soql-saql',
    'soql',
    'spring',
    'spring-boot',
    'sql',
}
JAVA_CODING_TARGET_ORDER = {
    'core-java': 0,
    'java': 0,
    'multithreading': 1,
    'multithreading-and-concurrency': 1,
    'concurrency': 1,
    'collection-framework': 2,
    'collections-framework': 2,
    'java-concurrency-and-collection': 3,
    'java-concurrency-and-collections': 3,
    'sql': 4,
}
NON_CODING_TARGET_SKILL_KEYS = {
    'adaptability',
    'analytical-skill',
    'analytical-skills',
    'collaboration',
    'communication',
    'communication-skill',
    'communication-skills',
    'decision-making',
    'leadership',
    'problem-solving',
    'stakeholder-management',
    'teamwork',
    'time-management',
}
GENERIC_TECHNICAL_ROLE_SKIP_SKILL_KEYS = {
    'agile',
    'communication-skill',
    'communication-skills',
    'documentation',
    'git',
    'industry-trends-awareness',
    'leadership',
    'problem-solving',
    'scrum',
    'soft-skill',
    'soft-skills',
    'stakeholder-management',
    'teamwork',
    'version-control',
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
MOBILE_SKILL_KEYS = {
    'flutter',
    'react-native',
    'reactnative',
}
CORE_TECHNICAL_SKILL_KEYS = {
    'angular',
    'django',
    'django-rest-framework',
    'djangorestframework',
    'html-css',
    'htmlcss',
    'javascript',
    'mongodb',
    'mysql',
    'next-js',
    'nextjs',
    'node-js',
    'nodejs',
    'postgresql',
    'python',
    'react',
    'rest-api',
    'restapi',
    'sql',
}
UNUSABLE_COVERAGE_AREAS = {
    '',
    'general',
    'generic',
    'misc',
    'miscellaneous',
    'uncategorized',
    'unclassified',
    'unknown',
    'other',
}
QUESTION_POOL_ROOT_SKILL_KEYS = {
    'angular',
    'apex',
    'django',
    'fastapi',
    'flask',
    'html-css',
    'java',
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
    'salesforce',
    'selenium-webdriver',
    'spring',
    'spring-boot',
    'sql',
}
QUESTION_POOL_QUALIFIER_TOKENS = {
    'advanced',
    'api',
    'backend',
    'basic',
    'core',
    'developer',
    'development',
    'engineering',
    'framework',
    'frontend',
    'fullstack',
    'language',
    'programmer',
    'programming',
    'software',
}
QUESTION_POOL_EQUIVALENT_SKILL_KEYS = {
    'python': {
        'backend-python',
        'core-python',
        'python-backend',
        'python-developer',
        'python-development',
        'python-programmer',
        'python-programming',
    },
    'java': {
        'backend-java',
        'core-java',
        'java-backend',
        'java-developer',
        'java-development',
        'java-programmer',
        'java-programming',
    },
    'javascript': {
        'ecmascript',
        'frontend-javascript',
        'javascript-development',
        'javascript-programming',
        'js',
        'vanilla-javascript',
    },
    'node-js': {
        'backend-node-js',
        'express',
        'express-js',
        'node',
        'nodejs',
    },
    'react': {
        'frontend-react',
        'react-js',
        'reactjs',
    },
    'rest-api': {
        'api',
        'api-integration',
        'apis',
        'backend-api',
        'rest-apis',
        'restful-api',
        'restful-apis',
        'web-services',
    },
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


def canonical_skill_key_for_question_pool(skill: Skill, section: dict[str, Any] | None = None) -> str:
    terms = _question_pool_terms(skill, section)
    for term in terms:
        key = _skill_match_key_for_question_pool(term)
        family_key = _question_pool_family_key(term)
        if family_key and family_key != key:
            return family_key
    for term in terms:
        key = _skill_match_key_for_question_pool(term)
        if key:
            return key
    return skill.key


def skill_family_key_for_question_pool(skill: Skill, section: dict[str, Any] | None = None) -> str:
    terms = _question_pool_terms(skill, section)
    for term in terms:
        key = _question_pool_family_key(term)
        if key:
            return key
    return canonical_skill_key_for_question_pool(skill, section)


def resolve_equivalent_skill_ids_for_question_pool(skill: Skill, section: dict[str, Any] | None = None) -> list[int]:
    if not skill or not getattr(skill, 'id', None):
        return []

    metadata = question_pool_metadata_for_skill(skill, section)
    lookup_keys = set(metadata['lookup_keys'])
    lookup_names = {normalize_skill_key(name) for name in metadata['lookup_names'] if normalize_skill_key(name)}
    equivalent_ids = [skill.id]

    for candidate in Skill.objects.filter(is_active=True).only('id', 'name', 'key', 'aliases').order_by('id'):
        if candidate.id == skill.id:
            continue
        candidate_keys = _skill_lookup_keys(candidate)
        candidate_name_key = normalize_skill_key(candidate.name)
        if (
            candidate.key in lookup_keys
            or candidate_name_key in lookup_keys
            or candidate_name_key in lookup_names
            or metadata['skill_family_key'] in candidate_keys
            or bool(candidate_keys & lookup_keys)
        ):
            equivalent_ids.append(candidate.id)

    return equivalent_ids


def question_pool_metadata_for_skill(skill: Skill, section: dict[str, Any] | None = None) -> dict[str, Any]:
    canonical_key = canonical_skill_key_for_question_pool(skill, section)
    family_key = _question_pool_family_key(canonical_key) or canonical_key
    terms = _question_pool_terms(skill, section)
    lookup_keys = {canonical_key, family_key, skill.key, normalize_skill_key(skill.name)}
    lookup_names = {_canonical_skill_name_for_question_pool(skill.name)}

    for term in terms:
        key = _skill_match_key_for_question_pool(term)
        family = _question_pool_family_key(term)
        if key:
            lookup_keys.add(key)
            lookup_names.add(_canonical_skill_name_for_question_pool(term))
        if family:
            lookup_keys.add(family)

    for key in list(lookup_keys):
        lookup_keys.update(_known_question_pool_alias_keys(key))
        lookup_keys.update(_configured_question_pool_equivalent_keys(key))

    lookup_names.update(_canonical_skill_name_for_question_pool(key.replace('-', ' ')) for key in lookup_keys)
    return {
        'canonical_skill_key': canonical_key,
        'skill_family_key': family_key,
        'lookup_keys': sorted(key for key in lookup_keys if key),
        'lookup_names': sorted(name for name in lookup_names if name),
    }


def skill_question_pool_queryset(skill: Skill, section: dict[str, Any] | None = None):
    return SkillQuestion.objects.filter(skill_id__in=resolve_equivalent_skill_ids_for_question_pool(skill, section))


def _question_pool_terms(skill: Skill, section: dict[str, Any] | None = None) -> list[str]:
    terms: list[str] = []
    if section:
        for key in [
            'canonical_skill_key',
            'skill_family_key',
            'skill_key',
            'key',
            'name',
            'skill',
            'skill_name',
        ]:
            value = section.get(key)
            if value:
                terms.append(str(value))
        for key in ['aliases', 'equivalent_skill_keys', 'equivalent_skills', 'canonical_aliases']:
            terms.extend(_json_list(section.get(key)))
    terms.extend([skill.name, skill.key.replace('-', ' ')])
    terms.extend(_json_list(skill.aliases))
    return _dedupe_strings(terms)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = _clean_string(value)
        key = normalize_skill_key(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _skill_lookup_keys(skill: Skill) -> set[str]:
    keys = {
        skill.key,
        normalize_skill_key(skill.name),
        _skill_match_key_for_question_pool(skill.name),
        _question_pool_family_key(skill.name),
    }
    for alias in _json_list(skill.aliases):
        keys.update({
            normalize_skill_key(alias),
            _skill_match_key_for_question_pool(alias),
            _question_pool_family_key(alias),
        })
    for key in list(keys):
        keys.update(_known_question_pool_alias_keys(key))
        keys.update(_configured_question_pool_equivalent_keys(key))
    return {key for key in keys if key}


def _skill_match_key_for_question_pool(value: Any) -> str:
    try:
        from smartInterviewApp.services.interview_blueprints import _skill_match_key
        return _skill_match_key(_clean_string(value))
    except Exception:
        return normalize_skill_key(_clean_string(value))


def _canonical_skill_name_for_question_pool(value: Any) -> str:
    try:
        from smartInterviewApp.services.interview_blueprints import _canonical_skill_name
        return _canonical_skill_name(_clean_string(value))
    except Exception:
        cleaned = _clean_string(value)
        return cleaned[:1].upper() + cleaned[1:] if cleaned.islower() else cleaned


def _question_pool_family_key(value: Any) -> str:
    key = _skill_match_key_for_question_pool(value)
    if not key:
        return ''
    normalized = normalize_skill_key(str(key))
    for family_key, aliases in QUESTION_POOL_EQUIVALENT_SKILL_KEYS.items():
        if normalized == family_key or normalized in aliases:
            return family_key

    tokens = [token for token in normalized.split('-') if token]
    for root_key in sorted(QUESTION_POOL_ROOT_SKILL_KEYS, key=len, reverse=True):
        root_tokens = root_key.split('-')
        if not all(token in tokens for token in root_tokens):
            continue
        extra_tokens = [token for token in tokens if token not in root_tokens]
        if extra_tokens and all(token in QUESTION_POOL_QUALIFIER_TOKENS for token in extra_tokens):
            return root_key
    return normalized


def _known_question_pool_alias_keys(key: str) -> set[str]:
    normalized = normalize_skill_key(key)
    if not normalized:
        return set()
    aliases = {normalized, _question_pool_family_key(normalized)}
    try:
        from smartInterviewApp.services.interview_blueprints import CANONICAL_SKILL_NAMES
        canonical = CANONICAL_SKILL_NAMES.get(normalized)
        if canonical:
            canonical_key = normalize_skill_key(canonical)
            aliases.add(canonical_key)
            aliases.add(_question_pool_family_key(canonical_key))
            aliases.update(
                alias_key
                for alias_key, canonical_name in CANONICAL_SKILL_NAMES.items()
                if normalize_skill_key(canonical_name) == canonical_key
            )
    except Exception:
        pass
    return {alias for alias in aliases if alias}


def _configured_question_pool_equivalent_keys(key: str) -> set[str]:
    normalized = normalize_skill_key(key)
    if not normalized:
        return set()
    configured = getattr(settings, 'INTERVIEW_QUESTION_POOL_EQUIVALENT_SKILL_KEYS', {}) or {}
    combined = {family: set(aliases) for family, aliases in QUESTION_POOL_EQUIVALENT_SKILL_KEYS.items()}
    if isinstance(configured, dict):
        for family, aliases in configured.items():
            family_key = normalize_skill_key(str(family))
            if not family_key:
                continue
            values = _json_list(aliases)
            if isinstance(aliases, str):
                values = [aliases]
            combined.setdefault(family_key, set()).update(normalize_skill_key(value) for value in values)

    matches: set[str] = set()
    for family_key, aliases in combined.items():
        alias_keys = {normalize_skill_key(alias) for alias in aliases if normalize_skill_key(alias)}
        if normalized == family_key or normalized in alias_keys:
            matches.add(family_key)
            matches.update(alias_keys)
    return {match for match in matches if match}


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
    skip_reason = _blueprint_enqueue_skip_reason(blueprint)
    if skip_reason:
        logger.warning(
            'Question bank auto-generation skipped blueprint_id=%s reason=%s status=%s minimum_ready=%s',
            blueprint.id,
            skip_reason,
            blueprint.status,
            blueprint.minimum_ready,
        )
        return [{'ok': True, 'status': 'skipped_blueprint_not_ready', 'reason': skip_reason, 'blueprint_id': blueprint.id}]
    active_plan = _blueprint_plan(blueprint)
    active_signature = _active_plan_signature(blueprint)
    if active_plan and active_plan != blueprint.blueprint_plan:
        blueprint.blueprint_plan = active_plan
        blueprint.save(update_fields=['blueprint_plan', 'updated_at'])
    results: list[dict[str, Any]] = []
    eligible_processed = 0
    max_skills = max(1, int(getattr(settings, 'INTERVIEW_QUESTION_BANK_MAX_SKILLS_PER_BLUEPRINT_ENQUEUE', 5)))
    all_plans = list(
        JobInterviewSkill.objects
        .select_related('skill')
        .filter(blueprint=blueprint, is_active=True, skill__is_active=True)
        .order_by('priority', 'id')
    )
    plans = all_plans
    runtime_skill_ids = _runtime_section_skill_ids(blueprint)
    if runtime_skill_ids:
        plans = [plan for plan in all_plans if plan.skill_id in runtime_skill_ids]
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
        results.append(ensure_question_bank_for_skill(
            plan.skill_id,
            verbal_target_count=_verbal_bank_target_for_plan(plan),
            blueprint=blueprint,
            target_role=_target_role_for_plan(plan),
            plan_signature=active_signature,
        ))
    coding_plans = _coding_target_plans_for_blueprint(blueprint, all_plans)
    coding_target_count = coding_bank_target_count()
    for plan in coding_plans:
        coding_count = CodingQuestion.objects.filter(skill=plan.skill, is_active=True).count()
        if coding_count >= coding_target_count:
            results.append({
                'ok': True,
                'status': 'enough_coding_questions',
                'skill_id': plan.skill_id,
                'skill_key': plan.skill.key,
                'skill_role': plan.skill_role,
                'coding_count': coding_count,
                'target_count': coding_target_count,
                'task_type': QuestionGenerationJob.TaskType.CODING_GENERATION,
            })
            continue
        enqueue_result = enqueue_skill_coding_generation(
            plan.skill_id,
            target_count=coding_target_count,
            batch_size=max(1, coding_target_count - coding_count),
            blueprint=blueprint,
            target_role='coding_target',
            plan_signature=active_signature,
        )
        results.append({
            'ok': bool(enqueue_result.get('queued') or enqueue_result.get('status') in {'already_queued_or_running', 'enough_questions'}),
            'status': enqueue_result.get('status'),
            'skill_id': plan.skill_id,
            'skill_key': plan.skill.key,
            'skill_role': plan.skill_role,
            'coding_count': coding_count,
            'target_count': coding_target_count,
            'task_type': QuestionGenerationJob.TaskType.CODING_GENERATION,
            'coding': enqueue_result,
        })
    return results


def _blueprint_enqueue_skip_reason(blueprint: JobInterviewBlueprint) -> str:
    if blueprint.status == JobInterviewBlueprint.Status.FAILED:
        return 'blueprint_failed'
    if not blueprint.minimum_ready:
        return 'minimum_ready_false'
    plan = blueprint.blueprint_plan if isinstance(blueprint.blueprint_plan, dict) else {}
    fatal_issues = set(str(item) for item in (plan.get('fatal_quality_issues') or []) if item)
    quality_issue = str(plan.get('quality_issue') or '').strip()
    if quality_issue:
        fatal_issues.add(quality_issue)
    for warning in plan.get('quality_warnings') or []:
        if isinstance(warning, dict) and warning.get('fatal'):
            code = str(warning.get('code') or '').strip()
            if code:
                fatal_issues.add(code)
    fatal_codes = {
        'unsupported_primary_skill',
        'unsupported_selected_primary_skill',
        'primary_skill_missing',
        'infrastructure_without_jd_evidence',
        'no_active_runtime_sections',
        'no_strong_fallback_primary',
        'all_selected_skills_noisy_or_generic',
    }
    blocking = sorted(fatal_issues & fatal_codes)
    if blocking:
        return f'fatal_quality_issue:{",".join(blocking)}'
    return ''


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
    runtime_sections = plan.get('runtime_sections')
    if isinstance(runtime_sections, list):
        items.extend(item for item in runtime_sections if isinstance(item, dict))

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
            'target_questions': item.get('target_questions'),
            'selection_basis': item.get('selection_basis'),
            'reason': item.get('reason'),
        }
    return metadata


def _runtime_section_skill_ids(blueprint: JobInterviewBlueprint) -> set[int]:
    return set(_runtime_section_plan_order(blueprint))


def _runtime_section_sub_skill_ids(blueprint: JobInterviewBlueprint) -> list[int]:
    plan = blueprint.blueprint_plan if isinstance(blueprint.blueprint_plan, dict) else {}
    sections = plan.get('runtime_sections')
    if not isinstance(sections, list):
        return []
    ids: list[int] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get('skill_role') != JobInterviewSkill.SkillRole.SUB_SKILL:
            continue
        try:
            skill_id = int(section.get('skill_id') or 0)
        except (TypeError, ValueError):
            continue
        if skill_id and skill_id not in ids:
            ids.append(skill_id)
    return ids


def _runtime_section_plan_order(blueprint: JobInterviewBlueprint) -> list[int]:
    plan = blueprint.blueprint_plan if isinstance(blueprint.blueprint_plan, dict) else {}
    sections = plan.get('runtime_sections')
    if not isinstance(sections, list):
        return []
    ids: list[int] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        try:
            skill_id = int(section.get('skill_id') or 0)
        except (TypeError, ValueError):
            continue
        if skill_id and skill_id not in ids:
            ids.append(skill_id)
    return ids


def _verbal_bank_target_for_plan(plan: JobInterviewSkill) -> int:
    configured = int(getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100) or 100)
    runtime_target = _runtime_target_count_for_plan(plan)
    minimum = 5 if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY else 3
    return max(configured, runtime_target, minimum)


def _blueprint_plan(blueprint: JobInterviewBlueprint) -> dict[str, Any]:
    return ensure_blueprint_plan_signature(blueprint.blueprint_plan if isinstance(blueprint.blueprint_plan, dict) else {})


def _active_plan_signature(blueprint: JobInterviewBlueprint) -> str:
    plan = _blueprint_plan(blueprint)
    return str(plan.get('plan_signature') or blueprint_plan_signature(plan)).strip()


def _blueprint_coding_required(blueprint: JobInterviewBlueprint, plans: list[JobInterviewSkill]) -> bool:
    plan = _blueprint_plan(blueprint)
    return bool(plan.get('coding_required'))


def _coding_target_names_from_blueprint(blueprint: JobInterviewBlueprint) -> list[str]:
    plan = _blueprint_plan(blueprint)
    names: list[str] = []
    for item in plan.get('coding_skill_targets') or []:
        if isinstance(item, dict):
            name = _clean_string(item.get('name') or item.get('skill') or item.get('skill_name'))
        else:
            name = _clean_string(item)
        if normalize_skill_key(name) in NON_CODING_TARGET_SKILL_KEYS:
            continue
        if normalize_skill_key(name) in GENERIC_TECHNICAL_ROLE_SKIP_SKILL_KEYS:
            continue
        if name and name not in names:
            names.append(name)
    return names


def _coding_target_order_index(name: str, target_names: list[str]) -> int:
    target_index: dict[str, int] = {}
    for index, target_name in enumerate(target_names):
        for key in _coding_target_key_set(target_name):
            target_index.setdefault(key, index)
    plan_keys = _coding_target_key_set(name)
    indexes = [target_index[key] for key in plan_keys if key in target_index]
    if indexes:
        return min(indexes)
    key = _skill_match_key_for_question_pool(name)
    return JAVA_CODING_TARGET_ORDER.get(key, 999)


def _coding_target_name_allowed(name: str, plans: list[JobInterviewSkill]) -> bool:
    key = normalize_skill_key(name)
    if not key or key in NON_CODING_TARGET_SKILL_KEYS or key in GENERIC_TECHNICAL_ROLE_SKIP_SKILL_KEYS:
        return False
    for plan in plans:
        if key in _coding_target_key_set(plan.skill.name) or key in _skill_lookup_keys(plan.skill):
            return _is_coding_skill(plan.skill)
    return True


def _coding_target_key_set(name: str) -> set[str]:
    key = normalize_skill_key(name)
    keys = {
        key,
        _skill_match_key_for_question_pool(name),
        _question_pool_family_key(name),
    }
    for item in list(keys):
        keys.update(_known_question_pool_alias_keys(item))
        keys.update(_configured_question_pool_equivalent_keys(item))
    return {item for item in keys if item}


def _coding_questions_for_blueprint_target(blueprint: JobInterviewBlueprint) -> int:
    plan = _blueprint_plan(blueprint)
    return _clamp_int(plan.get('coding_questions_to_ask'), 3, 1, 3)


def _coding_target_plans_for_blueprint(
    blueprint: JobInterviewBlueprint,
    plans: list[JobInterviewSkill],
    *,
    create_missing: bool = False,
) -> list[JobInterviewSkill]:
    if not _blueprint_coding_required(blueprint, plans):
        return []

    target_names = [
        name for name in _coding_target_names_from_blueprint(blueprint)
        if _coding_target_name_allowed(name, plans)
    ]
    target_keys: set[str] = set()
    for name in target_names:
        target_keys.update(_coding_target_key_set(name))
    if not target_keys:
        return []
    plans_by_key = {
        key: plan
        for plan in plans
        for key in _skill_lookup_keys(plan.skill)
    }
    plan_keys = set(plans_by_key)
    coding_questions_to_ask = _coding_questions_for_blueprint_target(blueprint)
    selected: list[JobInterviewSkill] = []
    seen_skill_ids: set[int] = set()

    for plan in plans:
        if (
            bool(target_keys & _skill_lookup_keys(plan.skill))
            and _is_coding_skill(plan.skill)
        ):
            if int(plan.coding_questions_to_ask or 0) <= 0:
                plan.coding_questions_to_ask = coding_questions_to_ask
                plan.save(update_fields=['coding_questions_to_ask', 'updated_at'])
            selected.append(plan)
            seen_skill_ids.add(plan.skill_id)

    missing_names = [
        name for name in target_names
        if not (_coding_target_key_set(name) & plan_keys)
    ]
    if create_missing and missing_names and getattr(settings, 'INTERVIEW_BLUEPRINT_CREATE_MISSING_SKILLS', True):
        next_priority = max([plan.priority for plan in plans] or [0]) + 1
        for name in missing_names:
            canonical_name = _canonical_skill_name_for_question_pool(name)
            key = _skill_match_key_for_question_pool(canonical_name)
            if not key:
                continue
            skill, _ = Skill.objects.get_or_create(
                key=key,
                defaults={
                    'name': canonical_name[:120],
                    'category': 'Coding Target',
                    'description': 'Auto-created from blueprint coding_skill_targets.',
                    'is_active': True,
                },
            )
            plan, _ = JobInterviewSkill.objects.update_or_create(
                blueprint=blueprint,
                skill=skill,
                defaults={
                    'job': blueprint.job,
                    'skill_role': JobInterviewSkill.SkillRole.SUB_SKILL,
                    'priority': next_priority,
                    'questions_to_ask': 3,
                    'coding_questions_to_ask': coding_questions_to_ask,
                    'difficulty_mix': {'basic': 1, 'intermediate': 2, 'advanced': 0},
                    'coding_difficulty_mix': {'easy': 0, 'medium': 1, 'hard': 0},
                    'source': JobInterviewSkill.Source.SYSTEM,
                    'is_required': True,
                    'is_active': True,
                },
            )
            next_priority += 1
            if plan.skill_id not in seen_skill_ids:
                selected.append(plan)
                seen_skill_ids.add(plan.skill_id)

    return sorted(
        selected,
        key=lambda plan: (
            _coding_target_order_index(plan.skill.name, target_names),
            plan.priority,
            plan.skill.name,
        ),
    )


def _coding_readiness_for_blueprint(
    blueprint: JobInterviewBlueprint,
    plans: list[JobInterviewSkill],
    *,
    create_missing: bool = False,
) -> dict[str, Any]:
    required = _blueprint_coding_required(blueprint, plans)
    target_plans = _coding_target_plans_for_blueprint(blueprint, plans, create_missing=create_missing) if required else []
    target_skill_ids = [plan.skill_id for plan in target_plans]
    counts = {
        plan.skill_id: CodingQuestion.objects.filter(skill=plan.skill, is_active=True).count()
        for plan in target_plans
    }
    total_active = sum(counts.values())
    active_signature = _active_plan_signature(blueprint)
    coding_jobs = [
        job for job in QuestionGenerationJob.objects.filter(
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            skill_id__in=target_skill_ids,
        )
        if _generation_job_matches_active_plan(job, blueprint, active_signature, target_skill_ids)
    ]
    failed_job_count = sum(1 for job in coding_jobs if job.status == QuestionGenerationJob.Status.FAILED)
    pending_job_count = sum(1 for job in coding_jobs if job.status in {QuestionGenerationJob.Status.QUEUED, QuestionGenerationJob.Status.RUNNING})
    reasons: list[str] = []
    if required and not target_plans:
        reasons.append('coding_targets_missing')
    if required and total_active < litio_coding_ask_count():
        reasons.append('coding_questions_missing')
    if failed_job_count:
        reasons.append('coding_generation_failed')
    return {
        'required': required,
        'target_count': litio_coding_ask_count() if required else 0,
        'active_count': total_active,
        'target_skills': [
            {
                'skill_id': plan.skill_id,
                'skill_name': plan.skill.name,
                'skill_key': plan.skill.key,
                'active_count': counts.get(plan.skill_id, 0),
            }
            for plan in target_plans
        ],
        'pending_or_running_job_count': pending_job_count,
        'failed_job_count': failed_job_count,
        'reasons': reasons,
    }


def _generation_job_matches_active_plan(
    generation_job: QuestionGenerationJob,
    blueprint: JobInterviewBlueprint,
    plan_signature: str,
    target_skill_ids: list[int] | set[int],
) -> bool:
    payload = generation_job.payload if isinstance(generation_job.payload, dict) else {}
    if not payload:
        return False
    try:
        payload_blueprint_id = int(payload.get('blueprint_id') or 0)
        payload_target_skill_id = int(payload.get('target_skill_id') or generation_job.skill_id or 0)
    except (TypeError, ValueError):
        return False
    return (
        payload_blueprint_id == blueprint.id
        and str(payload.get('plan_signature') or '').strip() == plan_signature
        and payload_target_skill_id in set(target_skill_ids)
    )


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


def _target_role_for_plan(plan: JobInterviewSkill) -> str:
    if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY:
        return 'primary'
    if plan.skill_role == JobInterviewSkill.SkillRole.SUB_SKILL:
        return 'sub_skill'
    return str(plan.skill_role or '')


def _should_include_coding_generation_for_plan(plan: JobInterviewSkill, coding_target: int) -> bool:
    if coding_target <= 0:
        return plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY and int(plan.coding_questions_to_ask or 0) > 0
    if plan.skill_role != JobInterviewSkill.SkillRole.PRIMARY:
        return False
    return _is_coding_skill(plan.skill)


def ensure_question_bank_for_skill(
    skill_id: int,
    include_coding: bool = False,
    *,
    verbal_target_count: int | None = None,
    coding_target_count: int | None = None,
    force_coding: bool = False,
    blueprint: JobInterviewBlueprint | None = None,
    target_role: str = '',
    plan_signature: str = '',
) -> dict[str, Any]:
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_ENABLED', True):
        return {'ok': True, 'status': 'disabled', 'skill_id': skill_id}
    skill = Skill.objects.filter(id=skill_id, is_active=True).first()
    if not skill:
        return {'ok': False, 'status': 'missing_skill', 'skill_id': skill_id}

    verbal_target = max(1, int(verbal_target_count or getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100)))
    coding_target = max(0, int(coding_target_count if coding_target_count is not None else getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0)))
    pool_metadata = question_pool_metadata_for_skill(skill)
    equivalent_skill_ids = resolve_equivalent_skill_ids_for_question_pool(skill)
    verbal_count = SkillQuestion.objects.filter(skill_id__in=equivalent_skill_ids, is_active=True).count()
    coding_count = CodingQuestion.objects.filter(skill=skill, is_active=True).count()
    result: dict[str, Any] = {
        'ok': True,
        'skill_id': skill.id,
        'skill_key': skill.key,
        'canonical_skill_key': pool_metadata['canonical_skill_key'],
        'skill_family_key': pool_metadata['skill_family_key'],
        'equivalent_skill_ids': equivalent_skill_ids,
        'verbal_count': verbal_count,
        'coding_count': coding_count,
        'verbal': None,
        'coding': None,
    }

    if verbal_count >= verbal_target:
        logger.info('Question bank enough skill_id=%s skill_key=%s verbal_count=%s target=%s', skill.id, skill.key, verbal_count, verbal_target)
        result['verbal'] = {'queued': False, 'status': 'enough_questions'}
    else:
        result['verbal'] = enqueue_skill_question_generation(
            skill.id,
            target_count=verbal_target,
            blueprint=blueprint,
            target_role=target_role,
            plan_signature=plan_signature,
        )

    if include_coding and coding_target > 0 and (force_coding or _is_coding_skill(skill)):
        if coding_count >= coding_target:
            logger.info('Coding bank enough skill_id=%s skill_key=%s coding_count=%s target=%s', skill.id, skill.key, coding_count, coding_target)
            result['coding'] = {'queued': False, 'status': 'enough_questions'}
        else:
            result['coding'] = enqueue_skill_coding_generation(
                skill.id,
                target_count=coding_target,
                blueprint=blueprint,
                target_role='coding_target',
                plan_signature=plan_signature,
            )
    elif include_coding and coding_target <= 0:
        logger.info('Coding question generation auto-enqueue disabled by target_count=0 skill_id=%s', skill.id)
        result['coding'] = {'queued': False, 'status': 'coding_generation_disabled'}
    return result


def enqueue_skill_question_generation(
    skill_id: int,
    target_count: int | None = None,
    *,
    blueprint: JobInterviewBlueprint | None = None,
    target_role: str = '',
    plan_signature: str = '',
) -> dict[str, Any]:
    return _enqueue_skill_generation(
        skill_id=skill_id,
        task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
        target_count=target_count or int(getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100)),
        batch_size=max(1, int(getattr(settings, 'INTERVIEW_QUESTION_GENERATION_BATCH_SIZE', 10))),
        blueprint=blueprint,
        target_role=target_role,
        plan_signature=plan_signature,
    )


def enqueue_skill_coding_generation(
    skill_id: int,
    target_count: int | None = None,
    batch_size: int | None = None,
    *,
    blueprint: JobInterviewBlueprint | None = None,
    target_role: str = '',
    plan_signature: str = '',
) -> dict[str, Any]:
    return _enqueue_skill_generation(
        skill_id=skill_id,
        task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
        target_count=target_count or coding_bank_target_count(),
        batch_size=max(1, int(batch_size or getattr(settings, 'INTERVIEW_CODING_GENERATION_BATCH_SIZE', 2))),
        blueprint=blueprint,
        target_role=target_role,
        plan_signature=plan_signature,
    )


def _enqueue_skill_generation(
    skill_id: int,
    task_type: str,
    target_count: int,
    batch_size: int,
    *,
    blueprint: JobInterviewBlueprint | None = None,
    target_role: str = '',
    plan_signature: str = '',
) -> dict[str, Any]:
    if not getattr(settings, 'INTERVIEW_QUESTION_BANK_ENABLED', True):
        return {'queued': False, 'status': 'disabled', 'skill_id': skill_id}
    skill = Skill.objects.filter(id=skill_id, is_active=True).first()
    if not skill:
        return {'queued': False, 'status': 'missing_skill', 'skill_id': skill_id}
    if task_type == QuestionGenerationJob.TaskType.CODING_GENERATION and int(target_count) <= 0:
        logger.info('Coding question generation skipped because target_count is not positive skill_id=%s', skill.id)
        return {'queued': False, 'status': 'coding_generation_disabled', 'skill_id': skill.id, 'target_count': target_count}

    if task_type == QuestionGenerationJob.TaskType.QUESTION_GENERATION:
        pool_metadata = question_pool_metadata_for_skill(skill)
        equivalent_skill_ids = resolve_equivalent_skill_ids_for_question_pool(skill)
        count = SkillQuestion.objects.filter(skill_id__in=equivalent_skill_ids, is_active=True).count()
    else:
        pool_metadata = {}
        equivalent_skill_ids = [skill.id]
        count = CodingQuestion.objects.filter(skill=skill, is_active=True).count()
    missing_count = max(0, int(target_count) - count)
    if missing_count <= 0:
        logger.info('Generation skipped enough questions skill_id=%s task_type=%s count=%s target=%s', skill.id, task_type, count, target_count)
        return {'queued': False, 'status': 'enough_questions', 'skill_id': skill.id, 'count': count, 'target_count': target_count}

    existing_filter = {
        'task_type': task_type,
        'status__in': [QuestionGenerationJob.Status.QUEUED, QuestionGenerationJob.Status.RUNNING],
    }
    if task_type == QuestionGenerationJob.TaskType.QUESTION_GENERATION:
        existing_filter['skill_id__in'] = equivalent_skill_ids
    else:
        existing_filter['skill'] = skill
    existing_candidates = QuestionGenerationJob.objects.filter(**existing_filter).order_by('-created_at', '-id')
    existing = None
    if blueprint and plan_signature:
        for candidate in existing_candidates:
            payload = candidate.payload if isinstance(candidate.payload, dict) else {}
            if (
                int(payload.get('blueprint_id') or 0) == blueprint.id
                and str(payload.get('plan_signature') or '').strip() == plan_signature
            ):
                existing = candidate
                break
    else:
        existing = existing_candidates.first()
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
        'canonical_skill_key': pool_metadata.get('canonical_skill_key') or skill.key,
        'skill_family_key': pool_metadata.get('skill_family_key') or skill.key,
        'equivalent_skill_ids': equivalent_skill_ids,
        'target_verbal_questions': int(getattr(settings, 'INTERVIEW_SKILL_VERBAL_TARGET_COUNT', 100)),
        'target_coding_questions': int(target_count) if task_type == QuestionGenerationJob.TaskType.CODING_GENERATION else int(getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0)),
        'missing_verbal_questions': missing_count if task_type == QuestionGenerationJob.TaskType.QUESTION_GENERATION else 0,
        'missing_coding_questions': missing_count if task_type == QuestionGenerationJob.TaskType.CODING_GENERATION else 0,
        'batch_size': min(batch_size, missing_count),
    }
    if blueprint:
        payload.update({
            'blueprint_id': blueprint.id,
            'plan_signature': plan_signature or _active_plan_signature(blueprint),
            'target_skill_id': skill.id,
            'target_skill_name': skill.name,
            'target_role': target_role or ('coding_target' if task_type == QuestionGenerationJob.TaskType.CODING_GENERATION else ''),
        })
    generation_job = QuestionGenerationJob.objects.create(
        job=blueprint.job if blueprint else None,
        blueprint=blueprint,
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
    payload = generation_job.payload if generation_job and isinstance(generation_job.payload, dict) else {}
    resolved_coding_target = int(payload.get('target_coding_questions') or getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0) or 0)
    if (
        resolved_task_type == QuestionGenerationJob.TaskType.CODING_GENERATION
        and resolved_coding_target <= 0
    ):
        result = {
            'ok': True,
            'status': 'coding_generation_disabled',
            'skill_id': resolved_skill_id,
            'task_type': resolved_task_type,
            'generation_job_id': getattr(generation_job, 'id', None),
            'message': 'Coding question generation is disabled because no coding target count was provided.',
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
    stale_result = _skip_stale_coding_generation_job(generation_job, resolved_skill_id, resolved_task_type)
    if stale_result:
        return stale_result

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


def _skip_stale_coding_generation_job(
    generation_job: QuestionGenerationJob | None,
    resolved_skill_id: int,
    resolved_task_type: str,
) -> dict[str, Any] | None:
    if not generation_job or resolved_task_type != QuestionGenerationJob.TaskType.CODING_GENERATION:
        return None
    blueprint = generation_job.blueprint
    if not blueprint and generation_job.job_id:
        blueprint = JobInterviewBlueprint.objects.filter(job_id=generation_job.job_id).first()
    if not blueprint:
        return None
    plans = list(
        JobInterviewSkill.objects
        .select_related('skill')
        .filter(blueprint=blueprint, is_active=True, skill__is_active=True)
        .order_by('priority', 'id')
    )
    target_plans = _coding_target_plans_for_blueprint(blueprint, plans, create_missing=False)
    target_skill_ids = [plan.skill_id for plan in target_plans]
    if _generation_job_matches_active_plan(generation_job, blueprint, _active_plan_signature(blueprint), target_skill_ids):
        return None
    result = {
        'ok': True,
        'status': 'stale_blueprint_plan_ignored',
        'skill_id': resolved_skill_id,
        'task_type': resolved_task_type,
        'generation_job_id': generation_job.id,
        'blueprint_id': blueprint.id,
        'message': 'Coding generation job does not match the current blueprint plan signature or coding targets.',
    }
    if generation_job.status != QuestionGenerationJob.Status.SKIPPED:
        generation_job.status = QuestionGenerationJob.Status.SKIPPED
        generation_job.result = result
        generation_job.error_message = result['message']
        generation_job.finished_at = timezone.now()
        generation_job.save(update_fields=['status', 'result', 'error_message', 'finished_at', 'updated_at'])
    logger.info(
        'Question generation worker skipped stale coding job generation_job_id=%s skill_id=%s blueprint_id=%s',
        generation_job.id,
        resolved_skill_id,
        blueprint.id,
    )
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


def coding_bank_target_count() -> int:
    configured = int(getattr(settings, 'INTERVIEW_SKILL_CODING_TARGET_COUNT', 0) or 0)
    return configured if configured > 0 else DEFAULT_PRIMARY_CODING_BANK_TARGET


def litio_coding_ask_count() -> int:
    return max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_CODING_QUESTIONS', DEFAULT_LITIO_CODING_ASK_COUNT) or DEFAULT_LITIO_CODING_ASK_COUNT))


def primary_skill_plan_for_interview(interview_id: int) -> dict[str, Any]:
    interview = Interview.objects.select_related('role').filter(id=interview_id).first()
    if not interview:
        return {'ok': False, 'status': 'not_found', 'interview_id': interview_id, 'message': 'Interview not found.'}
    job = interview.role
    if not job:
        return {'ok': False, 'status': 'no_job', 'interview_id': interview.id, 'message': 'Interview has no related job.'}
    blueprint = JobInterviewBlueprint.objects.filter(job=job).first()
    if not blueprint:
        return {'ok': False, 'status': 'no_blueprint', 'interview_id': interview.id, 'message': 'No JobInterviewBlueprint found.'}
    primary_plan = (
        JobInterviewSkill.objects
        .select_related('skill')
        .filter(blueprint=blueprint, is_active=True, skill__is_active=True, skill_role=JobInterviewSkill.SkillRole.PRIMARY)
        .order_by('priority', 'id')
        .first()
    )
    if not primary_plan:
        return {'ok': False, 'status': 'no_primary_skill', 'interview_id': interview.id, 'message': 'No active primary skill found.'}
    return {'ok': True, 'interview': interview, 'job': job, 'blueprint': blueprint, 'primary_plan': primary_plan}


def enqueue_missing_coding_questions_for_interview(interview_id: int, *, apply: bool = False) -> dict[str, Any]:
    resolved = primary_skill_plan_for_interview(interview_id)
    if not resolved.get('ok'):
        return resolved
    interview = resolved['interview']
    job = resolved['job']
    primary_plan = resolved['primary_plan']
    skill = primary_plan.skill
    target_count = DEFAULT_PRIMARY_CODING_BANK_TARGET
    active_count = CodingQuestion.objects.filter(skill=skill, is_active=True).count()
    missing_count = max(0, target_count - active_count)
    existing_job = (
        QuestionGenerationJob.objects
        .filter(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status__in=[QuestionGenerationJob.Status.QUEUED, QuestionGenerationJob.Status.RUNNING],
        )
        .order_by('-created_at', '-id')
        .first()
    )
    result: dict[str, Any] = {
        'ok': True,
        'mode': 'apply' if apply else 'dry-run',
        'interview_id': interview.id,
        'role': _job_title(job),
        'primary_skill': skill.name,
        'coding_bank_target_count': target_count,
        'available_active_coding_count': active_count,
        'missing_bank_count': missing_count,
        'would_enqueue': False,
        'enqueued': False,
        'status': 'enough_coding_questions' if missing_count <= 0 else 'missing_coding_questions',
    }
    if missing_count <= 0:
        return result
    if existing_job:
        result.update({
            'status': 'already_queued_or_running',
            'generation_job_id': existing_job.id,
            'would_enqueue': False,
        })
        return result
    result['would_enqueue'] = True
    if not apply:
        return result
    enqueue_result = enqueue_skill_coding_generation(skill.id, target_count=target_count, batch_size=missing_count)
    result.update({
        'enqueued': bool(enqueue_result.get('queued')),
        'status': enqueue_result.get('status', result['status']),
        'generation_job_id': enqueue_result.get('generation_job_id'),
        'enqueue_result': enqueue_result,
    })
    return result


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
    audits_by_skill_id = {
        plan.skill_id: _question_bank_readiness_for_plan(plan)
        for plan in ([primary_plan] if primary_plan else []) + sub_skill_plans
    }
    runtime_sub_skill_plans, runtime_skip_reasons = _runtime_required_sub_skill_plans(job, sub_skill_plans, audits_by_skill_id, blueprint=blueprint)
    selected_plans = ([primary_plan] if primary_plan else []) + runtime_sub_skill_plans

    skipped_skills: list[dict[str, Any]] = []
    planned_gaps: list[dict[str, Any]] = []
    remaining_not_ready_reasons: list[str] = []
    if not selected_plans:
        remaining_not_ready_reasons.append('no_selected_skills')
    if not primary_plan:
        remaining_not_ready_reasons.append('no_primary_skill')

    runtime_sub_skill_ids = {plan.skill_id for plan in runtime_sub_skill_plans}
    for plan in sub_skill_plans:
        if plan.skill_id in runtime_sub_skill_ids:
            continue
        audit = audits_by_skill_id.get(plan.skill_id) or _question_bank_readiness_for_plan(plan)
        skipped_skills.append(_skip_summary(plan, runtime_skip_reasons.get(plan.skill_id, 'outside_runtime_required_scope'), audit))

    for plan in selected_plans:
        audit = audits_by_skill_id.get(plan.skill_id) or _question_bank_readiness_for_plan(plan)
        if not audit['reasons']:
            skipped_skills.append(_skip_summary(plan, 'ready', audit))
            continue
        if _should_skip_missing_only_skill(job, plan):
            skipped_skills.append(_skip_summary(plan, 'technical_role_skill_not_explicit_in_jd', audit))
            remaining_not_ready_reasons.extend(_skill_reason_labels(plan, audit['reasons']))
            continue
        missing_count = _missing_question_count_for_plan(audit)
        if missing_count <= 0:
            skipped_skills.append(_skip_summary(plan, 'no_question_count_gap', audit))
            remaining_not_ready_reasons.extend(_skill_reason_labels(plan, audit['reasons']))
            continue
        planned_gaps.append({
            'skill_id': plan.skill_id,
            'skill_name': plan.skill.name,
            'skill_key': plan.skill.key,
            'skill_role': plan.skill_role,
            'canonical_skill_key': audit.get('canonical_skill_key'),
            'skill_family_key': audit.get('skill_family_key'),
            'equivalent_skill_ids': audit.get('equivalent_skill_ids', [plan.skill_id]),
            'approved_count': audit['approved_count'],
            'coverage_ready_count': audit['coverage_ready_count'],
            'target_count': audit['target_count'],
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

    coding_readiness = _coding_readiness_for_blueprint(blueprint, plans, create_missing=False)
    remaining_not_ready_reasons.extend(coding_readiness['reasons'])

    return {
        'ok': True,
        'status': 'completed' if apply else 'preview',
        'interview_id': interview.id,
        'role': role_title,
        'primary_skill': primary_plan.skill.name if primary_plan else '',
        'selected_sub_skills': [plan.skill.name for plan in runtime_sub_skill_plans],
        'planned_gaps': planned_gaps,
        'generated_count': generated_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'skipped_skills': skipped_skills,
        'remaining_not_ready_reasons': remaining_not_ready_reasons,
        'coding_readiness': coding_readiness,
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
    equivalent_skill_ids = resolve_equivalent_skill_ids_for_question_pool(skill)
    existing = list(SkillQuestion.objects.filter(skill_id__in=equivalent_skill_ids).values('question_text', 'question_hash', 'family_key'))
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
                    question_type=validation['question_type'],
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


def _runtime_required_sub_skill_plans(
    job,
    sub_skill_plans: list[JobInterviewSkill],
    audits_by_skill_id: dict[int, dict[str, Any]],
    blueprint: JobInterviewBlueprint | None = None,
) -> tuple[list[JobInterviewSkill], dict[int, str]]:
    if not sub_skill_plans:
        return [], {}

    if blueprint:
        runtime_sub_skill_ids = _runtime_section_sub_skill_ids(blueprint)
        if runtime_sub_skill_ids:
            plans_by_id = {plan.skill_id: plan for plan in sub_skill_plans}
            selected = [plans_by_id[skill_id] for skill_id in runtime_sub_skill_ids if skill_id in plans_by_id]
            selected_ids = {plan.skill_id for plan in selected}
            skip_reasons = {
                plan.skill_id: 'outside_authoritative_runtime_sections'
                for plan in sub_skill_plans
                if plan.skill_id not in selected_ids
            }
            return selected, skip_reasons

    target_count = max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_SUB_SKILLS_TO_PICK', 3) or 3))
    eligible_plans = [
        plan for plan in sub_skill_plans
        if not _is_mobile_specific_skill(plan.skill) or _skill_explicitly_mentioned(job, plan.skill)
    ]
    ready_plans = [
        plan for plan in eligible_plans
        if not (audits_by_skill_id.get(plan.skill_id) or {}).get('reasons')
    ]
    ready_threshold = min(2, target_count)
    if len(ready_plans) >= ready_threshold:
        selected = _rank_runtime_sub_skill_plans(job, ready_plans, audits_by_skill_id)[:target_count]
        skip_reason = 'enough_ready_sub_skills'
    else:
        selected = _rank_runtime_sub_skill_plans(job, eligible_plans, audits_by_skill_id)[:target_count]
        skip_reason = 'outside_runtime_required_scope'

    selected_ids = {plan.skill_id for plan in selected}
    skip_reasons: dict[int, str] = {}
    for plan in sub_skill_plans:
        if plan.skill_id in selected_ids:
            continue
        if _is_mobile_specific_skill(plan.skill) and not _skill_explicitly_mentioned(job, plan.skill):
            skip_reasons[plan.skill_id] = 'outside_runtime_required_scope'
        else:
            skip_reasons[plan.skill_id] = skip_reason
    return selected, skip_reasons


def _rank_runtime_sub_skill_plans(
    job,
    plans: list[JobInterviewSkill],
    audits_by_skill_id: dict[int, dict[str, Any]],
) -> list[JobInterviewSkill]:
    return sorted(
        plans,
        key=lambda plan: (
            -_runtime_sub_skill_score(job, plan, audits_by_skill_id.get(plan.skill_id) or {}),
            plan.priority,
            plan.id,
        ),
    )


def _runtime_sub_skill_score(job, plan: JobInterviewSkill, audit: dict[str, Any]) -> int:
    skill = plan.skill
    score = 0
    if not audit.get('reasons'):
        score += 1000
    if _skill_explicitly_mentioned(job, skill):
        score += 200
    if _is_core_technical_skill(skill):
        score += 120
    if _has_existing_approved_bank(audit):
        score += 80
    if _is_mobile_specific_skill(skill):
        score -= 50
    score += max(0, 50 - int(plan.priority or 0))
    score += min(40, int(audit.get('approved_count') or 0))
    return score


def _has_existing_approved_bank(audit: dict[str, Any]) -> bool:
    return int(audit.get('approved_count') or 0) > 0


def _is_core_technical_skill(skill: Skill) -> bool:
    category = (skill.category or '').strip().lower()
    return skill.key in CORE_TECHNICAL_SKILL_KEYS or category in {
        'backend development',
        'database',
        'frontend development',
        'programming language',
        'web services',
    }


def _is_mobile_specific_skill(skill: Skill) -> bool:
    category = (skill.category or '').strip().lower()
    return skill.key in MOBILE_SKILL_KEYS or category == 'mobile development'


def _question_bank_readiness_for_plan(plan: JobInterviewSkill) -> dict[str, Any]:
    pool_metadata = question_pool_metadata_for_skill(plan.skill)
    equivalent_skill_ids = resolve_equivalent_skill_ids_for_question_pool(plan.skill)
    questions = SkillQuestion.objects.filter(
        skill_id__in=equivalent_skill_ids,
        is_active=True,
        quality_status=SkillQuestion.QualityStatus.APPROVED,
    )
    approved_count = questions.count()
    coverage_ready_questions = [
        question
        for question in questions
        if _skill_question_has_required_metadata(question)
    ]
    coverage_ready_count = len(coverage_ready_questions)
    coverage_area_count = len({
        normalize_skill_key(question.coverage_area)
        for question in coverage_ready_questions
        if _usable_coverage_area(question.coverage_area)
    })
    distinct_family_count = len({
        normalize_skill_key(question.family_key)
        for question in coverage_ready_questions
        if normalize_skill_key(question.family_key)
    })
    target_count = _runtime_target_count_for_plan(plan)
    reasons: list[str] = []
    if plan.skill_role in {JobInterviewSkill.SkillRole.PRIMARY, JobInterviewSkill.SkillRole.SUB_SKILL}:
        if coverage_ready_count < target_count:
            reasons.append('coverage_ready_count_below_target')
        if coverage_area_count == 0:
            reasons.append('coverage_area_missing_or_unclassified')
    return {
        'approved_count': approved_count,
        'coverage_ready_count': coverage_ready_count,
        'target_count': target_count,
        'coverage_area_count': coverage_area_count,
        'distinct_family_count': distinct_family_count,
        'canonical_skill_key': pool_metadata['canonical_skill_key'],
        'skill_family_key': pool_metadata['skill_family_key'],
        'equivalent_skill_ids': equivalent_skill_ids,
        'reasons': reasons,
    }


def _missing_question_count_for_plan(audit: dict[str, Any]) -> int:
    coverage_ready_count = int(audit.get('coverage_ready_count') or 0)
    target_count = int(audit.get('target_count') or 0)
    return max(0, target_count - coverage_ready_count)


def _runtime_target_count_for_plan(plan: JobInterviewSkill) -> int:
    fallback = 5 if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY else 3
    return max(1, int(plan.questions_to_ask or fallback))


def _skill_question_has_required_metadata(question: SkillQuestion) -> bool:
    return (
        _usable_coverage_area(question.coverage_area)
        and bool(normalize_skill_key(question.family_key))
        and question.question_type in SkillQuestion.QuestionType.values
        and bool(_clean_string(question.expected_signal))
    )


def _usable_coverage_area(value: Any) -> bool:
    return normalize_skill_key(_clean_string(value)) not in UNUSABLE_COVERAGE_AREAS


def _skip_summary(plan: JobInterviewSkill, reason: str, audit: dict[str, Any]) -> dict[str, Any]:
    return {
        'skill_id': plan.skill_id,
        'skill_name': plan.skill.name,
        'skill_key': plan.skill.key,
        'skill_role': plan.skill_role,
        'reason': reason,
        'readiness_reasons': audit.get('reasons') or [],
        'canonical_skill_key': audit.get('canonical_skill_key'),
        'skill_family_key': audit.get('skill_family_key'),
        'equivalent_skill_ids': audit.get('equivalent_skill_ids', [plan.skill_id]),
        'approved_count': audit.get('approved_count', 0),
        'coverage_ready_count': audit.get('coverage_ready_count', 0),
        'target_count': audit.get('target_count', 0),
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
    section = _runtime_section_metadata_for_skill(blueprint, plan.skill_id)
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
        f'Runtime section target_questions: {section.get("target_questions", plan.questions_to_ask)}\n'
        f'Runtime section selection_basis: {section.get("selection_basis", "")}\n'
        f'Runtime section reason: {section.get("reason", "")}\n'
        f'Missing count: {missing_count}\n'
        f'Job description context:\n{description}'
    )


def _runtime_section_metadata_for_skill(blueprint: JobInterviewBlueprint, skill_id: int) -> dict[str, Any]:
    plan = blueprint.blueprint_plan if isinstance(blueprint.blueprint_plan, dict) else {}
    sections = plan.get('runtime_sections')
    if not isinstance(sections, list):
        return {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        try:
            section_skill_id = int(section.get('skill_id') or 0)
        except (TypeError, ValueError):
            continue
        if section_skill_id == skill_id:
            return section
    return {}


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
    question_type = _clean_string(item.get('question_type'))
    if not question_text:
        return {'ok': False, 'reason': 'question_text_empty'}
    if not expected_signal:
        return {'ok': False, 'reason': 'expected_signal_empty'}
    if not family_key:
        return {'ok': False, 'reason': 'family_key_empty'}
    if not _usable_coverage_area(coverage_area):
        return {'ok': False, 'reason': 'coverage_area_empty'}
    if question_type not in SkillQuestion.QuestionType.values:
        return {'ok': False, 'reason': 'question_type_empty'}
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
        'question_type': question_type,
        'normalized': normalized,
        'question_hash': question_hash,
    }


def _validate_skill_question_payload(
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
    question_type = _clean_string(item.get('question_type'))
    if not question_text:
        return {'ok': False, 'reason': 'question_text_empty'}
    if not expected_signal:
        return {'ok': False, 'reason': 'expected_signal_empty'}
    if not family_key:
        return {'ok': False, 'reason': 'family_key_empty'}
    if not _usable_coverage_area(coverage_area):
        return {'ok': False, 'reason': 'coverage_area_empty'}
    if question_type not in SkillQuestion.QuestionType.values:
        return {'ok': False, 'reason': 'question_type_empty'}

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
        'question_type': question_type,
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
        equivalent_skill_ids = resolve_equivalent_skill_ids_for_question_pool(skill)
        pool_count = SkillQuestion.objects.filter(skill_id__in=equivalent_skill_ids, is_active=True).count()
        batch_size = min(max(1, int(payload.get('batch_size') or getattr(settings, 'INTERVIEW_QUESTION_GENERATION_BATCH_SIZE', 10))), max(0, target - pool_count))
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
    pool_metadata = question_pool_metadata_for_skill(skill)
    return {
        'ok': True,
        'status': 'completed',
        'skill_id': skill.id,
        'skill_key': skill.key,
        'canonical_skill_key': pool_metadata['canonical_skill_key'],
        'skill_family_key': pool_metadata['skill_family_key'],
        'equivalent_skill_ids': resolve_equivalent_skill_ids_for_question_pool(skill),
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
        'Each question must include non-empty coverage_area, family_key, question_type, difficulty, and expected_signal. '
        'coverage_area must be a short snake_case label for the exact concept being tested, never general/unclassified/other. '
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
        'Generate practical coding tasks, not theory questions. Each task must include a clear problem statement, '
        'function signature or input/output format when applicable, constraints, edge cases, sample tests, and hidden-test guidance. '
        'Use explanation as the evaluation rubric: include what a correct solution must handle, complexity expectations, and common failure modes. '
        'Be conservative and practical. Avoid duplicate tasks within the response.\n\n'
        f'Skill category: {skill.category}\n'
        f'Skill aliases: {", ".join(_json_list(skill.aliases))[:MAX_SKILL_CONTEXT_CHARS]}'
    )
    parsed = _call_openai_json(prompt, _coding_question_schema(), 'skill_coding_question_bank')
    questions = parsed.get('coding_questions') if isinstance(parsed, dict) else []
    return [item for item in questions or [] if isinstance(item, dict)]


def insert_skill_questions(skill: Skill, questions: list[dict[str, Any]]) -> dict[str, int]:
    stats = {'generated_count': len(questions), 'inserted_count': 0, 'duplicate_skipped_count': 0, 'rejected_count': 0, 'failed_count': 0}
    equivalent_skill_ids = resolve_equivalent_skill_ids_for_question_pool(skill)
    existing = list(SkillQuestion.objects.filter(skill_id__in=equivalent_skill_ids).values('question_text', 'question_hash', 'family_key'))
    seen_normalized = {_normalize_question_text(item['question_text']) for item in existing}
    seen_hashes = {item['question_hash'] for item in existing if item['question_hash']}
    seen_family_texts = [(normalize_skill_key(item['family_key'] or ''), _normalize_question_text(item['question_text'])) for item in existing]

    for item in questions:
        validation = _validate_skill_question_payload(skill, item, seen_normalized, seen_hashes, seen_family_texts)
        if not validation['ok']:
            stats['rejected_count'] += 1
            if validation['reason'] == 'duplicate_question':
                stats['duplicate_skipped_count'] += 1
            logger.info('SkillQuestion rejected skill_id=%s reason=%s question=%s', skill.id, validation['reason'], _clean_string(item.get('question_text'))[:120])
            continue
        if validation['question_hash'] in seen_hashes or _is_near_duplicate(validation['normalized'], seen_normalized) or _is_family_duplicate(validation['family_key'], validation['normalized'], seen_family_texts):
            stats['duplicate_skipped_count'] += 1
            logger.info('Duplicate SkillQuestion skipped skill_id=%s family_key=%s question=%s', skill.id, validation['family_key'], validation['question_text'][:120])
            continue
        try:
            with transaction.atomic():
                SkillQuestion.objects.create(
                    skill=skill,
                    question_text=validation['question_text'][:4000],
                    question_hash=validation['question_hash'],
                    difficulty=_choice(item.get('difficulty'), SkillQuestion.Difficulty.values, SkillQuestion.Difficulty.INTERMEDIATE),
                    question_type=validation['question_type'],
                    family_key=validation['family_key'][:120],
                    coverage_area=validation['coverage_area'][:80],
                    expected_signal=validation['expected_signal'][:2000],
                    ideal_answer_points=_json_list(item.get('ideal_answer_points')),
                    evaluation_rubric=item.get('evaluation_rubric') if isinstance(item.get('evaluation_rubric'), dict) else {},
                    tags=_json_list(item.get('tags'))[:12],
                    source=SkillQuestion.Source.OPENAI,
                    quality_status=SkillQuestion.QualityStatus.APPROVED,
                    is_active=True,
                )
            seen_normalized.add(validation['normalized'])
            seen_hashes.add(validation['question_hash'])
            seen_family_texts.append((validation['family_key'], validation['normalized']))
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
        'required': ['question_text', 'difficulty', 'question_type', 'family_key', 'coverage_area', 'expected_signal', 'ideal_answer_points', 'evaluation_rubric', 'tags'],
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
    test_case_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'input': {'type': 'string'},
            'expected_output': {'type': 'string'},
            'explanation': {'type': 'string'},
        },
        'required': ['input', 'expected_output', 'explanation'],
    }
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
            'starter_code': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'language': {'type': 'string'},
                    'code': {'type': 'string'},
                },
                'required': ['language', 'code'],
            },
            'test_cases': {'type': 'array', 'items': test_case_schema},
            'hidden_test_cases': {'type': 'array', 'items': test_case_schema},
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
    if skill.key in GENERIC_TECHNICAL_ROLE_SKIP_SKILL_KEYS or skill.key in NON_CODING_TARGET_SKILL_KEYS:
        return False
    category = (skill.category or '').strip().lower()
    category_parts = {
        part.strip()
        for part in re.split(r'[/,|]+', category)
        if part.strip()
    }
    return (
        category in TECHNICAL_CODING_CATEGORIES
        or bool(category_parts & TECHNICAL_CODING_CATEGORIES)
        or skill.key in TECHNICAL_CODING_SKILL_KEYS
    )


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
