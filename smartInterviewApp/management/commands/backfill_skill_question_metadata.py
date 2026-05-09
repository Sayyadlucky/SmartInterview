from __future__ import annotations

import json
import re
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.models import Interview, JobInterviewBlueprint, JobInterviewSkill, SkillQuestion


AREA_RULES = {
    'technical_concepts': {
        'core_principles': ['principle', 'concept', 'fundamental', 'basic', 'core idea'],
        'design_tradeoffs': ['tradeoff', 'design', 'architecture', 'approach', 'decision'],
        'abstraction_modeling': ['abstraction', 'model', 'interface', 'contract', 'encapsulation'],
        'implementation_practices': ['implement', 'code', 'class', 'method', 'function', 'module'],
        'maintainability_quality': ['maintain', 'readable', 'quality', 'refactor', 'clean', 'solid'],
        'testing_debugging': ['test', 'debug', 'bug', 'failure', 'fix', 'verify'],
    },
    'programming_language': {
        'core_language_data_structures': ['list', 'dict', 'dictionary', 'array', 'map', 'set', 'tuple', 'data structure', 'collection', 'string'],
        'oop_or_design': ['class', 'object', 'inheritance', 'polymorphism', 'interface', 'abstract', 'design pattern', 'solid'],
        'exception_handling': ['exception', 'error handling', 'try', 'catch', 'finally', 'raise', 'throw'],
        'functions_decorators_generators': ['function', 'decorator', 'generator', 'lambda', 'closure', 'iterator', 'callback'],
        'testing_debugging': ['test', 'unit test', 'debug', 'bug', 'traceback', 'pytest', 'jest', 'fix'],
        'performance_code_quality': ['performance', 'optimize', 'complexity', 'memory', 'refactor', 'clean code', 'quality'],
        'concurrency_runtime': ['thread', 'async', 'await', 'concurrency', 'parallel', 'runtime', 'event loop', 'garbage collection'],
    },
    'node_backend': {
        'async_event_loop': ['async', 'await', 'promise', 'callback', 'event loop', 'non-blocking', 'stream'],
        'api_routing': ['route', 'routing', 'endpoint', 'controller', 'express', 'request', 'response'],
        'middleware_auth': ['middleware', 'auth', 'authentication', 'authorization', 'jwt', 'token', 'session'],
        'database_integration': ['database', 'mongo', 'mysql', 'postgres', 'query', 'orm', 'schema'],
        'error_handling': ['error', 'exception', 'try', 'catch', 'failure', 'fallback'],
        'logging_monitoring': ['log', 'logging', 'monitor', 'metrics', 'observability', 'alert'],
        'performance_scalability': ['performance', 'scale', 'scalability', 'load', 'cache', 'throughput'],
        'testing_debugging': ['test', 'unit test', 'integration test', 'debug', 'bug', 'mock'],
    },
    'react_frontend': {
        'component_architecture': ['component', 'props', 'composition', 'architecture', 'container', 'presentational'],
        'state_management': ['state', 'redux', 'context', 'store', 'reducer', 'zustand'],
        'hooks_lifecycle': ['hook', 'useeffect', 'usestate', 'lifecycle', 'memo', 'ref'],
        'api_integration': ['api', 'fetch', 'axios', 'http', 'request', 'response', 'integration'],
        'forms_validation': ['form', 'input', 'validation', 'field', 'submit'],
        'performance_rendering': ['render', 'rerender', 'performance', 'memo', 'virtual', 'lazy', 'bundle'],
        'testing_debugging': ['test', 'jest', 'rtl', 'debug', 'bug', 'testing library'],
    },
    'database': {
        'queries_joins_aggregation': ['query', 'join', 'aggregate', 'group by', 'select', 'where', 'pipeline'],
        'schema_design': ['schema', 'table', 'model', 'relationship', 'normalization', 'document design'],
        'indexing_performance': ['index', 'performance', 'optimize', 'slow query', 'explain', 'latency'],
        'transactions_constraints': ['transaction', 'constraint', 'acid', 'lock', 'foreign key', 'unique'],
        'query_debugging': ['debug', 'bug', 'incorrect result', 'deadlock', 'timeout'],
    },
    'rest_api': {
        'http_methods_status_codes': ['http', 'method', 'get', 'post', 'put', 'patch', 'delete', 'status code'],
        'endpoint_design': ['endpoint', 'resource', 'route', 'uri', 'url', 'restful', 'design'],
        'auth_security': ['auth', 'authentication', 'authorization', 'jwt', 'oauth', 'security', 'token'],
        'validation_error_handling': ['validation', 'error', 'bad request', 'exception', 'invalid', '400'],
        'pagination_filtering': ['pagination', 'filter', 'sorting', 'page', 'limit', 'offset', 'cursor'],
        'api_testing_debugging': ['test', 'postman', 'debug', 'contract', 'integration test', 'mock'],
    },
}

