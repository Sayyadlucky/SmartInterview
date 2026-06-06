from __future__ import annotations

from django.core.management.base import BaseCommand

from smartInterviewApp.models import AptitudeQuestionBank
from smartInterviewApp.services.aptitude_generation import normalize_generated_answer_schema


class Command(BaseCommand):
    help = 'Normalize existing aptitude question-bank answer_schema payloads.'

    def add_arguments(self, parser):
        parser.add_argument('--section', default='')
        parser.add_argument('--quality-status', default='')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry_run = bool(options['dry_run'])
        queryset = AptitudeQuestionBank.objects.select_related('section').order_by('id')
        if options['section']:
            queryset = queryset.filter(section__code=options['section'])
        if options['quality_status']:
            queryset = queryset.filter(quality_status=options['quality_status'])

        scanned_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0

        for question in queryset.iterator():
            scanned_count += 1
            try:
                normalized_schema = normalize_generated_answer_schema(
                    question.question_type,
                    question.answer_schema or {},
                )
            except ValueError as exc:
                error_count += 1
                self.stderr.write(f'Question {question.id}: {exc}')
                continue

            if normalized_schema == (question.answer_schema or {}):
                skipped_count += 1
                continue

            updated_count += 1
            if not dry_run:
                question.answer_schema = normalized_schema
                question.save(update_fields=['answer_schema', 'updated_at'])

        self.stdout.write(f'scanned_count={scanned_count}')
        self.stdout.write(f'updated_count={updated_count}')
        self.stdout.write(f'skipped_count={skipped_count}')
        self.stdout.write(f'error_count={error_count}')
        if dry_run:
            self.stdout.write('dry_run=True')
