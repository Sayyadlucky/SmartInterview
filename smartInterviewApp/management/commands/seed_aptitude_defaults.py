from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from smartInterviewApp.models import (
    AptitudeSection,
    AptitudeTestTemplate,
    AptitudeTestTemplateSection,
)


DIFFICULTY_MIX = {
    'easy': 0.3,
    'medium': 0.5,
    'hard': 0.2,
}

SECTION_DEFINITIONS = [
    {
        'name': 'Quantitative Aptitude',
        'code': 'quantitative_aptitude',
        'category': AptitudeSection.Category.APTITUDE,
        'default_order': 10,
        'description': (
            'Measures numerical ability, arithmetic reasoning, percentages, ratios, time and work, '
            'profit/loss, averages, and basic data interpretation.'
        ),
    },
    {
        'name': 'Logical Reasoning',
        'code': 'logical_reasoning',
        'category': AptitudeSection.Category.REASONING,
        'default_order': 20,
        'description': (
            'Measures analytical thinking, pattern identification, deductive reasoning, arrangements, '
            'syllogisms, and decision-making ability.'
        ),
    },
    {
        'name': 'Verbal Reasoning',
        'code': 'verbal_reasoning',
        'category': AptitudeSection.Category.COMMUNICATION,
        'default_order': 30,
        'description': (
            'Measures reasoning through written language, comprehension, statement assumptions, '
            'conclusions, and critical interpretation.'
        ),
    },
    {
        'name': 'Verbal Ability',
        'code': 'verbal_ability',
        'category': AptitudeSection.Category.COMMUNICATION,
        'default_order': 40,
        'description': (
            'Measures grammar, sentence correction, reading comprehension, verbal clarity, and written '
            'communication readiness.'
        ),
    },
    {
        'name': 'Non-Verbal Reasoning',
        'code': 'non_verbal_reasoning',
        'category': AptitudeSection.Category.REASONING,
        'default_order': 50,
        'description': (
            'Measures visual reasoning, figure series, pattern completion, mirror images, paper folding, '
            'embedded figures, and diagram-based problem solving.'
        ),
    },
    {
        'name': 'English Vocabulary',
        'code': 'english_vocabulary',
        'category': AptitudeSection.Category.COMMUNICATION,
        'default_order': 60,
        'description': (
            'Measures vocabulary, synonyms, antonyms, word usage, contextual meaning, and language precision.'
        ),
    },
    {
        'name': 'Technical MCQ',
        'code': 'technical_mcq',
        'category': AptitudeSection.Category.TECHNICAL,
        'default_order': 70,
        'description': (
            'Measures technical fundamentals based on the role, such as OOPs, arrays, data structures, '
            'programming basics, SQL, APIs, and role-specific concepts.'
        ),
    },
]

TEMPLATE_DEFINITIONS = [
    {
        'title': 'General Aptitude Test',
        'role_type': AptitudeTestTemplate.RoleType.GENERAL,
        'role_family': 'general',
        'sections': {
            'quantitative_aptitude': 10,
            'logical_reasoning': 10,
            'verbal_reasoning': 8,
            'verbal_ability': 8,
            'non_verbal_reasoning': 8,
            'english_vocabulary': 6,
            'technical_mcq': 0,
        },
    },
    {
        'title': 'Technical Aptitude Test',
        'role_type': AptitudeTestTemplate.RoleType.TECHNICAL,
        'role_family': 'technical',
        'sections': {
            'quantitative_aptitude': 8,
            'logical_reasoning': 8,
            'verbal_reasoning': 6,
            'verbal_ability': 6,
            'non_verbal_reasoning': 6,
            'english_vocabulary': 4,
            'technical_mcq': 12,
        },
    },
    {
        'title': 'Mixed Aptitude Test',
        'role_type': AptitudeTestTemplate.RoleType.MIXED,
        'role_family': 'mixed',
        'sections': {
            'quantitative_aptitude': 8,
            'logical_reasoning': 8,
            'verbal_reasoning': 7,
            'verbal_ability': 7,
            'non_verbal_reasoning': 6,
            'english_vocabulary': 6,
            'technical_mcq': 8,
        },
    },
]

