from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.services.aptitude_generation import (
    DEFAULT_APTITUDE_SECTION_CODES,
    enqueue_aptitude_generation_job,
)


class Command(BaseCommand):
    help = 'Enqueue aptitude question-bank generation jobs without processing them.'

    def add_arguments(self, parser):
        section_mode = parser.add_mutually_exclusive_group(required=True)
        section_mode.add_argument('--section')
        section_mode.add_argument('--all-default-sections', action='store_true')
        parser.add_argument('--target-count', type=int, default=500)
        parser.add_argument('--batch-size', type=int, default=20)
        parser.add_argument('--quality-status', default='needs_review')
        parser.add_argument('--role-family', default='')
        parser.add_argument('--skill-tag', default='')
        parser.add_argument('--topic-tag', default='')

    def handle(self, *args, **options):
        section_codes = (
            DEFAULT_APTITUDE_SECTION_CODES
            if options['all_default_sections']
            else [options['section']]
        )
        created_or_reused = []
        try:
            for section_code in section_codes:
                job = enqueue_aptitude_generation_job(
                    section_code=section_code,
                    target_count=options['target_count'],
                    batch_size=options['batch_size'],
                    role_family=options['role_family'],
                    skill_tag=options['skill_tag'],
                    topic_tag=options['topic_tag'],
                    quality_status_for_created=options['quality_status'],
                )
                created_or_reused.append(job)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        for job in created_or_reused:
            self.stdout.write(
                f'Job {job.id}: section={job.section.code} status={job.status} '
                f'target_count={job.target_count} batch_size={job.batch_size}'
            )
        self.stdout.write(self.style.SUCCESS(f'Enqueued/reused {len(created_or_reused)} aptitude generation job(s).'))
