from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json
import logging
import socket
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from smartInterviewApp.models import (
    AptitudeQuestionBank,
    AptitudeQuestionGenerationJob,
    AptitudeSection,
)
from smartInterviewApp.services.aptitude_question_schemas import validate_question_payload


logger = logging.getLogger(__name__)

DEFAULT_APTITUDE_SECTION_CODES = [
    'quantitative_aptitude',
    'logical_reasoning',
    'verbal_reasoning',
    'verbal_ability',
    'non_verbal_reasoning',
    'english_vocabulary',
    'technical_mcq',
]

COUNTED_QUALITY_STATUSES = [
    AptitudeQuestionBank.QualityStatus.DRAFT,
    AptitudeQuestionBank.QualityStatus.APPROVED,
    AptitudeQuestionBank.QualityStatus.NEEDS_REVIEW,
]

MAX_TARGET_COUNT = 500
MAX_BATCH_SIZE = 50


def build_aptitude_generation_prompt(
    *,
    section,
    role_family='',
    skill_tag='',
    topic_tag='',
    batch_size=20,
    difficulty_mix=None,
    question_types=None,
    existing_question_texts=None,
):
    difficulty_mix = difficulty_mix or {'easy': 0.3, 'medium': 0.5, 'hard': 0.2}
    question_types = question_types or [AptitudeQuestionBank.QuestionType.SINGLE_CHOICE]
    existing_question_texts = list(existing_question_texts or [])[:50]
    section_description = (getattr(section, 'description', '') or '').strip()

    return (
        'Generate original aptitude question-bank items for SmartInterview / Shortlistii.\n'
        'Return strict JSON only. Do not wrap the response in Markdown.\n\n'
        'Required JSON shape:\n'
        '{"questions": ['
        '{"section_code": "...", "question_text": "...", "question_type": "...", '
        '"difficulty": "easy|medium|hard", "options": [], "answer_schema": {}, '
        '"scoring_schema": {}, "explanation": "...", "skill_tag": "...", '
        '"topic_tag": "...", "role_family": "...", "question_media": []}'
        ']}\n\n'
        f'Section code: {section.code}\n'
        f'Section name: {section.name}\n'
        f'Section description: {section_description}\n'
        f'Role family: {role_family or "general"}\n'
        f'Skill tag: {skill_tag or ""}\n'
        f'Topic tag: {topic_tag or ""}\n'
        f'Batch size: {int(batch_size)}\n'
        f'Difficulty mix target: {json.dumps(difficulty_mix, sort_keys=True)}\n'
        f'Allowed question types: {json.dumps(question_types)}\n'
        f'Existing questions to avoid: {json.dumps(existing_question_texts)}\n\n'
        'Compatibility rules:\n'
        '- Use only question types supported by the allowed list.\n'
        '- For single_choice, multiple_choice, true_false, and image_choice, options must be objects with stable keys such as A, B, C, D.\n'
        '- answer_schema must match the question type: correct_key, correct_keys, value, accepted_values, pairs, or correct_order as appropriate.\n'
        '- scoring_schema should include partial_credit and normalize_text booleans when relevant.\n'
        '- marks must be omitted or set to 2. negative_marks must be omitted or set to 0.\n'
        '- question_media must be an array. Use [] unless a diagram placeholder is needed.\n\n'
        'Quality and safety rules:\n'
        '- Create original questions only. Do not copy copyrighted content or real exam questions.\n'
        '- Avoid ambiguous wording and ensure exactly one defensible answer unless the question type requires multiple answers.\n'
        '- Never include explanations that contradict the answer key.\n'
        '- Never write "Correction", "adjust answer key", "closest", or "approximate answer" in the explanation.\n'
        '- For single-choice aptitude, the correct option must be exactly correct and the exact answer must be present in options.\n'
        '- For quantitative questions, compute internally and ensure the answer key matches the exact option.\n'
        '- Avoid cultural, political, religious, medical, legal, financial, or otherwise sensitive content.\n'
        '- Keep language professional, workplace-friendly, concise, and suitable for hiring assessments.\n'
        '- Do not include external image URLs. For non-verbal reasoning, represent diagrams using concise ASCII/text pattern descriptions or question_media placeholders like '
        '{"type": "diagram_placeholder", "description": "...", "position": "below_question"}.\n'
    )


