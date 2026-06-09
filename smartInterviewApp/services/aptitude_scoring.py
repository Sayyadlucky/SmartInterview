from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from smartInterviewApp.models import AptitudeAnswer, AptitudeTestAssignment, AptitudeTestResult
from smartInterviewApp.services.aptitude_question_schemas import (
    QUESTION_TYPE_FILL_BLANK,
    QUESTION_TYPE_IMAGE_CHOICE,
    QUESTION_TYPE_MATCHING,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_NUMERIC,
    QUESTION_TYPE_ORDERING,
    QUESTION_TYPE_SINGLE_CHOICE,
    QUESTION_TYPE_TEXT_INPUT,
    QUESTION_TYPE_TRUE_FALSE,
)


PROBLEM_SOLVING_SECTIONS = {
    'quantitative_aptitude',
    'logical_reasoning',
    'non_verbal_reasoning',
    'technical_mcq',
}
COMMUNICATION_SECTIONS = {
    'verbal_reasoning',
    'verbal_ability',
    'english_vocabulary',
}
TECHNICAL_SECTIONS = {'technical_mcq'}


def normalize_text_value(value, *, case_sensitive=False, trim_spaces=True):
    normalized = '' if value is None else str(value)
    if trim_spaces:
        normalized = normalized.strip()
    if not case_sensitive:
        normalized = normalized.lower()
    return normalized


def score_question_answer(question, answer_payload, *, negative_marking_enabled=False):
    marks = _to_decimal(getattr(question, 'marks', 0))
    negative_marks = _to_decimal(getattr(question, 'negative_marks', 0))
    answer_schema = getattr(question, 'answer_schema', None) or {}
    question_type = getattr(question, 'question_type', '')

    try:
        attempted = _is_attempted(question_type, answer_payload)
        if not attempted:
            return _score_result(False, False, Decimal('0'), marks, 'skipped')

        is_correct = _is_correct(question_type, answer_payload, answer_schema)
        if is_correct:
            return _score_result(True, True, marks, marks, 'correct')

        awarded = -negative_marks if negative_marking_enabled and negative_marks else Decimal('0')
        return _score_result(True, False, awarded, marks, 'wrong')
    except (TypeError, ValueError, InvalidOperation):
        awarded = -negative_marks if negative_marking_enabled and negative_marks else Decimal('0')
        return _score_result(True, False, awarded, marks, 'invalid_answer')


@transaction.atomic
def score_assignment(assignment):
    questions = list(assignment.questions.select_related('section').order_by('order_index', 'id'))
    answers_by_question_id = {
        answer.question_id: answer
        for answer in assignment.answers.select_related('question')
    }
    negative_marking_enabled = bool(getattr(assignment, 'negative_marking_enabled', False))

    totals = _empty_totals()
    section_totals = defaultdict(_empty_totals)
    skill_totals = defaultdict(_empty_totals)

    for question in questions:
        answer = answers_by_question_id.get(question.id)
        answer_payload = answer.answer_payload if answer else {}
        scored = score_question_answer(
            question,
            answer_payload,
            negative_marking_enabled=negative_marking_enabled,
        )

        if answer:
            answer.is_correct = scored['is_correct']
            answer.marks_awarded = scored['marks_awarded']
            answer.save(update_fields=['is_correct', 'marks_awarded', 'answered_at'])

        _accumulate_totals(totals, scored)

        section = question.section
        section_key = section.code if section else 'unassigned'
        section_bucket = section_totals[section_key]
        section_bucket['section_name'] = section.name if section else 'Unassigned'
        _accumulate_totals(section_bucket, scored)

        if question.skill_tag:
            skill_bucket = skill_totals[question.skill_tag]
            _accumulate_totals(skill_bucket, scored)

    total_marks = totals['total_marks']
    marks_obtained = totals['marks_obtained']
    score_percent = _percent(marks_obtained, total_marks)
    passing_score_percent = _to_decimal(getattr(assignment, 'passing_score_percent', 0))

    section_breakdown = _build_section_breakdown(section_totals)
    skill_breakdown = _build_skill_breakdown(skill_totals)
    integrity_summary = _build_integrity_summary(assignment)

    result, _ = AptitudeTestResult.objects.update_or_create(
        assignment=assignment,
        defaults={
            'total_questions': totals['total_questions'],
            'attempted_questions': totals['attempted_questions'],
            'correct_answers': totals['correct_answers'],
            'wrong_answers': totals['wrong_answers'],
            'skipped_questions': totals['skipped_questions'],
            'total_marks': total_marks,
            'marks_obtained': marks_obtained,
            'score_percent': score_percent,
            'passed': score_percent >= passing_score_percent,
            'problem_solving_score': _derived_score(section_breakdown, PROBLEM_SOLVING_SECTIONS),
            'communication_score': _derived_score(section_breakdown, COMMUNICATION_SECTIONS),
            'technical_score': _derived_score(section_breakdown, TECHNICAL_SECTIONS),
            'section_breakdown': section_breakdown,
            'skill_breakdown': skill_breakdown,
            'integrity_summary': integrity_summary,
        },
    )
    return result