GENERIC_PATTERNS = [
    r'\btell me about yourself\b',
    r'\bwhy should we hire\b',
    r'\bstrengths? and weaknesses?\b',
    r'\bwhere do you see yourself\b',
    r'\bdescribe yourself\b',
    r'\bgood communication\b',
]


class Command(BaseCommand):
    help = 'Deterministically backfill SkillQuestion quality metadata for an interview question bank.'

    def add_arguments(self, parser):
        parser.add_argument('--interview-id', type=int, required=True)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--apply', action='store_true')
        parser.add_argument('--only-empty', action='store_true')
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        interview_id = options['interview_id']
        apply_changes = bool(options['apply'])
        only_empty = bool(options['only_empty'])
        force = bool(options['force'])

        interview = Interview.objects.select_related('role').filter(id=interview_id).first()
        if not interview:
            raise CommandError(f'Interview not found: {interview_id}')
        job = interview.role
        if not job:
            raise CommandError(f'Interview {interview_id} has no related job.')
        blueprint = JobInterviewBlueprint.objects.filter(job=job).first()
        if not blueprint:
            raise CommandError(f'No JobInterviewBlueprint found for interview {interview_id}.')

        plans = list(
            JobInterviewSkill.objects
            .select_related('skill')
            .filter(
                blueprint=blueprint,
                is_active=True,
                skill__is_active=True,
                skill_role__in=[
                    JobInterviewSkill.SkillRole.PRIMARY,
                    JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE,
                    JobInterviewSkill.SkillRole.SUB_SKILL,
                ],
            )
            .order_by('priority', 'id')
        )

        scanned_count = 0
        updated_count = 0
        skipped_count = 0
        status_changes_count = 0
        downgraded_count = 0
        unclassified_coverage_count = 0
        approved_with_empty_coverage_count_before = 0
        approved_with_empty_coverage_count_after = 0
        before_counts = Counter()
        after_counts = Counter()
        per_skill = []

        for plan in plans:
            result = self._process_skill(plan, job, apply_changes, only_empty, force)
            scanned_count += result['scanned_count']
            updated_count += result['updated_count']
            skipped_count += result['skipped_count']
            status_changes_count += result['status_changes_count']
            downgraded_count += result['downgraded_count']
            unclassified_coverage_count += result['unclassified_coverage_count']
            approved_with_empty_coverage_count_before += result['approved_with_empty_coverage_count_before']
            approved_with_empty_coverage_count_after += result['approved_with_empty_coverage_count_after']
            before_counts.update(result['coverage_counts_before'])
            after_counts.update(result['coverage_counts_after'])
            per_skill.append(result)

        self.stdout.write(f'mode={"apply" if apply_changes else "dry-run"}')
        self.stdout.write(f'interview_id={interview.id}')
        self.stdout.write(f'role={job.role or job.position or ""}')
        self.stdout.write(f'only_empty={only_empty}')
        self.stdout.write(f'force={force}')
        self.stdout.write(f'scanned_count={scanned_count}')
        self.stdout.write(f'updated_count={updated_count}')
        self.stdout.write(f'skipped_count={skipped_count}')
        self.stdout.write(f'status_changes_count={status_changes_count}')
        self.stdout.write(f'downgraded_count={downgraded_count}')
        self.stdout.write(f'unclassified_coverage_count={unclassified_coverage_count}')
        self.stdout.write(f'approved_with_empty_coverage_count={approved_with_empty_coverage_count_after}')
        self.stdout.write(f'approved_with_empty_coverage_count_before={approved_with_empty_coverage_count_before}')
        self.stdout.write(f'approved_with_empty_coverage_count_after={approved_with_empty_coverage_count_after}')
        self.stdout.write(f'coverage_counts_before={self._json_counter(before_counts)}')
        self.stdout.write(f'coverage_counts_after={self._json_counter(after_counts)}')
        self.stdout.write(f'missing_required_coverage_areas_before={self._missing_required_json(per_skill, "before")}')
        self.stdout.write(f'missing_required_coverage_areas_after={self._missing_required_json(per_skill, "after")}')
        self.stdout.write('per_skill_summary:')
        for item in per_skill:
            self.stdout.write(json.dumps({
                'skill': item['skill'],
                'skill_role': item['skill_role'],
                'scanned_count': item['scanned_count'],
                'updated_count': item['updated_count'],
                'skipped_count': item['skipped_count'],
                'status_changes_count': item['status_changes_count'],
                'downgraded_count': item['downgraded_count'],
                'unclassified_coverage_count': item['unclassified_coverage_count'],
                'approved_count_before': item['approved_count_before'],
                'approved_count_after': item['approved_count_after'],
                'approved_with_empty_coverage_count_before': item['approved_with_empty_coverage_count_before'],
                'approved_with_empty_coverage_count_after': item['approved_with_empty_coverage_count_after'],
                'coverage_counts_before': item['coverage_counts_before'],
                'coverage_counts_after': item['coverage_counts_after'],
                'missing_required_coverage_areas_before': item['missing_required_coverage_areas_before'],
                'missing_required_coverage_areas_after': item['missing_required_coverage_areas_after'],
                'planned_changes': item['planned_changes'][:20],
            }, sort_keys=True))
        if not apply_changes:
            self.stdout.write('dry_run_no_db_writes=true')

    def _process_skill(self, plan, job, apply_changes, only_empty, force):
        questions = list(
            SkillQuestion.objects
            .filter(skill=plan.skill, is_active=True)
            .order_by('id')
        )
        before_counts = Counter(question.coverage_area for question in questions if question.coverage_area)
        after_counts = Counter(before_counts)
        required_areas = required_coverage_areas(plan.skill)
        planned_changes = []
        updated_count = 0
        skipped_count = 0
        status_changes_count = 0
        downgraded_count = 0
        approved_count_before = sum(1 for question in questions if question.quality_status == SkillQuestion.QualityStatus.APPROVED)
        approved_count_after = approved_count_before
        approved_with_empty_coverage_count_before = sum(
            1 for question in questions
            if question.quality_status == SkillQuestion.QualityStatus.APPROVED and not question.coverage_area
        )
        approved_with_empty_coverage_count_after = approved_with_empty_coverage_count_before
        unclassified_coverage_count = 0

        for question in questions:
            proposal = classify_question_metadata(plan.skill, question, job)
            changes = proposed_changes(question, proposal, only_empty, force)
            if 'cannot_classify_coverage_area' in proposal['reason']:
                unclassified_coverage_count += 1
            if not changes:
                skipped_count += 1
                continue
            old_status = question.quality_status
            new_status = changes.get('quality_status', old_status)
            status_changed = new_status != old_status
            downgraded = is_status_downgrade(old_status, new_status)
            if status_changed:
                status_changes_count += 1
                if old_status == SkillQuestion.QualityStatus.APPROVED:
                    approved_count_after -= 1
                if new_status == SkillQuestion.QualityStatus.APPROVED:
                    approved_count_after += 1
            old_area = question.coverage_area
            new_area = changes.get('coverage_area', old_area)
            if (
                old_status == SkillQuestion.QualityStatus.APPROVED
                and not old_area
                and (new_status != SkillQuestion.QualityStatus.APPROVED or new_area)
            ):
                approved_with_empty_coverage_count_after -= 1
            if (
                not (old_status == SkillQuestion.QualityStatus.APPROVED and not old_area)
                and new_status == SkillQuestion.QualityStatus.APPROVED
                and not new_area
            ):
                approved_with_empty_coverage_count_after += 1
            if downgraded:
                downgraded_count += 1
            updated_count += 1
            planned_changes.append({
                'question_id': question.id,
                'changes': changes,
                'current_quality_status': question.quality_status,
                'final_quality_status': new_status,
                'status_changed': status_changed,
                'reason': proposal['reason'],
            })
            if new_area != old_area:
                if old_area:
                    after_counts[old_area] -= 1
                    if after_counts[old_area] <= 0:
                        del after_counts[old_area]
                if new_area:
                    after_counts[new_area] += 1
            if apply_changes:
                for field, value in changes.items():
                    setattr(question, field, value)
                question.save(update_fields=[*changes.keys(), 'updated_at'])

        return {
            'skill': plan.skill.name,
            'skill_role': plan.skill_role,
            'scanned_count': len(questions),
            'updated_count': updated_count,
            'skipped_count': skipped_count,
            'status_changes_count': status_changes_count,
            'downgraded_count': downgraded_count,
            'unclassified_coverage_count': unclassified_coverage_count,
            'approved_count_before': approved_count_before,
            'approved_count_after': approved_count_after,
            'approved_with_empty_coverage_count_before': approved_with_empty_coverage_count_before,
            'approved_with_empty_coverage_count_after': approved_with_empty_coverage_count_after,
            'coverage_counts_before': dict(sorted(before_counts.items())),
            'coverage_counts_after': dict(sorted(after_counts.items())),
            'missing_required_coverage_areas_before': sorted(set(required_areas) - set(before_counts)),
            'missing_required_coverage_areas_after': sorted(set(required_areas) - set(after_counts)),
            'planned_changes': planned_changes,
        }

    def _json_counter(self, counter):
        return json.dumps(dict(sorted((key, value) for key, value in counter.items() if value > 0)), sort_keys=True)

    def _missing_required_json(self, per_skill, key):
        payload = {
            item['skill']: item[f'missing_required_coverage_areas_{key}']
            for item in per_skill
            if item[f'missing_required_coverage_areas_{key}']
        }
        return json.dumps(payload, sort_keys=True)