def parse_openai_questions_response(raw_text):
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError('OpenAI response is empty.')

    json_text = _extract_json_text(raw_text)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError('OpenAI response did not contain valid JSON.') from exc

    if isinstance(payload, dict):
        questions = payload.get('questions')
    elif isinstance(payload, list):
        questions = payload
    else:
        questions = None

    if not isinstance(questions, list):
        raise ValueError('OpenAI response JSON must be a questions object or list.')
    return questions


def validate_generated_question_payload(section, item):
    if not isinstance(item, dict):
        raise ValueError('Generated question must be an object.')

    section_code = str(item.get('section_code') or item.get('section') or '').strip()
    if section_code and section_code != section.code:
        raise ValueError(f'Generated question section {section_code} does not match {section.code}.')

    required_fields = [
        'question_text',
        'question_type',
        'difficulty',
        'options',
        'answer_schema',
        'scoring_schema',
        'explanation',
        'skill_tag',
        'topic_tag',
        'role_family',
        'question_media',
    ]
    missing_fields = [field for field in required_fields if field not in item]
    if missing_fields:
        raise ValueError(f'Generated question is missing required fields: {", ".join(missing_fields)}.')

    question_text = _clean_text(item.get('question_text'))
    if not question_text:
        raise ValueError('Generated question_text is required.')

    question_type = _clean_text(item.get('question_type'))
    supported_question_types = {choice[0] for choice in AptitudeQuestionBank.QuestionType.choices}
    if question_type not in supported_question_types:
        raise ValueError(f'Unsupported aptitude question_type: {question_type}.')

    difficulty = _clean_text(item.get('difficulty')) or AptitudeQuestionBank.Difficulty.MEDIUM
    supported_difficulties = {choice[0] for choice in AptitudeQuestionBank.Difficulty.choices}
    if difficulty not in supported_difficulties:
        raise ValueError(f'Unsupported aptitude difficulty: {difficulty}.')

    options = item.get('options') or []
    raw_answer_schema = item.get('answer_schema') or {}
    scoring_schema = item.get('scoring_schema') or {}
    question_media = item.get('question_media') or []

    if not isinstance(options, list):
        raise ValueError('Generated options must be a list.')
    if not isinstance(raw_answer_schema, dict):
        raise ValueError('Generated answer_schema must be an object.')
    if not isinstance(scoring_schema, dict):
        raise ValueError('Generated scoring_schema must be an object.')
    if not isinstance(question_media, list):
        raise ValueError('Generated question_media must be a list.')

    try:
        answer_schema = normalize_generated_answer_schema(question_type, raw_answer_schema)
    except ValueError as exc:
        raise ValueError(f'Generated answer_schema cannot be normalized: {exc}') from exc

    quality_item = {**item, 'question_type': question_type, 'options': options, 'answer_schema': answer_schema}
    quality_issues = detect_generated_question_quality_issues(quality_item)
    schema_errors = validate_question_payload(question_type, options, answer_schema)
    errors = [*quality_issues, *schema_errors]
    if errors:
        raise ValueError('; '.join(errors))

    return {
        'section_code': section.code,
        'question_text': question_text,
        'question_html': _clean_text(item.get('question_html')),
        'question_type': question_type,
        'difficulty': difficulty,
        'options': options,
        'answer_schema': answer_schema,
        'scoring_schema': scoring_schema,
        'explanation': _clean_text(item.get('explanation')),
        'skill_tag': _clean_text(item.get('skill_tag')),
        'topic_tag': _clean_text(item.get('topic_tag')),
        'role_family': _clean_text(item.get('role_family')),
        'question_media': question_media,
        'marks': Decimal('2'),
        'negative_marks': Decimal('0'),
    }


