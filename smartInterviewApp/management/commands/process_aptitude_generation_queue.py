from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.models import AptitudeQuestionGenerationJob
from smartInterviewApp.services.aptitude_generation import (
    DEFAULT_APTITUDE_SECTION_CODES,
    enqueue_aptitude_generation_job,
    process_aptitude_generation_queue,
    repair_aptitude_generation_job_statuses,
)


class Command(BaseCommand):
    help = 'Process queued aptitude question-bank generation jobs one batch at a time.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1)
        parser.add_argument('--section', default='')
        parser.add_argument('--target-count', type=int, default=500)
        parser.add_argument('--batch-size', type=int, default=20)
        parser.add_argument('--enqueue-defaults', action='store_true')
        parser.add_argument('--quality-status', default='needs_review')
        parser.add_argument('--role-family', default='')
        parser.add_argument('--skill-tag', default='')
        parser.add_argument('--topic-tag', default='')
        parser.add_argument('--repair-statuses', action='store_true')

    def handle(self, *args, **options):
        try:
            repaired_count = 0
            if options['repair_statuses']:
                repaired_count = repair_aptitude_generation_job_statuses(section_code=options['section'])
            enqueued_count = self._enqueue_defaults_if_requested(options)
            results = process_aptitude_generation_queue(
                limit=options['limit'],
                section_code=options['section'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        summary = self._summarize(results)
        summary['enqueued_count'] = enqueued_count
        summary['repaired_count'] = repaired_count
        for result in results:
            self.stdout.write(str(result))
        self.stdout.write(
            'Summary: '
            f"processed_count={summary['processed_count']} "
            f"completed_count={summary['completed_count']} "
            f"failed_count={summary['failed_count']} "
            f"queued_count={summary['queued_count']} "
            f"accepted_count={summary['accepted_count']} "
            f"rejected_count={summary['rejected_count']} "
            f"enqueued_count={summary['enqueued_count']} "
            f"repaired_count={summary['repaired_count']}"
        )
        self.stdout.write(self.style.SUCCESS('Aptitude generation queue processed.'))

    def _enqueue_defaults_if_requested(self, options):
        if not options['enqueue_defaults']:
            return 0

        section_codes = [options['section']] if options['section'] else DEFAULT_APTITUDE_SECTION_CODES
        count = 0
        for section_code in section_codes:
            enqueue_aptitude_generation_job(
                section_code=section_code,
                target_count=options['target_count'],
                batch_size=options['batch_size'],
                role_family=options['role_family'],
                skill_tag=options['skill_tag'],
                topic_tag=options['topic_tag'],
                quality_status_for_created=options['quality_status'],
            )
            count += 1
        return count

    def _summarize(self, results):
        return {
            'processed_count': len(results),
            'completed_count': sum(
                1 for result in results
                if result.get('status') == AptitudeQuestionGenerationJob.Status.COMPLETED
            ),
            'failed_count': sum(
                1 for result in results
                if result.get('status') == AptitudeQuestionGenerationJob.Status.FAILED
            ),
            'queued_count': sum(
                1 for result in results
                if result.get('status') == AptitudeQuestionGenerationJob.Status.QUEUED
            ),
            'accepted_count': sum(int(result.get('batch_accepted_count') or 0) for result in results),
            'rejected_count': sum(int(result.get('batch_rejected_count') or 0) for result in results),
        }