def classify_question_metadata(skill, question, job):
    text = normalize_text(' '.join([
        skill.name,
        question.question_text or '',
        question.family_key or '',
        question.question_type or '',
        question.expected_signal or '',
    ]))
    coverage_area = classify_coverage_area(skill, text)
    reason = []
    if not clean(question.question_text):
        status = SkillQuestion.QualityStatus.REJECTED
        reason.append('empty_question_text')
    elif is_broken_question(question.question_text):
        status = SkillQuestion.QualityStatus.REJECTED
        reason.append('broken_question_text')
    else:
        if not clean(question.expected_signal):
            reason.append('missing_expected_signal')
        if not clean(question.family_key):
            reason.append('missing_family_key')
        if is_generic_question(text):
            reason.append('too_generic')
        if not coverage_area:
            reason.append('cannot_classify_coverage_area')
        status = SkillQuestion.QualityStatus.NEEDS_REVIEW if reason else SkillQuestion.QualityStatus.APPROVED

    quality_score = quality_score_for_status(status, reason, question)
    jd_relevance_score = jd_relevance_score_for_question(job, skill, question)
    return {
        'coverage_area': coverage_area,
        'quality_status': status,
        'quality_score': quality_score,
        'jd_relevance_score': jd_relevance_score,
        'quality_notes': quality_notes_for_proposal(reason),
        'reason': reason or ['usable'],
    }