def normalize_generated_answer_schema(question_type, answer_schema):
    if not isinstance(answer_schema, dict):
        raise ValueError('answer_schema must be an object.')

    question_type = _clean_text(question_type)
    if question_type in {
        AptitudeQuestionBank.QuestionType.SINGLE_CHOICE,
        AptitudeQuestionBank.QuestionType.IMAGE_CHOICE,
    }:
        correct_keys = _schema_string_list(answer_schema.get('correct_keys'))
        correct_key = _clean_text(answer_schema.get('correct_key'))
        if correct_key:
            correct_keys = [correct_key]
        if len(correct_keys) != 1:
            raise ValueError('single choice answer_schema must contain exactly one correct key.')
        return {'correct_keys': correct_keys}

    if question_type == AptitudeQuestionBank.QuestionType.MULTIPLE_CHOICE:
        correct_keys = _schema_string_list(answer_schema.get('correct_keys'))
        if not correct_keys:
            raise ValueError('multiple_choice answer_schema must contain correct_keys.')
        return {'correct_keys': correct_keys}

    if question_type == AptitudeQuestionBank.QuestionType.TRUE_FALSE:
        if 'value' not in answer_schema:
            raise ValueError('true_false answer_schema must contain value.')
        return {'value': bool(answer_schema.get('value'))}

    if question_type == AptitudeQuestionBank.QuestionType.NUMERIC:
        if 'value' not in answer_schema:
            raise ValueError('numeric answer_schema must contain value.')
        return {
            'value': answer_schema.get('value'),
            'tolerance': answer_schema.get('tolerance') or 0,
        }

    if question_type in {
        AptitudeQuestionBank.QuestionType.TEXT_INPUT,
        AptitudeQuestionBank.QuestionType.FILL_BLANK,
    }:
        accepted_values = _schema_string_list(answer_schema.get('accepted_values'))
        if not accepted_values:
            raise ValueError(f'{question_type} answer_schema must contain accepted_values.')
        return {
            'accepted_values': accepted_values,
            'case_sensitive': bool(answer_schema.get('case_sensitive', False)),
            'trim_spaces': bool(answer_schema.get('trim_spaces', True)),
        }

    if question_type == AptitudeQuestionBank.QuestionType.MATCHING:
        pairs = answer_schema.get('pairs')
        if not isinstance(pairs, dict) or not pairs:
            raise ValueError('matching answer_schema must contain pairs.')
        return {'pairs': pairs}

    if question_type == AptitudeQuestionBank.QuestionType.ORDERING:
        correct_order = _schema_string_list(answer_schema.get('correct_order'))
        if not correct_order:
            raise ValueError('ordering answer_schema must contain correct_order.')
        return {'correct_order': correct_order}

    raise ValueError(f'Unsupported question_type: {question_type}.')


def detect_generated_question_quality_issues(item):
    issues = []
    if not isinstance(item, dict):
        return ['Generated question must be an object.']

    question_type = _clean_text(item.get('question_type'))
    question_text = _clean_text(item.get('question_text'))
    explanation = _clean_text(item.get('explanation'))
    answer_schema = item.get('answer_schema') or {}
    options = item.get('options') or []

    if len(question_text) < 12:
        issues.append('Generated question_text is too short.')
    if len(explanation) < 12:
        issues.append('Generated explanation is too short.')

    try:
        normalized_schema = normalize_generated_answer_schema(question_type, answer_schema)
    except ValueError as exc:
        issues.append(f'Generated answer_schema cannot be normalized: {exc}')
        normalized_schema = {}

    option_keys = []
    option_labels = []
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            issues.append(f'Option {index + 1} must be an object.')
            continue
        key = _clean_text(option.get('key'))
        label = _clean_text(option.get('label'))
        if key:
            option_keys.append(key)
        if question_type != AptitudeQuestionBank.QuestionType.IMAGE_CHOICE and not label:
            issues.append(f'Option {key or index + 1} label is empty.')
        if label:
            option_labels.append(label.casefold())

    if len(option_labels) != len(set(option_labels)):
        issues.append('Generated options contain duplicate labels.')

    if question_type in {
        AptitudeQuestionBank.QuestionType.SINGLE_CHOICE,
        AptitudeQuestionBank.QuestionType.IMAGE_CHOICE,
    }:
        correct_keys = normalized_schema.get('correct_keys') or []
        if not correct_keys:
            issues.append(f'{question_type} has no correct key.')
        elif len(correct_keys) > 1:
            issues.append(f'{question_type} has more than one correct key.')
        elif correct_keys[0] not in option_keys:
            issues.append(f'Correct key {correct_keys[0]} is not present in options.')

    if question_type == AptitudeQuestionBank.QuestionType.MULTIPLE_CHOICE:
        for correct_key in normalized_schema.get('correct_keys') or []:
            if correct_key not in option_keys:
                issues.append(f'Correct key {correct_key} is not present in options.')

    if question_type == AptitudeQuestionBank.QuestionType.SINGLE_CHOICE:
        lowered_explanation = explanation.casefold()
        suspicious_phrases = [
            'correction',
            'adjust answer key',
            'should be',
            'closest to',
            'closest option',
            'approximate answer',
            'but exact',
            'exact is',
        ]
        for phrase in suspicious_phrases:
            if phrase in lowered_explanation:
                issues.append(f'Generated explanation contains suspicious phrase: {phrase}.')
                break
        if 'approximate' in lowered_explanation and (
            item.get('section_code') == 'quantitative_aptitude'
            or _clean_text(item.get('skill_tag')).casefold() in {'quantitative', 'arithmetic', 'math', 'mathematics'}
        ):
            issues.append('Generated quantitative single-choice explanation uses an approximate answer.')

    return issues


