from decimal import Decimal

from django.db import transaction

from smartInterviewApp.models import (
    AptitudeQuestionBank,
    AptitudeTestAssignment,
    AptitudeTestQuestion,
    AptitudeTestTemplate,
)


DEFAULT_TEMPLATE_TITLE = 'General Aptitude Test'
GENERIC_ROLE_FAMILIES = {'', 'general', 'technical', 'mixed'}


class AptitudeAssignmentError(ValueError):
    pass


def get_default_aptitude_template(role_type='general', role_family=''):
    role_type = role_type or AptitudeTestTemplate.RoleType.GENERAL
    role_family = role_family or ''

    if role_family:
        template = (
            AptitudeTestTemplate.objects
            .filter(is_active=True, role_type=role_type, role_family=role_family)
            .order_by('id')
            .first()
        )
        if template:
            return template

    template = (
        AptitudeTestTemplate.objects
        .filter(is_active=True, role_type=role_type)
        .order_by('id')
        .first()
    )
    if template:
        return template

    return (
        AptitudeTestTemplate.objects
        .filter(is_active=True, title=DEFAULT_TEMPLATE_TITLE)
        .order_by('id')
        .first()
    )


def get_template_coverage(template):
    coverage = {}
    for template_section in _template_sections(template):
        section = template_section.section
        available = _approved_questions_for_section(template, section).count()
        required = template_section.question_count
        coverage[section.code] = {
            'required': required,
            'available': available,
            'ready': required == 0 or available >= required,
        }
    return coverage


def validate_template_readiness(template):
    if template is None:
        return {
            'ready': False,
            'missing_sections': [],
            'coverage': {},
            'message': 'No active aptitude test template is available.',
        }

    coverage = get_template_coverage(template)
    missing_sections = [
        code
        for code, item in coverage.items()
        if item['required'] > 0 and not item['ready']
    ]
    ready = not missing_sections
    if ready:
        message = f'{template.title} is ready.'
    else:
        message = f'{template.title} is missing enough approved questions for: {", ".join(missing_sections)}.'
    return {
        'ready': ready,
        'missing_sections': missing_sections,
        'coverage': coverage,
        'message': message,
    }


@transaction.atomic
def create_aptitude_assignment(
    *,
    candidate=None,
    vacancy=None,
    interview=None,
    template=None,
    role_type='general',
    role_family='',
    created_by=None,
    title=None,
    allow_partial=False,
):
    template = template or get_default_aptitude_template(role_type=role_type, role_family=role_family)
    if template is None:
        raise AptitudeAssignmentError('No active aptitude test template is available.')

    readiness = validate_template_readiness(template)
    if not readiness['ready'] and not allow_partial:
        raise AptitudeAssignmentError(readiness['message'])

    assignment = AptitudeTestAssignment.objects.create(
        candidate=candidate,
        vacancy=vacancy,
        interview=interview,
        template=template,
        title=title or template.title or 'Aptitude Test',
        status=AptitudeTestAssignment.Status.ASSIGNED,
        role_type=template.role_type,
        section_config=create_section_config_from_template(template),
        duration_minutes=template.duration_minutes,
        total_questions=template.total_questions,
        marks_per_question=template.marks_per_question,
        total_marks=template.total_marks,
        passing_score_percent=template.passing_score_percent,
        negative_marking_enabled=template.negative_marking_enabled,
        allow_retake=template.allow_retake,
        created_by=created_by,
    )

    questions_created = 0
    selected_question_ids = set()
    for template_section in _template_sections(template):
        question_count = template_section.question_count
        if question_count <= 0:
            continue

        candidates = _select_questions_for_section(
            template,
            template_section.section,
            question_count,
            exclude_ids=selected_question_ids,
            allow_partial=allow_partial,
        )
        for question in candidates:
            selected_question_ids.add(question.id)
            questions_created += 1
            AptitudeTestQuestion.objects.create(
                assignment=assignment,
                source_question=question,
                section=question.section,
                question_type=question.question_type,
                role_family=question.role_family,
                skill_tag=question.skill_tag,
                topic_tag=question.topic_tag,
                difficulty=question.difficulty,
                question_text=question.question_text,
                question_html=question.question_html,
                question_media=question.question_media,
                options=question.options,
                answer_schema=question.answer_schema,
                scoring_schema=question.scoring_schema,
                marks=question.marks,
                negative_marks=question.negative_marks,
                order_index=questions_created,
            )

    return {
        'assignment': assignment,
        'created': True,
        'questions_created': questions_created,
        'readiness': readiness,
    }


def create_section_config_from_template(template):
    config = {}
    for template_section in _template_sections(template):
        section = template_section.section
        config[section.code] = {
            'section_name': section.name,
            'question_count': template_section.question_count,
            'marks_per_question': float(_decimal(template_section.marks_per_question)),
            'difficulty_mix': template_section.difficulty_mix or {},
            'order_index': template_section.order_index,
        }
    return config


def _template_sections(template):
    return (
        template.sections
        .select_related('section')
        .order_by('order_index', 'section__default_order', 'id')
    )


def _approved_questions_for_section(template, section):
    queryset = AptitudeQuestionBank.objects.filter(
        section=section,
        is_active=True,
        quality_status=AptitudeQuestionBank.QualityStatus.APPROVED,
    )
    if _should_prefer_specific_technical_questions(template, section):
        queryset = queryset.filter(role_family__in=[template.role_family, '', 'technical'])
    return queryset


def _select_questions_for_section(template, section, question_count, *, exclude_ids, allow_partial):
    base_queryset = _approved_questions_for_section(template, section).exclude(id__in=exclude_ids)
    if _should_prefer_specific_technical_questions(template, section):
        selected = list(_ordered_question_queryset(
            base_queryset.filter(role_family=template.role_family),
            template,
        )[:question_count])
        remaining = question_count - len(selected)
        if remaining > 0:
            selected_ids = [question.id for question in selected]
            fallback = _ordered_question_queryset(
                base_queryset.exclude(id__in=selected_ids).filter(role_family__in=['', 'technical']),
                template,
            )
            selected.extend(list(fallback[:remaining]))
    else:
        selected = list(_ordered_question_queryset(base_queryset, template)[:question_count])

    if len(selected) < question_count and not allow_partial:
        raise AptitudeAssignmentError(
            f'Only {len(selected)} approved questions available for {section.code}; expected {question_count}.'
        )
    return selected


def _ordered_question_queryset(queryset, template):
    if template.randomize_questions:
        return queryset.order_by('?')
    return queryset.order_by('difficulty', 'id')


def _should_prefer_specific_technical_questions(template, section):
    return (
        section.code == 'technical_mcq'
        and template.role_type == AptitudeTestTemplate.RoleType.TECHNICAL
        and template.role_family not in GENERIC_ROLE_FAMILIES
    )


def _decimal(value):
    return Decimal(str(value if value is not None else 0))