def quality_notes_for_proposal(reason):
    notes = {
            'backfill_source': 'backfill_skill_question_metadata',
            'classification_version': 1,
            'reason': reason or ['usable'],
            'deterministic': True,
    }
    if 'cannot_classify_coverage_area' in reason:
        notes['unclassified_coverage_area'] = True
    return notes


def proposed_changes(question, proposal, only_empty, force):
    changes = {}
    if should_update_text_field(question.coverage_area, only_empty):
        if proposal['coverage_area']:
            changes['coverage_area'] = proposal['coverage_area']
    proposed_status = safe_quality_status(question, proposal, force)
    if should_update_quality_status(question, proposed_status, proposal, only_empty, force):
        changes['quality_status'] = proposed_status
    proposed_quality_score = safe_quality_score_for_status(proposed_status, proposal['quality_score'], question)
    if should_update_number_field(question.quality_score, only_empty) or score_out_of_range(question.quality_score):
        changes['quality_score'] = proposed_quality_score
    if should_update_number_field(question.jd_relevance_score, only_empty) or score_out_of_range(question.jd_relevance_score):
        changes['jd_relevance_score'] = proposal['jd_relevance_score']
    if should_update_json_field(question.quality_notes, only_empty, force) or should_note_classification_failure(question, proposal, force):
        changes['quality_notes'] = proposal['quality_notes']
    return changes