def create_question_from_generated_item(
    section,
    item,
    *,
    role_family='',
    quality_status=AptitudeQuestionBank.QualityStatus.NEEDS_REVIEW,
    created_by=None,
):
    cleaned = validate_generated_question_payload(section, item)
    quality_status = quality_status or AptitudeQuestionBank.QualityStatus.NEEDS_REVIEW
    allowed_quality_statuses = {
        AptitudeQuestionBank.QualityStatus.DRAFT,
        AptitudeQuestionBank.QualityStatus.APPROVED,
        AptitudeQuestionBank.QualityStatus.NEEDS_REVIEW,
    }
    if quality_status not in allowed_quality_statuses:
        raise ValueError(f'Unsupported generated question quality_status: {quality_status}.')

    duplicate = _find_duplicate_question(section, cleaned['question_text'])
    if duplicate:
        return duplicate, False

    question = AptitudeQuestionBank.objects.create(
        section=section,
        question_type=cleaned['question_type'],
        role_family=_clean_text(role_family) or cleaned['role_family'],
        skill_tag=cleaned['skill_tag'],
        topic_tag=cleaned['topic_tag'],
        difficulty=cleaned['difficulty'],
        question_text=cleaned['question_text'],
        question_html=cleaned['question_html'],
        question_media=cleaned['question_media'],
        options=cleaned['options'],
        answer_schema=cleaned['answer_schema'],
        scoring_schema=cleaned['scoring_schema'],
        marks=Decimal('2'),
        negative_marks=Decimal('0'),
        explanation=cleaned['explanation'],
        quality_status=quality_status,
        is_active=True,
        created_by=created_by,
    )
    return question, True


