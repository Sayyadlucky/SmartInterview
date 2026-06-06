from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from smartInterviewApp.models import AptitudeQuestionBank, AptitudeSection
from smartInterviewApp.services.aptitude_question_schemas import (
    QUESTION_TYPE_IMAGE_CHOICE,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_NUMERIC,
    QUESTION_TYPE_ORDERING,
    QUESTION_TYPE_SINGLE_CHOICE,
    QUESTION_TYPE_TEXT_INPUT,
    default_scoring_schema,
    make_image_option,
    make_question_image,
    make_text_option,
    multiple_choice_answer,
    numeric_answer,
    ordering_answer,
    single_choice_answer,
    text_answer,
    validate_question_payload,
)


def text_options(*items):
    return [make_text_option(key, label) for key, label in items]


SAMPLE_QUESTIONS = [
    {
        'section_code': 'quantitative_aptitude',
        'question_type': QUESTION_TYPE_SINGLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'If 20% of a number is 50, what is the number?',
        'options': text_options(('A', '200'), ('B', '250'), ('C', '300'), ('D', '150')),
        'answer_schema': single_choice_answer('B'),
        'explanation': '20% of 250 is 50, so the number is 250.',
    },
    {
        'section_code': 'quantitative_aptitude',
        'question_type': QUESTION_TYPE_NUMERIC,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'A train travels 180 km in 3 hours. What is its speed in km/h?',
        'options': [],
        'answer_schema': numeric_answer(60),
        'explanation': 'Speed is distance divided by time: 180 / 3 = 60 km/h.',
    },
    {
        'section_code': 'logical_reasoning',
        'question_type': QUESTION_TYPE_SINGLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.MEDIUM,
        'question_text': 'Find the next number in the series: 2, 6, 12, 20, 30, ?',
        'options': text_options(('A', '40'), ('B', '42'), ('C', '44'), ('D', '46')),
        'answer_schema': single_choice_answer('B'),
        'explanation': 'The differences are 4, 6, 8, 10, so the next difference is 12.',
    },
    {
        'section_code': 'logical_reasoning',
        'question_type': QUESTION_TYPE_ORDERING,
        'difficulty': AptitudeQuestionBank.Difficulty.MEDIUM,
        'question_text': 'Arrange the steps in a logical order for solving a workplace problem.',
        'options': text_options(
            ('A', 'Identify the root cause'),
            ('B', 'Implement the chosen solution'),
            ('C', 'Evaluate possible solutions'),
            ('D', 'Understand the problem clearly'),
        ),
        'answer_schema': ordering_answer(['D', 'A', 'C', 'B']),
        'scoring_schema': default_scoring_schema(partial_credit=True),
        'explanation': 'A structured problem-solving flow starts with understanding, then cause, options, and action.',
    },
    {
        'section_code': 'verbal_reasoning',
        'question_type': QUESTION_TYPE_SINGLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.MEDIUM,
        'question_text': (
            'Statement: All managers are employees. Some employees are trainers. '
            'Which conclusion definitely follows?'
        ),
        'options': text_options(
            ('A', 'All managers are trainers'),
            ('B', 'Some trainers are managers'),
            ('C', 'All managers are employees'),
            ('D', 'No employee is a manager'),
        ),
        'answer_schema': single_choice_answer('C'),
        'explanation': 'The statement directly establishes that all managers are employees.',
    },
    {
        'section_code': 'verbal_ability',
        'question_type': QUESTION_TYPE_SINGLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'Choose the grammatically correct sentence.',
        'options': text_options(
            ('A', "She don't like delayed feedback."),
            ('B', "She doesn't likes delayed feedback."),
            ('C', "She doesn't like delayed feedback."),
            ('D', 'She not like delayed feedback.'),
        ),
        'answer_schema': single_choice_answer('C'),
        'explanation': 'The correct auxiliary and verb form is "does not like".',
    },
    {
        'section_code': 'english_vocabulary',
        'question_type': QUESTION_TYPE_SINGLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'Choose the synonym of "efficient".',
        'options': text_options(('A', 'Wasteful'), ('B', 'Productive'), ('C', 'Slow'), ('D', 'Careless')),
        'answer_schema': single_choice_answer('B'),
        'explanation': 'Efficient means producing results with minimal waste, so productive is the closest synonym.',
    },
    {
        'section_code': 'english_vocabulary',
        'question_type': QUESTION_TYPE_TEXT_INPUT,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'Fill in the blank: A person who can communicate clearly is often called ______.',
        'options': [],
        'answer_schema': text_answer(['articulate', 'clear communicator']),
        'explanation': 'Articulate and clear communicator both describe someone who communicates clearly.',
    },
    {
        'section_code': 'non_verbal_reasoning',
        'question_type': QUESTION_TYPE_IMAGE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.MEDIUM,
        'question_text': 'Select the figure that best completes the pattern.',
        'question_media': [
            make_question_image(
                'https://example.com/non-verbal/pattern-question.png',
                alt='Placeholder pattern question image',
            ),
        ],
        'options': [
            make_image_option('A', 'https://example.com/non-verbal/option-a.png', alt='Placeholder option A'),
            make_image_option('B', 'https://example.com/non-verbal/option-b.png', alt='Placeholder option B'),
            make_image_option('C', 'https://example.com/non-verbal/option-c.png', alt='Placeholder option C'),
            make_image_option('D', 'https://example.com/non-verbal/option-d.png', alt='Placeholder option D'),
        ],
        'answer_schema': single_choice_answer('C'),
        'explanation': 'Placeholder image URLs demonstrate image-choice schema support until real assets are added.',
    },
    {
        'section_code': 'technical_mcq',
        'question_type': QUESTION_TYPE_SINGLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'Which OOP concept allows one interface to be used for different underlying forms?',
        'options': text_options(
            ('A', 'Encapsulation'),
            ('B', 'Abstraction'),
            ('C', 'Polymorphism'),
            ('D', 'Inheritance'),
        ),
        'answer_schema': single_choice_answer('C'),
        'explanation': 'Polymorphism allows one interface to represent different underlying implementations.',
        'role_family': 'technical',
        'skill_tag': 'OOPs',
        'topic_tag': 'Polymorphism',
    },
    {
        'section_code': 'technical_mcq',
        'question_type': QUESTION_TYPE_MULTIPLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'Which of the following are common array operations?',
        'options': text_options(('A', 'Traversal'), ('B', 'Insertion'), ('C', 'Sorting'), ('D', 'HTTP routing')),
        'answer_schema': multiple_choice_answer(['A', 'B', 'C']),
        'scoring_schema': default_scoring_schema(partial_credit=True),
        'explanation': 'Traversal, insertion, and sorting are common operations performed on arrays.',
        'role_family': 'technical',
        'skill_tag': 'Arrays',
        'topic_tag': 'Basic Operations',
    },
    {
        'section_code': 'quantitative_aptitude',
        'question_type': QUESTION_TYPE_SINGLE_CHOICE,
        'difficulty': AptitudeQuestionBank.Difficulty.EASY,
        'question_text': 'If 10 + 5 = ?',
        'options': [
            make_text_option('A', '10'),
            make_text_option('B', '12'),
            make_text_option('C', '14'),
            make_text_option('OTHER', 'Other', requires_input=True, input_type='text', placeholder='Enter your answer'),
        ],
        'answer_schema': single_choice_answer('OTHER', accepted_other_values=['15', 'fifteen']),
        'explanation': 'This sample demonstrates an Other option with candidate-entered accepted values.',
    },
]


