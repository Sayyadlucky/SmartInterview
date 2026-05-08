from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.models import CodingQuestion
from smartInterviewApp.services.question_banks import coding_bank_target_count, litio_coding_ask_count, primary_skill_plan_for_interview


class Command(BaseCommand):
    help = 'Preview primary-skill CodingQuestion bank readiness without modifying data.'

    def add_arguments(self, parser):
        parser.add_argument('--interview-id', type=int, required=True)

    def handle(self, *args, **options):
        interview_id = options['interview_id']
        resolved = primary_skill_plan_for_interview(interview_id)
        if not resolved.get('ok'):
            raise CommandError(resolved.get('message') or resolved.get('status') or 'Unable to resolve interview.')

        interview = resolved['interview']
        job = resolved['job']
        skill = resolved['primary_plan'].skill
        target_count = coding_bank_target_count()
        ask_count = litio_coding_ask_count()
        questions = list(
            CodingQuestion.objects
            .filter(skill=skill, is_active=True)
            .order_by('difficulty', 'id')
        )
        selected = questions[:ask_count]
        selected_ids = [question.id for question in selected]
        validation_issues = []
        if len({question.id for question in selected}) != len(selected):
            validation_issues.append('duplicate_question_ids')
        non_active = [question.id for question in selected if not question.is_active]
        if non_active:
            validation_issues.append(f'inactive_selected_rows={non_active}')
        missing_prompt = [question.id for question in selected if not question.prompt]
        if missing_prompt:
            validation_issues.append(f'missing_prompt={missing_prompt}')
        missing_bank_count = max(0, target_count - len(questions))
        if len(questions) < ask_count:
            validation_issues.append('available_count_below_litio_ask_count')

        self.stdout.write(f'Interview: {interview.id}')
        self.stdout.write(f'Role: {job.role or job.position or ""}')
        self.stdout.write(f'Primary skill: {skill.name}')
        self.stdout.write(f'Coding bank target count: {target_count}')
        self.stdout.write(f'Litio ask count: {ask_count}')
        self.stdout.write(f'Available active coding count: {len(questions)}')
        self.stdout.write(f'Missing bank count: {missing_bank_count}')
        self.stdout.write(f'Selected preview coding question IDs: {json.dumps(selected_ids)}')
        self.stdout.write(f'Validation issues: {json.dumps(validation_issues)}')
        self.stdout.write(f'Status: {"ready" if missing_bank_count == 0 and len(questions) >= ask_count else "not-ready"}')
        self.stdout.write('Read-only preview: no DB writes performed.')

        if not questions:
            raise CommandError('Zero usable coding questions for primary skill.')