def process_aptitude_generation_job(job_id):
    job = _claim_generation_job(job_id)
    if job.status in {
        AptitudeQuestionGenerationJob.Status.COMPLETED,
        AptitudeQuestionGenerationJob.Status.CANCELLED,
    }:
        return _job_result(job, processed=False, message='Job is already terminal.')

    before_count = _matching_question_queryset(job).count()
    if before_count >= int(job.target_count) or int(job.accepted_count) >= int(job.target_count):
        _mark_job_completed(
            job,
            {
                'message': 'Target question count already met.',
                'existing_count': before_count,
                'accepted_count': job.accepted_count,
            },
        )
        job.refresh_from_db()
        return _job_result(job, processed=True, message='Target question count already met.')

    remaining = max(0, int(job.target_count) - before_count)
    if remaining <= 0:
        _mark_job_completed(job, {'message': 'Target question count already met.', 'existing_count': before_count})
        job.refresh_from_db()
        return _job_result(job, processed=True, message='Target question count already met.')

    batch_size = min(max(1, int(job.batch_size)), remaining, MAX_BATCH_SIZE)
    prompt = build_aptitude_generation_prompt(
        section=job.section,
        role_family=job.role_family,
        skill_tag=job.skill_tag,
        topic_tag=job.topic_tag,
        batch_size=batch_size,
        difficulty_mix=job.difficulty_mix,
        question_types=job.question_types,
        existing_question_texts=list(
            _matching_question_queryset(job)
            .order_by('-updated_at')
            .values_list('question_text', flat=True)[:50]
        ),
    )

    try:
        raw_text = call_openai_for_aptitude_questions(prompt, model_name=job.model_name)
        generated_items = parse_openai_questions_response(raw_text)[:batch_size]
        accepted_count = 0
        rejected_count = 0
        created_count = 0
        rejection_errors = []

        for item in generated_items:
            try:
                item_for_save = dict(item)
                if job.role_family:
                    item_for_save['role_family'] = job.role_family
                if job.skill_tag:
                    item_for_save['skill_tag'] = job.skill_tag
                if job.topic_tag:
                    item_for_save['topic_tag'] = job.topic_tag
                question, created = create_question_from_generated_item(
                    job.section,
                    item_for_save,
                    role_family=job.role_family,
                    quality_status=job.quality_status_for_created,
                    created_by=job.created_by,
                )
                accepted_count += 1
                if created:
                    created_count += 1
                logger.info(
                    'Aptitude generated question accepted job_id=%s question_id=%s created=%s',
                    job.id,
                    question.id,
                    created,
                )
            except ValueError as exc:
                rejected_count += 1
                rejection_errors.append(str(exc)[:300])

        after_count = _matching_question_queryset(job).count()
        projected_accepted_count = int(job.accepted_count) + accepted_count
        status = (
            AptitudeQuestionGenerationJob.Status.COMPLETED
            if after_count >= int(job.target_count) or projected_accepted_count >= int(job.target_count)
            else AptitudeQuestionGenerationJob.Status.QUEUED
        )
        finished_at = timezone.now() if status == AptitudeQuestionGenerationJob.Status.COMPLETED else None
        _save_successful_batch(
            job,
            status=status,
            generated_count=len(generated_items),
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            created_count=created_count,
            before_count=before_count,
            after_count=after_count,
            batch_size=batch_size,
            rejection_errors=rejection_errors,
            finished_at=finished_at,
        )
        job.refresh_from_db()
        return _job_result(
            job,
            processed=True,
            message='Aptitude generation batch processed.',
            batch_generated_count=len(generated_items),
            batch_accepted_count=accepted_count,
            batch_rejected_count=rejected_count,
            batch_created_count=created_count,
            existing_count=after_count,
        )
    except Exception as exc:
        _save_failed_batch(job, exc)
        job.refresh_from_db()
        return _job_result(job, processed=True, message=str(exc), error=True)


def enqueue_aptitude_generation_job(
    *,
    section_code,
    target_count=500,
    batch_size=20,
    role_family='',
    skill_tag='',
    topic_tag='',
    difficulty_mix=None,
    question_types=None,
    quality_status_for_created=AptitudeQuestionBank.QualityStatus.NEEDS_REVIEW,
    created_by=None,
):
    target_count = int(target_count)
    batch_size = int(batch_size)
    if target_count < 1 or target_count > MAX_TARGET_COUNT:
        raise ValueError(f'target_count must be between 1 and {MAX_TARGET_COUNT}.')
    if batch_size < 1:
        raise ValueError('batch_size must be at least 1.')
    batch_size = min(batch_size, MAX_BATCH_SIZE)

    section = AptitudeSection.objects.get(code=section_code)
    role_family = _clean_text(role_family)
    skill_tag = _clean_text(skill_tag)
    topic_tag = _clean_text(topic_tag)
    quality_status_for_created = quality_status_for_created or AptitudeQuestionBank.QualityStatus.NEEDS_REVIEW

    active_job = (
        AptitudeQuestionGenerationJob.objects
        .filter(
            section=section,
            role_family=role_family,
            skill_tag=skill_tag,
            topic_tag=topic_tag,
            status__in=[
                AptitudeQuestionGenerationJob.Status.QUEUED,
                AptitudeQuestionGenerationJob.Status.RUNNING,
            ],
        )
        .order_by('-created_at', '-id')
        .first()
    )
    if active_job:
        return active_job

    return AptitudeQuestionGenerationJob.objects.create(
        section=section,
        status=AptitudeQuestionGenerationJob.Status.QUEUED,
        role_family=role_family,
        skill_tag=skill_tag,
        topic_tag=topic_tag,
        target_count=target_count,
        batch_size=batch_size,
        difficulty_mix=difficulty_mix or {},
        question_types=list(question_types or []),
        quality_status_for_created=quality_status_for_created,
        created_by=created_by,
        payload={
            'section_code': section_code,
            'target_count': target_count,
            'batch_size': batch_size,
            'role_family': role_family,
            'skill_tag': skill_tag,
            'topic_tag': topic_tag,
        },
    )