TEMPLATE_DEFAULTS = {
    'description': '',
    'duration_minutes': 60,
    'total_questions': 50,
    'marks_per_question': Decimal('2'),
    'total_marks': Decimal('100'),
    'passing_score_percent': Decimal('70'),
    'negative_marking_enabled': False,
    'randomize_questions': True,
    'randomize_options': True,
    'allow_retake': False,
    'is_active': True,
}


class Command(BaseCommand):
    help = 'Seed default aptitude sections and aptitude test templates.'

    def handle(self, *args, **options):
        with transaction.atomic():
            section_stats = seed_sections()
            template_stats = seed_templates()

        self.stdout.write(
            f"Sections: {section_stats['created']} created, {section_stats['updated']} updated."
        )
        self.stdout.write(
            f"Templates: {template_stats['created']} created, {template_stats['updated']} updated."
        )
        self.stdout.write(
            f"Template sections: {template_stats['section_created']} created, "
            f"{template_stats['section_updated']} updated."
        )

        for template_summary in template_stats['summaries']:
            self.stdout.write('')
            self.stdout.write(template_summary['title'])
            for code, count in template_summary['distribution']:
                self.stdout.write(f'  - {code}: {count}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Default aptitude sections and templates seeded successfully.'))


def seed_sections():
    stats = {'created': 0, 'updated': 0}

    for definition in SECTION_DEFINITIONS:
        _, created = AptitudeSection.objects.update_or_create(
            code=definition['code'],
            defaults={
                'name': definition['name'],
                'description': definition['description'],
                'category': definition['category'],
                'default_order': definition['default_order'],
                'is_active': True,
            },
        )
        stats['created' if created else 'updated'] += 1

    return stats


def seed_templates():
    stats = {
        'created': 0,
        'updated': 0,
        'section_created': 0,
        'section_updated': 0,
        'summaries': [],
    }
    sections_by_code = {
        section.code: section
        for section in AptitudeSection.objects.filter(code__in=[item['code'] for item in SECTION_DEFINITIONS])
    }

    for definition in TEMPLATE_DEFINITIONS:
        template_defaults = {
            **TEMPLATE_DEFAULTS,
            'role_type': definition['role_type'],
            'role_family': definition['role_family'],
        }
        template, created = AptitudeTestTemplate.objects.update_or_create(
            title=definition['title'],
            defaults=template_defaults,
        )
        stats['created' if created else 'updated'] += 1

        distribution = []
        for code, question_count in definition['sections'].items():
            section = sections_by_code.get(code)
            if section is None:
                raise CommandError(f'Missing aptitude section for code: {code}')

            _, section_created = AptitudeTestTemplateSection.objects.update_or_create(
                template=template,
                section=section,
                defaults={
                    'question_count': question_count,
                    'difficulty_mix': DIFFICULTY_MIX,
                    'marks_per_question': Decimal('2'),
                    'order_index': section.default_order,
                    'is_required': question_count > 0,
                },
            )
            stats['section_created' if section_created else 'section_updated'] += 1
            distribution.append((code, question_count))

        validate_template_distribution(template)
        stats['summaries'].append({
            'title': template.title,
            'distribution': distribution,
        })

    return stats


def validate_template_distribution(template):
    required_question_count = sum(
        template_section.question_count
        for template_section in template.sections.filter(is_required=True)
    )
    if template.is_active and required_question_count != template.total_questions:
        raise CommandError(
            f'{template.title} has {required_question_count} required section questions; '
            f'expected {template.total_questions}.'
        )

    expected_total_marks = Decimal(template.total_questions) * template.marks_per_question
    if template.total_marks != expected_total_marks:
        raise CommandError(
            f'{template.title} total_marks is {template.total_marks}; expected {expected_total_marks}.'
        )

    if template.passing_score_percent != Decimal('70'):
        raise CommandError(
            f'{template.title} passing_score_percent is {template.passing_score_percent}; expected 70.'
        )
