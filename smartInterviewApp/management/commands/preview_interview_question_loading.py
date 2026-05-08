from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.models import Interview, JobInterviewBlueprint, JobInterviewSkill, SkillQuestion
from smartInterviewApp.services.question_banks import _question_bank_readiness_for_plan, _runtime_required_sub_skill_plans


PREFERRED_QUESTION_TYPES = {
    SkillQuestion.QuestionType.PRACTICAL,
    SkillQuestion.QuestionType.SCENARIO,
    SkillQuestion.QuestionType.DEBUGGING,
}


class Command(BaseCommand):
    help = 'Preview DB-only interview question loading without modifying data.'

    def add_arguments(self, parser):
        parser.add_argument('--interview-id', type=int, required=True)

    def handle(self, *args, **options):
        interview_id = options['interview_id']
        interview = Interview.objects.select_related('role').filter(id=interview_id).first()
        if not interview:
            raise CommandError(f'Interview not found: {interview_id}')
        job = interview.role
        if not job:
            raise CommandError(f'Interview {interview_id} has no related job.')
        blueprint = JobInterviewBlueprint.objects.filter(job=job).first()
        if not blueprint:
            raise CommandError(f'No JobInterviewBlueprint found for interview {interview_id}.')

        plans = list(
            JobInterviewSkill.objects
            .select_related('skill')
            .filter(blueprint=blueprint, is_active=True, skill__is_active=True)
            .order_by('priority', 'id')
        )
        primary_plan = next((plan for plan in plans if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY), None)
        sub_skill_plans = [plan for plan in plans if plan.skill_role == JobInterviewSkill.SkillRole.SUB_SKILL]
        audits_by_skill_id = {
            plan.skill_id: _question_bank_readiness_for_plan(plan)
            for plan in ([primary_plan] if primary_plan else []) + sub_skill_plans
        }
        runtime_sub_skills, skip_reasons = _runtime_required_sub_skill_plans(job, sub_skill_plans, audits_by_skill_id)
        selected_plans = ([primary_plan] if primary_plan else []) + runtime_sub_skills

        skipped = []
        runtime_sub_skill_ids = {plan.skill_id for plan in runtime_sub_skills}
        for plan in sub_skill_plans:
            if plan.skill_id not in runtime_sub_skill_ids:
                skipped.append({
                    'skill_name': plan.skill.name,
                    'skill_role': plan.skill_role,
                    'reason': skip_reasons.get(plan.skill_id, 'outside_runtime_required_scope'),
                })

        primary_target = max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_PRIMARY_QUESTIONS', 5) or 5))
        sub_skill_target = max(1, int(getattr(settings, 'INTERVIEW_RUNTIME_SUB_SKILL_QUESTIONS', 3) or 3))
        selected_ids = set()
        sections = []
        duplicate_selected_ids = []
        non_approved_selected_ids = []
        inactive_selected_ids = []
        empty_coverage_area_count = 0
        sections_below_target = []
        zero_usable_sections = []

        for plan in selected_plans:
            if not plan:
                continue
            target = primary_target if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY else sub_skill_target
            questions = list(
                SkillQuestion.objects
                .filter(
                    skill=plan.skill,
                    is_active=True,
                    quality_status=SkillQuestion.QualityStatus.APPROVED,
                )
                .order_by('id')
            )
            selected = select_preview_questions(questions, target, selected_ids)
            for question in selected:
                if question.id in selected_ids:
                    duplicate_selected_ids.append(question.id)
                selected_ids.add(question.id)
                if question.quality_status != SkillQuestion.QualityStatus.APPROVED:
                    non_approved_selected_ids.append(question.id)
                if not question.is_active:
                    inactive_selected_ids.append(question.id)
                if not question.coverage_area:
                    empty_coverage_area_count += 1

            selected_question_ids = [question.id for question in selected]
            if len(selected) < target:
                sections_below_target.append(plan.skill.name)
            if not selected:
                zero_usable_sections.append(plan.skill.name)
            sections.append({
                'skill_name': plan.skill.name,
                'skill_role': plan.skill_role,
                'target_count': target,
                'available_approved_count': len(questions),
                'selected_question_ids': selected_question_ids,
                'selected_family_keys': [question.family_key for question in selected],
                'selected_coverage_areas': [question.coverage_area for question in selected],
                'selected_question_types': [question.question_type for question in selected],
                'readiness_status': 'ready' if len(selected) >= target else 'not-ready',
            })

        self.stdout.write(f'Interview: {interview.id}')
        self.stdout.write(f'Role: {job.role or job.position or ""}')
        self.stdout.write(f'Primary skill: {primary_plan.skill.name if primary_plan else ""}')
        self.stdout.write(f'Runtime sub-skills: {", ".join(plan.skill.name for plan in runtime_sub_skills)}')
        self.stdout.write('Skipped skills:')
        if skipped:
            for item in skipped:
                self.stdout.write(f"- {item['skill_name']} ({item['skill_role']}): {item['reason']}")
        else:
            self.stdout.write('- none')

        self.stdout.write('')
        self.stdout.write('Selected sections:')
        for section in sections:
            self.stdout.write(f"Skill: {section['skill_name']} ({section['skill_role']})")
            self.stdout.write(f"Target count: {section['target_count']}")
            self.stdout.write(f"Available approved count: {section['available_approved_count']}")
            self.stdout.write(f"Selected question IDs: {json.dumps(section['selected_question_ids'])}")
            self.stdout.write(f"Selected family_keys: {json.dumps(section['selected_family_keys'])}")
            self.stdout.write(f"Selected coverage_areas: {json.dumps(section['selected_coverage_areas'])}")
            self.stdout.write(f"Selected question_type: {json.dumps(section['selected_question_types'])}")
            self.stdout.write(f"Readiness status: {section['readiness_status']}")
            self.stdout.write('')

        self.stdout.write('Validation summary:')
        self.stdout.write(f'Duplicate question IDs: {json.dumps(sorted(set(duplicate_selected_ids)))}')
        self.stdout.write(f'Non-approved selected rows: {json.dumps(sorted(set(non_approved_selected_ids)))}')
        self.stdout.write(f'Inactive selected rows: {json.dumps(sorted(set(inactive_selected_ids)))}')
        self.stdout.write(f'Empty coverage_area count: {empty_coverage_area_count}')
        self.stdout.write(f'Sections below target: {json.dumps(sections_below_target)}')
        self.stdout.write('Read-only preview: no DB writes performed.')

        if zero_usable_sections:
            raise CommandError(f'Zero usable questions for runtime-required sections: {", ".join(zero_usable_sections)}')


def select_preview_questions(questions, target, already_selected_ids):
    selected = []
    selected_family_keys = set()
    for question in sorted(questions, key=question_sort_key):
        if question.id in already_selected_ids:
            continue
        family_key = question.family_key or ''
        if family_key and family_key in selected_family_keys:
            continue
        selected.append(question)
        if family_key:
            selected_family_keys.add(family_key)
        if len(selected) >= target:
            return selected

    for question in sorted(questions, key=question_sort_key):
        if question.id in already_selected_ids or question in selected:
            continue
        selected.append(question)
        if len(selected) >= target:
            return selected
    return selected


def question_sort_key(question):
    return (
        0 if question.coverage_area else 1,
        0 if question.question_type in PREFERRED_QUESTION_TYPES else 1,
        family_frequency_rank(question),
        question.id,
    )


def family_frequency_rank(question):
    return 0 if question.family_key else 1