def process_aptitude_generation_queue(limit=1, *, section_code=''):
    limit = max(1, int(limit or 1))
    stale_cutoff = timezone.now() - timedelta(minutes=15)
    filters = (
        Q(status=AptitudeQuestionGenerationJob.Status.QUEUED)
        | Q(status=AptitudeQuestionGenerationJob.Status.RUNNING, started_at__isnull=True)
        | Q(status=AptitudeQuestionGenerationJob.Status.RUNNING, started_at__lt=stale_cutoff)
    )
    queryset = AptitudeQuestionGenerationJob.objects.filter(filters)
    if section_code:
        queryset = queryset.filter(section__code=section_code)

    job_ids = list(
        queryset
        .order_by('created_at', 'id')
        .values_list('id', flat=True)[:limit]
    )
    return [process_aptitude_generation_job(job_id) for job_id in job_ids]


def repair_aptitude_generation_job_status(job):
    existing_count = _matching_question_queryset(job).count()
    if existing_count >= int(job.target_count) or int(job.accepted_count) >= int(job.target_count):
        _mark_job_completed(
            job,
            {
                'message': 'Generation job status repaired.',
                'existing_count': existing_count,
                'accepted_count': job.accepted_count,
            },
        )
        job.refresh_from_db()
        return True
    return False


def repair_aptitude_generation_job_statuses(*, section_code=''):
    queryset = AptitudeQuestionGenerationJob.objects.select_related('section').order_by('id')
    if section_code:
        queryset = queryset.filter(section__code=section_code)
    repaired_count = 0
    for job in queryset.iterator():
        if repair_aptitude_generation_job_status(job):
            repaired_count += 1
    return repaired_count


