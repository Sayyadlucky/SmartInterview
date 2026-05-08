from __future__ import annotations

import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.models import Interview, JobInterviewBlueprint, JobInterviewSkill, SkillQuestion


class Command(BaseCommand):
    help = 'Audit question-bank readiness for an interview without modifying data.'

    def add_arguments(self, parser):
        parser.add_argument('--interview-id', type=int, required=True)

    def handle(self, *args, **options):
        interview_id = options['interview_id']
        interview = (
            Interview.objects
            .select_related('role')
            .filter(id=interview_id)
            .first()
        )
        if not interview:
            raise CommandError(f'Interview not found: {interview_id}')

        job = interview.role
        blueprint = None
        plans = []
        top_level_reasons = []

        if job:
            blueprint = JobInterviewBlueprint.objects.filter(job=job).first()
            if blueprint:
                plans = list(
                    JobInterviewSkill.objects
                    .select_related('skill')
                    .filter(blueprint=blueprint, is_active=True, skill__is_active=True)
                    .order_by('priority', 'id')
                )
            else:
                top_level_reasons.append('no_blueprint')
        else:
            top_level_reasons.append('no_job')

        primary_plan = next(
            (plan for plan in plans if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY),
            None,
        )
        sub_skill_plans = [
            plan for plan in plans
            if plan.skill_role == JobInterviewSkill.SkillRole.SUB_SKILL
        ]
        selected_plans = []
        if primary_plan:
            selected_plans.append(primary_plan)
        selected_plans.extend(sub_skill_plans)

        if blueprint and not selected_plans:
            top_level_reasons.append('no_selected_skills')
        if blueprint and not primary_plan:
            top_level_reasons.append('no_primary_skill')

        self.stdout.write(f'Interview: {interview.id}')
        self.stdout.write(f'Role: {self._job_title(job)}')
        self.stdout.write(f'Primary skill: {primary_plan.skill.name if primary_plan else ""}')
        self.stdout.write(f'Selected sub-skills: {", ".join(plan.skill.name for plan in sub_skill_plans)}')

        if top_level_reasons:
            self.stdout.write(f'Status: not-ready')
            self.stdout.write(f'Not-ready reason: {",".join(top_level_reasons)}')

        for plan in selected_plans:
            self.stdout.write('')
            self._write_skill_audit(plan)

    def _write_skill_audit(self, plan):
        questions = SkillQuestion.objects.filter(
            skill=plan.skill,
            is_active=True,
            quality_status=SkillQuestion.QualityStatus.APPROVED,
        )
        approved_count = questions.count()
        coverage_counts = Counter(
            value for value in questions.values_list('coverage_area', flat=True)
            if value
        )
        question_type_counts = Counter(
            value for value in questions.values_list('question_type', flat=True)
            if value
        )
        distinct_family_count = (
            questions
            .exclude(family_key='')
            .values('family_key')
            .distinct()
            .count()
        )
        reasons = self._readiness_reasons(
            plan.skill_role,
            approved_count,
            len(coverage_counts),
            distinct_family_count,
        )
        status = 'not-ready' if reasons else 'ready'

        self.stdout.write(f'Skill: {plan.skill.name} ({plan.skill_role})')
        self.stdout.write(f'Approved count: {approved_count}')
        self.stdout.write(f'Coverage counts: {json.dumps(dict(sorted(coverage_counts.items())), sort_keys=True)}')
        self.stdout.write(f'Question type counts: {json.dumps(dict(sorted(question_type_counts.items())), sort_keys=True)}')
        self.stdout.write(f'Distinct family count: {distinct_family_count}')
        self.stdout.write(f'Status: {status}')
        if reasons:
            self.stdout.write(f'Not-ready reason: {",".join(reasons)}')

    def _readiness_reasons(self, skill_role, approved_count, coverage_area_count, distinct_family_count):
        reasons = []
        if skill_role == JobInterviewSkill.SkillRole.PRIMARY:
            if approved_count < 12:
                reasons.append('approved_question_count_below_12')
            if coverage_area_count == 0:
                reasons.append('coverage_area_missing_or_unclassified')
            elif coverage_area_count < 5:
                reasons.append('coverage_area_count_too_low')
        elif skill_role == JobInterviewSkill.SkillRole.SUB_SKILL:
            if approved_count < 4:
                reasons.append('approved_question_count_below_4')
            if coverage_area_count == 0:
                reasons.append('coverage_area_missing_or_unclassified')
            if distinct_family_count < 2:
                reasons.append('distinct_family_count_too_low')
        return reasons

    def _job_title(self, job):
        if not job:
            return ''
        return job.role or job.position or ''
