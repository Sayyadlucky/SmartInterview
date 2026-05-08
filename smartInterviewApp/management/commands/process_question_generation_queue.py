from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from smartInterviewApp.services.question_banks import process_question_generation_queue


class Command(BaseCommand):
    help = 'Process queued skill-wise interview question generation jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args, **options):
        limit = options['limit']
        if limit is None:
            limit = int(getattr(settings, 'INTERVIEW_QUESTION_BANK_WORKER_LIMIT', 1))
        results = process_question_generation_queue(limit=max(1, limit))
        for result in results:
            self.stdout.write(str(result))
        self.stdout.write(self.style.SUCCESS(f'Processed {len(results)} question generation jobs.'))