class Command(BaseCommand):
    help = 'Seed approved sample aptitude question-bank rows.'

    def handle(self, *args, **options):
        with transaction.atomic():
            stats = seed_sample_questions()

        self.stdout.write(f"Questions: {stats['created']} created, {stats['updated']} updated.")
        self.stdout.write(f"Validation errors: {stats['validation_errors']}.")
        self.stdout.write(f"Validation warnings: {stats['validation_warnings']}.")
        self.stdout.write(self.style.SUCCESS('Sample aptitude question bank seeded successfully.'))


def seed_sample_questions():
    stats = {
        'created': 0,
        'updated': 0,
        'validation_errors': 0,
        'validation_warnings': 0,
    }
    section_codes = {question['section_code'] for question in SAMPLE_QUESTIONS}
    sections_by_code = {
        section.code: section
        for section in AptitudeSection.objects.filter(code__in=section_codes)
    }
    missing_sections = sorted(section_codes - set(sections_by_code))
    if missing_sections:
        raise CommandError(
            'Missing aptitude sections: '
            f'{", ".join(missing_sections)}. Run seed_aptitude_defaults first.'
        )

    for question in SAMPLE_QUESTIONS:
        question_type = question['question_type']
        options = question.get('options', [])
        answer_schema = question['answer_schema']
        validation_errors = validate_question_payload(question_type, options, answer_schema)
        if validation_errors:
            stats['validation_errors'] += len(validation_errors)
            raise CommandError(
                f"Invalid sample question '{question['question_text']}': "
                + '; '.join(validation_errors)
            )

        section = sections_by_code[question['section_code']]
        _, created = AptitudeQuestionBank.objects.update_or_create(
            section=section,
            question_text=question['question_text'],
            defaults={
                'question_type': question_type,
                'role_family': question.get('role_family', ''),
                'skill_tag': question.get('skill_tag', ''),
                'topic_tag': question.get('topic_tag', ''),
                'difficulty': question['difficulty'],
                'question_html': question.get('question_html', ''),
                'question_media': question.get('question_media', []),
                'options': options,
                'answer_schema': answer_schema,
                'scoring_schema': question.get('scoring_schema', default_scoring_schema()),
                'marks': Decimal('2'),
                'negative_marks': Decimal('0'),
                'explanation': question['explanation'],
                'quality_status': AptitudeQuestionBank.QualityStatus.APPROVED,
                'is_active': True,
            },
        )
        stats['created' if created else 'updated'] += 1

    return stats