@transaction.atomic
def mark_aptitude_assignment_expired_if_needed(assignment, *, submit_and_score=True):
    if assignment.status != AptitudeTestAssignment.Status.IN_PROGRESS or not assignment.expires_at:
        return False

    now = timezone.now()
    if now < assignment.expires_at:
        return False

    assignment.status = AptitudeTestAssignment.Status.EXPIRED
    update_fields = ['status', 'updated_at']
    if not assignment.submitted_at:
        assignment.submitted_at = now
        update_fields.append('submitted_at')
    assignment.save(update_fields=update_fields)

    if submit_and_score and not AptitudeTestResult.objects.filter(assignment=assignment).exists():
        score_assignment(assignment)

    return True


def _is_attempted(question_type, answer_payload):
    if not answer_payload:
        return False
    if not isinstance(answer_payload, dict):
        return True

    if question_type in {QUESTION_TYPE_SINGLE_CHOICE, QUESTION_TYPE_IMAGE_CHOICE, QUESTION_TYPE_MULTIPLE_CHOICE}:
        return bool(answer_payload.get('selected_keys'))
    if question_type == QUESTION_TYPE_TRUE_FALSE:
        return answer_payload.get('value') is not None
    if question_type == QUESTION_TYPE_NUMERIC:
        value = answer_payload.get('numeric_value', answer_payload.get('value'))
        return value not in (None, '')
    if question_type in {QUESTION_TYPE_TEXT_INPUT, QUESTION_TYPE_FILL_BLANK}:
        value = answer_payload.get('text', answer_payload.get('value'))
        return normalize_text_value(value) != ''
    if question_type == QUESTION_TYPE_MATCHING:
        return bool(answer_payload.get('matched_pairs'))
    if question_type == QUESTION_TYPE_ORDERING:
        return bool(answer_payload.get('order'))
    return bool(answer_payload)


def _is_correct(question_type, answer_payload, answer_schema):
    if not isinstance(answer_payload, dict):
        raise TypeError('answer_payload must be a dict')

    if question_type in {QUESTION_TYPE_SINGLE_CHOICE, QUESTION_TYPE_IMAGE_CHOICE}:
        selected_keys = _string_list(answer_payload.get('selected_keys'))
        correct_keys = _correct_keys(answer_schema)
        if selected_keys != correct_keys:
            return False
        if correct_keys == ['OTHER']:
            return _other_text_matches(answer_payload, answer_schema)
        return True

    if question_type == QUESTION_TYPE_MULTIPLE_CHOICE:
        return set(_string_list(answer_payload.get('selected_keys'))) == set(_correct_keys(answer_schema))

    if question_type == QUESTION_TYPE_TRUE_FALSE:
        return bool(answer_payload.get('value')) == bool(answer_schema.get('value'))

    if question_type == QUESTION_TYPE_NUMERIC:
        actual = _to_decimal(answer_payload.get('numeric_value', answer_payload.get('value')))
        expected = _to_decimal(answer_schema['value'])
        tolerance = _to_decimal(answer_schema.get('tolerance', 0))
        return abs(actual - expected) <= tolerance

    if question_type in {QUESTION_TYPE_TEXT_INPUT, QUESTION_TYPE_FILL_BLANK}:
        case_sensitive = bool(answer_schema.get('case_sensitive', False))
        trim_spaces = bool(answer_schema.get('trim_spaces', True))
        actual = normalize_text_value(
            answer_payload.get('text', answer_payload.get('value')),
            case_sensitive=case_sensitive,
            trim_spaces=trim_spaces,
        )
        accepted = [
            normalize_text_value(value, case_sensitive=case_sensitive, trim_spaces=trim_spaces)
            for value in answer_schema.get('accepted_values', [])
        ]
        return actual in accepted

    if question_type == QUESTION_TYPE_MATCHING:
        return _normalized_mapping(answer_payload.get('matched_pairs')) == _normalized_mapping(answer_schema.get('pairs'))

    if question_type == QUESTION_TYPE_ORDERING:
        return _string_list(answer_payload.get('order')) == _string_list(answer_schema.get('correct_order'))

    return False


