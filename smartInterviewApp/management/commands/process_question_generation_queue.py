from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from smartInterviewApp.services.question_banks import process_missing_question_bank_for_interview, process_question_generation_queue


class Command(BaseCommand):
    help = 'Process queued skill-wise interview question generation jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--interview-id', type=int, default=None)
        parser.add_argument('--missing-only', action='store_true')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if options['missing_only']:
            interview_id = options.get('interview_id')
            if not interview_id:
                self.stderr.write('--interview-id is required with --missing-only.')
                return
            result = process_missing_question_bank_for_interview(interview_id, apply=bool(options.get('apply')))
            self._write_missing_only_result(result)
            return

        limit = options['limit']
        if limit is None:
            limit = int(getattr(settings, 'INTERVIEW_QUESTION_BANK_WORKER_LIMIT', 1))
        results = process_question_generation_queue(limit=max(1, limit))
        for result in results:
            self.stdout.write(str(result))
        self.stdout.write(self.style.SUCCESS(f'Processed {len(results)} question generation jobs.'))

    def _write_missing_only_result(self, result):
        self.stdout.write(f"Mode: {'apply' if result.get('apply') else 'preview'}")
        self.stdout.write(f"Interview: {result.get('interview_id', '')}")
        self.stdout.write(f"Role: {result.get('role', '')}")
        self.stdout.write(f"Primary skill: {result.get('primary_skill', '')}")
        self.stdout.write(f"Selected sub-skills: {', '.join(result.get('selected_sub_skills') or [])}")

        self.stdout.write('')
        self.stdout.write('Planned gaps:')
        planned_gaps = result.get('planned_gaps') or []
        if planned_gaps:
            for gap in planned_gaps:
                self.stdout.write(
                    f"- {gap['skill_name']} ({gap['skill_role']}): "
                    f"missing_count={gap['missing_count']}, "
                    f"target_count={gap.get('target_count', '')}, "
                    f"approved_count={gap['approved_count']}, "
                    f"coverage_ready_count={gap.get('coverage_ready_count', '')}, "
                    f"distinct_family_count={gap['distinct_family_count']}, "
                    f"coverage_area_count={gap['coverage_area_count']}, "
                    f"reasons={','.join(gap.get('reasons') or [])}"
                )
        else:
            self.stdout.write('- none')

        self.stdout.write('')
        self.stdout.write('Skipped skills:')
        skipped_skills = result.get('skipped_skills') or []
        if skipped_skills:
            for skipped in skipped_skills:
                self.stdout.write(
                    f"- {skipped['skill_name']} ({skipped['skill_role']}): "
                    f"{skipped['reason']}"
                )
        else:
            self.stdout.write('- none')

        self.stdout.write('')
        self.stdout.write(f"Generated count: {result.get('generated_count', 0)}")
        self.stdout.write(f"Approved count: {result.get('approved_count', 0)}")
        self.stdout.write(f"Rejected count: {result.get('rejected_count', 0)}")
        remaining = result.get('remaining_not_ready_reasons') or []
        self.stdout.write(f"Remaining not-ready reasons: {','.join(remaining) if remaining else 'none'}")
        if not result.get('apply'):
            self.stdout.write('Dry run: no DB writes performed. Re-run with --apply to generate and save approved missing questions.')
