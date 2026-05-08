from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand

from smartInterviewApp.models import CodingQuestion, Skill, SkillQuestion, normalize_skill_key


VERBAL_QUESTIONS = [
    ('Core Java', 'java-oop', 'How do inheritance and composition differ in Core Java design?', ['Explains reuse tradeoffs', 'Mentions coupling', 'Uses a practical example']),
    ('Core Java', 'java-concurrency', 'What signals would you look for when debugging a Java multithreading issue?', ['Mentions race conditions', 'Discusses locks or synchronization', 'Explains reproducibility']),
    ('Python', 'python-data-model', 'How do Python decorators work, and when would you avoid using one?', ['Explains callable wrapping', 'Mentions readability', 'Covers metadata or functools.wraps']),
    ('SQL', 'sql-joins', 'How would you explain the difference between inner joins and left joins?', ['Defines row preservation', 'Uses example tables', 'Mentions nulls']),
    ('Django', 'django-orm', 'How do you avoid N+1 queries in Django ORM code?', ['Mentions select_related', 'Mentions prefetch_related', 'Explains query inspection']),
]

CODING_QUESTIONS = [
    (
        'Python',
        'Normalize Skill Names',
        'Given a list of skill names, return unique normalized lowercase slugs while preserving first-seen order.',
        'python-normalize-skill-names',
    ),
    (
        'SQL',
        'Find Duplicate Emails',
        'Write a SQL query that returns email addresses appearing more than once in a candidates table.',
        'sql-find-duplicate-emails',
    ),
    (
        'Django',
        'Optimize Candidate Query',
        'Refactor a Django queryset to fetch interviews with candidate profile and role data without N+1 queries.',
        'django-optimize-candidate-query',
    ),
]


class Command(BaseCommand):
    help = 'Seed a small reusable sample interview question bank.'

    def handle(self, *args, **options):
        call_command('seed_interview_skills', verbosity=0)

        verbal_created = 0
        coding_created = 0
        for skill_name, family_key, question_text, answer_points in VERBAL_QUESTIONS:
            skill = Skill.objects.get(key=normalize_skill_key(skill_name))
            _, was_created = SkillQuestion.objects.update_or_create(
                skill=skill,
                family_key=family_key,
                question_text=question_text,
                defaults={
                    'difficulty': SkillQuestion.Difficulty.INTERMEDIATE,
                    'question_type': SkillQuestion.QuestionType.CONCEPT,
                    'ideal_answer_points': answer_points,
                    'tags': [skill.key, family_key],
                    'source': SkillQuestion.Source.MANUAL,
                    'is_active': True,
                },
            )
            verbal_created += int(was_created)

        for skill_name, title, prompt, slug in CODING_QUESTIONS:
            skill = Skill.objects.get(key=normalize_skill_key(skill_name))
            _, was_created = CodingQuestion.objects.update_or_create(
                slug=slug,
                defaults={
                    'skill': skill,
                    'title': title,
                    'prompt': prompt,
                    'difficulty': CodingQuestion.Difficulty.EASY,
                    'question_type': CodingQuestion.QuestionType.FRAMEWORK_TASK if skill_name == 'Django' else CodingQuestion.QuestionType.SQL_QUERY if skill_name == 'SQL' else CodingQuestion.QuestionType.ALGORITHM,
                    'family_key': slug,
                    'tags': [skill.key, slug],
                    'source': CodingQuestion.Source.MANUAL,
                    'is_active': True,
                },
            )
            coding_created += int(was_created)

        self.stdout.write(self.style.SUCCESS(
            f'Seeded sample interview questions: {verbal_created} verbal created, {coding_created} coding created.'
        ))