def _other_text_matches(answer_payload, answer_schema):
    case_sensitive = bool(answer_schema.get('case_sensitive', False))
    trim_spaces = bool(answer_schema.get('trim_spaces', True))
    actual = normalize_text_value(
        answer_payload.get('other_text'),
        case_sensitive=case_sensitive,
        trim_spaces=trim_spaces,
    )
    accepted = [
        normalize_text_value(value, case_sensitive=case_sensitive, trim_spaces=trim_spaces)
        for value in answer_schema.get('accepted_other_values', [])
    ]
    return actual in accepted


def _correct_keys(answer_schema):
    if 'correct_keys' in answer_schema:
        return _string_list(answer_schema.get('correct_keys'))
    if 'correct_key' in answer_schema:
        return _string_list([answer_schema.get('correct_key')])
    return []


def _string_list(value):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    return [str(item) for item in value]


def _normalized_mapping(value):
    if not isinstance(value, dict):
        raise TypeError('mapping answer must be a dict')
    return {str(key): str(item) for key, item in value.items()}


def _to_decimal(value):
    return Decimal(str(value if value is not None else 0))


def _score_result(is_attempted, is_correct, marks_awarded, max_marks, reason):
    return {
        'is_attempted': is_attempted,
        'is_correct': is_correct,
        'marks_awarded': marks_awarded,
        'max_marks': max_marks,
        'reason': reason,
    }


def _empty_totals():
    return {
        'total_questions': 0,
        'attempted_questions': 0,
        'correct_answers': 0,
        'wrong_answers': 0,
        'skipped_questions': 0,
        'total_marks': Decimal('0'),
        'marks_obtained': Decimal('0'),
    }


def _accumulate_totals(bucket, scored):
    bucket['total_questions'] += 1
    bucket['total_marks'] += scored['max_marks']
    bucket['marks_obtained'] += scored['marks_awarded']
    if not scored['is_attempted']:
        bucket['skipped_questions'] += 1
    elif scored['is_correct']:
        bucket['attempted_questions'] += 1
        bucket['correct_answers'] += 1
    else:
        bucket['attempted_questions'] += 1
        bucket['wrong_answers'] += 1


def _percent(numerator, denominator):
    denominator = _to_decimal(denominator)
    if denominator == 0:
        return Decimal('0')
    return (numerator / denominator * Decimal('100')).quantize(Decimal('0.01'))


def _build_section_breakdown(section_totals):
    breakdown = {}
    for section_key, totals in section_totals.items():
        breakdown[section_key] = _json_totals(totals, section_name=totals.get('section_name', section_key))
    return breakdown


def _build_skill_breakdown(skill_totals):
    return {
        skill_tag: _json_totals(totals)
        for skill_tag, totals in skill_totals.items()
    }


def _json_totals(totals, *, section_name=None):
    payload = {
        'total_questions': totals['total_questions'],
        'attempted_questions': totals['attempted_questions'],
        'correct_answers': totals['correct_answers'],
        'wrong_answers': totals['wrong_answers'],
        'skipped_questions': totals['skipped_questions'],
        'total_marks': float(totals['total_marks']),
        'marks_obtained': float(totals['marks_obtained']),
        'score_percent': float(_percent(totals['marks_obtained'], totals['total_marks'])),
    }
    if section_name is not None:
        payload = {'section_name': section_name, **payload}
    return payload


def _derived_score(section_breakdown, section_codes):
    matching_scores = [
        Decimal(str(payload.get('score_percent', 0)))
        for code, payload in section_breakdown.items()
        if code in section_codes and payload.get('total_questions', 0) > 0
    ]
    if not matching_scores:
        return Decimal('0')
    return (sum(matching_scores) / Decimal(len(matching_scores))).quantize(Decimal('0.01'))


def _build_integrity_summary(assignment):
    events = assignment.integrity_events.all()
    events_by_type = Counter(event.event_type for event in events)
    total_events = sum(events_by_type.values())
    if total_events >= 8:
        risk_level = 'high'
    elif total_events >= 3:
        risk_level = 'medium'
    else:
        risk_level = 'low'
    return {
        'total_events': total_events,
        'events_by_type': dict(events_by_type),
        'risk_level': risk_level,
    }
