from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.services.question_banks import enqueue_missing_coding_questions_for_interview


class Command(BaseCommand):
    help = 'Preview or enqueue missing primary-skill coding question generation.'

    def add_arguments(self, parser):
        parser.add_argument('--interview-id', type=int, required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        result = enqueue_missing_coding_questions_for_interview(
            options['interview_id'],
            apply=bool(options['apply']),
        )
        if not result.get('ok'):
            raise CommandError(result.get('message') or result.get('status') or 'Unable to enqueue coding generation.')

        self.stdout.write(f"Mode: {result['mode']}")
        self.stdout.write(f"Interview: {result['interview_id']}")
        self.stdout.write(f"Role: {result['role']}")
        self.stdout.write(f"Primary skill: {result['primary_skill']}")
        self.stdout.write(f"Target coding bank count: {result['coding_bank_target_count']}")
        self.stdout.write(f"Available active coding count: {result['available_active_coding_count']}")
        self.stdout.write(f"Missing bank count: {result['missing_bank_count']}")
        self.stdout.write(f"Status: {result['status']}")
        self.stdout.write(f"Would enqueue coding_generation: {result['would_enqueue']}")
        self.stdout.write(f"Enqueued: {result['enqueued']}")
        if result.get('generation_job_id'):
            self.stdout.write(f"Generation job id: {result['generation_job_id']}")
        if not options['apply']:
            self.stdout.write('Dry run: no DB writes performed. Re-run with --apply to enqueue one coding_generation job.')