def safe_quality_score_for_status(status, proposed_score, question):
    score = clamp_score(proposed_score)
    if status == SkillQuestion.QualityStatus.APPROVED:
        existing = clamp_score(question.quality_score)
        score = max(score, existing, 0.70)
    return round(score, 2)


def should_update_text_field(value, only_empty):
    return True if not only_empty else not clean(value)


def should_update_number_field(value, only_empty):
    return True if not only_empty else float(value or 0) == 0


def should_update_json_field(value, only_empty, force):
    if force:
        return True
    return True if not only_empty else not value


def should_update_quality_status(question, proposed_status, proposal, only_empty, force):
    current_status = clean(question.quality_status)
    if current_status == proposed_status:
        return False
    if is_status_downgrade(current_status, proposed_status) and not force:
        return False
    if 'cannot_classify_coverage_area' in proposal['reason'] and proposed_status == SkillQuestion.QualityStatus.NEEDS_REVIEW:
        return force or current_status in {'', SkillQuestion.QualityStatus.PENDING}
    if not only_empty:
        return True
    if proposed_status == SkillQuestion.QualityStatus.APPROVED and current_status in {
        '',
        SkillQuestion.QualityStatus.PENDING,
        SkillQuestion.QualityStatus.NEEDS_REVIEW,
    }:
        return True
    metadata_is_default = (
        not question.quality_notes
        and float(question.quality_score or 0) == 0
        and float(question.jd_relevance_score or 0) == 0
    )
    return current_status in {'', SkillQuestion.QualityStatus.PENDING} or metadata_is_default


def safe_quality_status(question, proposal, force):
    proposed_status = proposal['quality_status']
    if (
        not force
        and question.quality_status == SkillQuestion.QualityStatus.APPROVED
        and is_status_downgrade(question.quality_status, proposed_status)
    ):
        return SkillQuestion.QualityStatus.APPROVED
    if (
        not force
        and is_curated_status(question)
        and clean(question.quality_status)
        and clean(question.quality_status) != SkillQuestion.QualityStatus.PENDING
    ):
        return question.quality_status
    return proposed_status


def is_status_downgrade(old_status, new_status):
    rank = {
        '': 0,
        SkillQuestion.QualityStatus.PENDING: 1,
        SkillQuestion.QualityStatus.REJECTED: 1,
        SkillQuestion.QualityStatus.NEEDS_REVIEW: 2,
        SkillQuestion.QualityStatus.APPROVED: 3,
    }
    return rank.get(clean(new_status), 0) < rank.get(clean(old_status), 0)


def score_out_of_range(value):
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return True
    return parsed < 0 or parsed > 1


def clamp_score(value):
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, min(1.0, parsed))


def is_curated_status(question):
    notes = question.quality_notes if isinstance(question.quality_notes, dict) else {}
    return bool(notes) and notes.get('backfill_source') != 'backfill_skill_question_metadata'


