from __future__ import annotations

from django.core.management.base import BaseCommand

from smartInterviewApp.services.interview_blueprints import process_queued_interview_blueprint_jobs


class Command(BaseCommand):
    help = 'Process queued job interview blueprint tasks from the database queue.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=25)

    def handle(self, *args, **options):
        results = process_queued_interview_blueprint_jobs(limit=max(1, options['limit']))
        success_count = sum(1 for item in results if item.get('ok'))
        self.stdout.write(self.style.SUCCESS(
            f'Processed {len(results)} interview blueprint task(s), {success_count} succeeded.'
        ))