def call_openai_for_aptitude_questions(prompt, *, model_name=''):
    if not getattr(settings, 'APTITUDE_QUESTION_BANK_OPENAI_ENABLED', False):
        raise RuntimeError('Aptitude OpenAI generation is disabled.')

    api_key = _setting_str_value(getattr(settings, 'OPENAI_API_KEY', ''))
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is missing.')

    model = resolve_aptitude_generation_model_name(model_name)
    timeout = max(1, int(getattr(settings, 'APTITUDE_QUESTION_GENERATION_TIMEOUT_SECONDS', 60)))
    body = json.dumps({
        'model': model,
        'input': prompt,
        'temperature': 0.2,
        'text': {
            'format': {
                'type': 'json_schema',
                'name': 'aptitude_question_bank_batch',
                'strict': True,
                'schema': _openai_aptitude_question_schema(),
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
        raise RuntimeError(f'OpenAI aptitude generation HTTP error {exc.code}: {detail[:400]}') from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(
            f'OpenAI aptitude generation timed out provider=openai model={model} timeout_seconds={timeout}.'
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'OpenAI aptitude generation network error: {exc.reason}') from exc

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError('OpenAI aptitude generation returned invalid response JSON.') from exc

    output_text = _extract_output_text(payload)
    if not output_text:
        raise RuntimeError('OpenAI aptitude generation returned no structured output.')
    return output_text


def resolve_aptitude_generation_model_name(model_name=''):
    return (
        _setting_str_value(model_name)
        or _setting_str_value(getattr(settings, 'APTITUDE_QUESTION_GENERATION_MODEL', ''))
        or _setting_str_value(getattr(settings, 'INTERVIEW_QA_OPENAI_MODEL', ''))
        or _setting_str_value(getattr(settings, 'OPENAI_MODEL', ''))
        or 'gpt-4o-mini'
    )


def _claim_generation_job(job_id):
    with transaction.atomic():
        job = (
            AptitudeQuestionGenerationJob.objects
            .select_for_update()
            .get(id=job_id)
        )
        if job.status in {
            AptitudeQuestionGenerationJob.Status.COMPLETED,
            AptitudeQuestionGenerationJob.Status.CANCELLED,
        }:
            return job
        job.status = AptitudeQuestionGenerationJob.Status.RUNNING
        if not job.started_at:
            job.started_at = timezone.now()
        if not job.model_name:
            job.model_name = resolve_aptitude_generation_model_name()
        job.error_message = ''
        job.finished_at = None
        job.save(update_fields=['status', 'started_at', 'model_name', 'error_message', 'finished_at', 'updated_at'])
        return job


def _matching_question_queryset(job):
    queryset = AptitudeQuestionBank.objects.filter(
        section=job.section,
        is_active=True,
        quality_status__in=COUNTED_QUALITY_STATUSES,
    )
    if job.role_family:
        queryset = queryset.filter(role_family=job.role_family)
    if job.skill_tag:
        queryset = queryset.filter(skill_tag=job.skill_tag)
    if job.topic_tag:
        queryset = queryset.filter(topic_tag=job.topic_tag)
    return queryset


def _save_successful_batch(
    job,
    *,
    status,
    generated_count,
    accepted_count,
    rejected_count,
    created_count,
    before_count,
    after_count,
    batch_size,
    rejection_errors,
    finished_at,
):
    with transaction.atomic():
        locked_job = AptitudeQuestionGenerationJob.objects.select_for_update().get(id=job.id)
        result = dict(locked_job.result or {})
        batches = list(result.get('batches') or [])
        batches.append({
            'at': timezone.now().isoformat(),
            'batch_size': batch_size,
            'generated_count': generated_count,
            'accepted_count': accepted_count,
            'rejected_count': rejected_count,
            'created_count': created_count,
            'before_count': before_count,
            'after_count': after_count,
            'rejection_errors': rejection_errors[:10],
        })
        result.update({
            'batches': batches[-25:],
            'last_batch': batches[-1],
            'current_matching_count': after_count,
        })
        locked_job.status = status
        locked_job.generated_count += generated_count
        locked_job.accepted_count += accepted_count
        locked_job.rejected_count += rejected_count
        locked_job.attempts = 0
        locked_job.result = result
        locked_job.error_message = ''
        locked_job.finished_at = finished_at
        locked_job.save(update_fields=[
            'status',
            'generated_count',
            'accepted_count',
            'rejected_count',
            'attempts',
            'result',
            'error_message',
            'finished_at',
            'updated_at',
        ])


def _save_failed_batch(job, exc):
    message = str(exc)[:2000]
    non_retryable_messages = {
        'Aptitude OpenAI generation is disabled.',
        'OPENAI_API_KEY is missing.',
    }
    with transaction.atomic():
        locked_job = AptitudeQuestionGenerationJob.objects.select_for_update().get(id=job.id)
        locked_job.attempts += 1
        will_retry = locked_job.attempts < locked_job.max_attempts and str(exc) not in non_retryable_messages
        locked_job.status = (
            AptitudeQuestionGenerationJob.Status.QUEUED
            if will_retry
            else AptitudeQuestionGenerationJob.Status.FAILED
        )
        locked_job.error_message = message
        locked_job.result = {
            **(locked_job.result or {}),
            'last_error': message,
            'attempts': locked_job.attempts,
            'will_retry': will_retry,
        }
        if not will_retry:
            locked_job.finished_at = timezone.now()
        locked_job.save(update_fields=['status', 'attempts', 'error_message', 'result', 'finished_at', 'updated_at'])


def _mark_job_completed(job, extra_result):
    with transaction.atomic():
        locked_job = AptitudeQuestionGenerationJob.objects.select_for_update().get(id=job.id)
        locked_job.status = AptitudeQuestionGenerationJob.Status.COMPLETED
        locked_job.result = {**(locked_job.result or {}), **(extra_result or {})}
        locked_job.error_message = ''
        locked_job.attempts = 0
        if not locked_job.finished_at:
            locked_job.finished_at = timezone.now()
        locked_job.save(update_fields=['status', 'attempts', 'result', 'error_message', 'finished_at', 'updated_at'])


def _job_result(job, *, processed, message, error=False, **extra):
    return {
        'ok': not error and job.status != AptitudeQuestionGenerationJob.Status.FAILED,
        'processed': processed,
        'generation_job_id': job.id,
        'section_code': job.section.code,
        'status': job.status,
        'target_count': job.target_count,
        'generated_count': job.generated_count,
        'accepted_count': job.accepted_count,
        'rejected_count': job.rejected_count,
        'message': message,
        **extra,
    }


def _find_duplicate_question(section, question_text):
    normalized = _normalize_question_text(question_text)
    if not normalized:
        return None
    candidates = AptitudeQuestionBank.objects.filter(section=section).only('id', 'question_text')
    for candidate in candidates:
        if _normalize_question_text(candidate.question_text) == normalized:
            return candidate
    return None


def _extract_json_text(raw_text):
    text = raw_text.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        text = '\n'.join(lines).strip()
    if text.startswith('{') or text.startswith('['):
        return text

    object_start = text.find('{')
    array_start = text.find('[')
    starts = [index for index in [object_start, array_start] if index >= 0]
    if not starts:
        raise ValueError('OpenAI response did not contain JSON.')
    start = min(starts)
    end_char = '}' if text[start] == '{' else ']'
    end = text.rfind(end_char)
    if end <= start:
        raise ValueError('OpenAI response did not contain complete JSON.')
    return text[start:end + 1]


def _extract_output_text(payload):
    chunks = []
    for output_item in payload.get('output') or []:
        for content_item in output_item.get('content') or []:
            if content_item.get('type') in {'output_text', 'text'} and content_item.get('text'):
                chunks.append(content_item['text'])
    if chunks:
        return '\n'.join(chunks).strip()
    return (payload.get('output_text') or '').strip()


def _openai_aptitude_question_schema():
    option_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'key': {'type': 'string'},
            'label': {'type': 'string'},
        },
        'required': ['key', 'label'],
    }
    answer_pairs_schema = {
        'type': ['object', 'null'],
        'additionalProperties': False,
        'properties': {
            'A': {'type': ['string', 'null']},
            'B': {'type': ['string', 'null']},
            'C': {'type': ['string', 'null']},
            'D': {'type': ['string', 'null']},
            'E': {'type': ['string', 'null']},
            'F': {'type': ['string', 'null']},
        },
        'required': ['A', 'B', 'C', 'D', 'E', 'F'],
    }
    answer_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'type': {'type': 'string'},
            'correct_key': {'type': ['string', 'null']},
            'correct_keys': {'type': ['array', 'null'], 'items': {'type': 'string'}},
            'value': {'type': ['string', 'number', 'boolean', 'null']},
            'tolerance': {'type': ['number', 'null']},
            'accepted_values': {'type': ['array', 'null'], 'items': {'type': 'string'}},
            'accepted_other_values': {'type': ['array', 'null'], 'items': {'type': 'string'}},
            'case_sensitive': {'type': ['boolean', 'null']},
            'trim_spaces': {'type': ['boolean', 'null']},
            'pairs': answer_pairs_schema,
            'correct_order': {'type': ['array', 'null'], 'items': {'type': 'string'}},
        },
        'required': [
            'type',
            'correct_key',
            'correct_keys',
            'value',
            'tolerance',
            'accepted_values',
            'accepted_other_values',
            'case_sensitive',
            'trim_spaces',
            'pairs',
            'correct_order',
        ],
    }
    scoring_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'partial_credit': {'type': 'boolean'},
            'normalize_text': {'type': 'boolean'},
        },
        'required': ['partial_credit', 'normalize_text'],
    }
    media_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'type': {'type': 'string'},
            'description': {'type': 'string'},
            'position': {'type': 'string'},
        },
        'required': ['type', 'description', 'position'],
    }
    question_schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'section_code': {'type': 'string'},
            'question_text': {'type': 'string'},
            'question_type': {'type': 'string'},
            'difficulty': {'type': 'string'},
            'options': {'type': 'array', 'items': option_schema},
            'answer_schema': answer_schema,
            'scoring_schema': scoring_schema,
            'explanation': {'type': 'string'},
            'skill_tag': {'type': 'string'},
            'topic_tag': {'type': 'string'},
            'role_family': {'type': 'string'},
            'question_media': {'type': 'array', 'items': media_schema},
        },
        'required': [
            'section_code',
            'question_text',
            'question_type',
            'difficulty',
            'options',
            'answer_schema',
            'scoring_schema',
            'explanation',
            'skill_tag',
            'topic_tag',
            'role_family',
            'question_media',
        ],
    }
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'questions': {
                'type': 'array',
                'items': question_schema,
            },
        },
        'required': ['questions'],
    }


def _clean_text(value):
    if value is None:
        return ''
    return ' '.join(str(value).split())


def _schema_string_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    cleaned = _clean_text(value)
    return [cleaned] if cleaned else []


def _setting_str_value(value):
    return str(value or '').strip()


def _normalize_question_text(value):
    return _clean_text(value).casefold()