def should_note_classification_failure(question, proposal, force):
    if 'cannot_classify_coverage_area' not in proposal['reason']:
        return False
    if force:
        return True
    notes = question.quality_notes if isinstance(question.quality_notes, dict) else {}
    return not notes or notes.get('backfill_source') == 'backfill_skill_question_metadata'


def classify_coverage_area(skill, text):
    group = coverage_group_for_skill(skill)
    if not group:
        group = 'technical_concepts'
    rules = AREA_RULES[group]
    for area, keywords in rules.items():
        if any(keyword in text for keyword in keywords):
            return area
    if 'debug' in text or 'bug' in text or 'fix' in text:
        for fallback in ['testing_debugging', 'query_debugging', 'api_testing_debugging']:
            if fallback in rules:
                return fallback
    if group == 'technical_concepts':
        return 'core_principles'
    return ''


def coverage_group_for_skill(skill):
    key = skill.key or ''
    name = (skill.name or '').lower()
    category = (skill.category or '').lower()
    if key == 'rest-api' or 'rest api' in name or 'api' == name.strip():
        return 'rest_api'
    if category == 'database' or key in {'sql', 'mysql', 'postgresql', 'mongodb'}:
        return 'database'
    if key in {'react', 'next-js', 'angular', 'html-css'} or category == 'frontend development':
        return 'react_frontend'
    if key in {'node-js', 'django', 'django-rest-framework', 'spring-boot'} or category == 'backend development':
        return 'node_backend'
    if category == 'programming language' or key in {'python', 'javascript', 'core-java', 'php', 'apex'}:
        return 'programming_language'
    if any(term in category for term in ['programming', 'software', 'technical', 'backend', 'frontend', 'framework']):
        return 'technical_concepts'
    if any(term in name for term in ['concept', 'principle', 'design', 'architecture', 'pattern', 'object']):
        return 'technical_concepts'
    return ''


def required_coverage_areas(skill):
    group = coverage_group_for_skill(skill)
    return list(AREA_RULES.get(group, {}).keys())


def quality_score_for_status(status, reason, question):
    if status == SkillQuestion.QualityStatus.REJECTED:
        return 0.0
    if status == SkillQuestion.QualityStatus.NEEDS_REVIEW:
        return 0.45 if 'cannot_classify_coverage_area' in reason else 0.55
    score = 0.78
    if question.question_type in {
        SkillQuestion.QuestionType.SCENARIO,
        SkillQuestion.QuestionType.DEBUGGING,
        SkillQuestion.QuestionType.PRACTICAL,
    }:
        score += 0.08
    if len(clean(question.expected_signal)) >= 80:
        score += 0.06
    return round(min(score, 0.95), 2)


def jd_relevance_score_for_question(job, skill, question):
    jd_text = normalize_text(' '.join([
        getattr(job, 'role', '') or '',
        getattr(job, 'position', '') or '',
        getattr(job, 'description', '') or '',
        getattr(job, 'experience_required', '') or '',
    ]))
    question_text = normalize_text(' '.join([
        skill.name or '',
        question.question_text or '',
        question.family_key or '',
        question.expected_signal or '',
    ]))
    skill_terms = [normalize_text(skill.name), normalize_text((skill.key or '').replace('-', ' '))]
    skill_match = any(term.strip() and term in jd_text for term in skill_terms)
    jd_tokens = {token for token in jd_text.split() if len(token) > 3}
    question_tokens = {token for token in question_text.split() if len(token) > 3}
    overlap = len(jd_tokens & question_tokens)
    score = 0.62 + min(overlap, 8) * 0.03
    if skill_match:
        score += 0.12
    return round(min(score, 0.95), 2)


def is_generic_question(text):
    return any(re.search(pattern, text) for pattern in GENERIC_PATTERNS)


def is_broken_question(value):
    text = clean(value).lower()
    return len(text) < 10 or text in {'n/a', 'na', 'none', 'test', 'todo', 'placeholder'}


def normalize_text(value):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9+#.]+', ' ', (value or '').lower())).strip()


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()
