from __future__ import annotations

import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import models

from smartInterviewApp.models import CodingQuestion, Interview, JobInterviewBlueprint, JobInterviewSkill, QuestionGenerationJob, SkillQuestion, Vacancies
from smartInterviewApp.services.question_banks import (
    _active_plan_signature,
    _coding_target_plans_for_blueprint,
    _generation_job_matches_active_plan,
    _question_bank_readiness_for_plan,
    _runtime_required_sub_skill_plans,
)


class Command(BaseCommand):
    help = 'Audit question-bank readiness for an interview without modifying data.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--interview-id', type=int)
        group.add_argument('--vacancy-id', type=int)
        group.add_argument('--blueprint-id', type=int)

    def handle(self, *args, **options):
        interview = None
        if options.get('interview_id'):
            interview = (
                Interview.objects
                .select_related('role')
                .filter(id=options['interview_id'])
                .first()
            )
            if not interview:
                raise CommandError(f'Interview not found: {options["interview_id"]}')
            job = interview.role
        elif options.get('vacancy_id'):
            job = Vacancies.objects.filter(id=options['vacancy_id']).first()
            if not job:
                raise CommandError(f'Vacancy not found: {options["vacancy_id"]}')
        else:
            blueprint = JobInterviewBlueprint.objects.select_related('job').filter(id=options['blueprint_id']).first()
            if not blueprint:
                raise CommandError(f'Blueprint not found: {options["blueprint_id"]}')
            job = blueprint.job

        blueprint = None
        plans = []
        top_level_reasons = []

        if options.get('blueprint_id'):
            blueprint = JobInterviewBlueprint.objects.filter(id=options['blueprint_id']).first()
        elif job:
            blueprint = JobInterviewBlueprint.objects.filter(job=job).first()
        else:
            top_level_reasons.append('no_job')

        if blueprint:
            plans = list(
                JobInterviewSkill.objects
                .select_related('skill')
                .filter(blueprint=blueprint, is_active=True, skill__is_active=True)
                .order_by('priority', 'id')
            )
        elif job:
            top_level_reasons.append('no_blueprint')

        blueprint_plan = blueprint.blueprint_plan if blueprint and isinstance(blueprint.blueprint_plan, dict) else {}
        primary_plan = next(
            (plan for plan in plans if plan.skill_role == JobInterviewSkill.SkillRole.PRIMARY),
            None,
        )
        sub_skill_plans = [
            plan for plan in plans
            if plan.skill_role == JobInterviewSkill.SkillRole.SUB_SKILL
        ]
        audits_by_skill_id = {
            plan.skill_id: _question_bank_readiness_for_plan(plan)
            for plan in ([primary_plan] if primary_plan else []) + sub_skill_plans
        }
        runtime_sub_skill_plans, _ = _runtime_required_sub_skill_plans(
            job,
            sub_skill_plans,
            audits_by_skill_id,
            blueprint=blueprint,
        )
        selected_plans = []
        if primary_plan:
            selected_plans.append(primary_plan)
        selected_plans.extend(runtime_sub_skill_plans)

        if blueprint and not selected_plans:
            top_level_reasons.append('no_selected_skills')
        if blueprint and not primary_plan:
            top_level_reasons.append('no_primary_skill')

        coding_target_plans = _coding_target_plans_for_blueprint(blueprint, plans, create_missing=False) if blueprint else []
        active_plan_signature = _active_plan_signature(blueprint) if blueprint else ''
        active_coding_skill_ids = [plan.skill_id for plan in coding_target_plans]
        missing_reasons = list(top_level_reasons)
        for plan in selected_plans:
            audit = _question_bank_readiness_for_plan(plan)
            if audit['reasons']:
                missing_reasons.extend(f'{plan.skill.name}:{reason}' for reason in audit['reasons'])
        if blueprint_plan.get('coding_required'):
            active_coding_total = sum(CodingQuestion.objects.filter(skill=plan.skill, is_active=True).count() for plan in coding_target_plans)
            if active_coding_total < 3:
                missing_reasons.append('coding_questions_missing')
            failed_coding = any(
                _generation_job_matches_active_plan(job, blueprint, active_plan_signature, active_coding_skill_ids)
                for job in QuestionGenerationJob.objects.filter(
                    task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
                    status=QuestionGenerationJob.Status.FAILED,
                    skill_id__in=active_coding_skill_ids,
                )
            )
            if failed_coding:
                missing_reasons.append('coding_generation_failed')

        if interview:
            self.stdout.write(f'Interview: {interview.id}')
        self.stdout.write(f'Vacancy: {job.id if job else ""}')
        self.stdout.write(f'Role: {self._job_title(job)}')
        self.stdout.write(f'Blueprint: {blueprint.id if blueprint else ""}')
        self.stdout.write(f'Blueprint status: {blueprint.status if blueprint else ""}')
        self.stdout.write(f'Role family: {blueprint_plan.get("role_family", "")}')
        self.stdout.write(f'Technical interview: {blueprint_plan.get("technical_interview", "")}')
        self.stdout.write(f'Coding required: {blueprint_plan.get("coding_required", False)}')
        active_coding_target_names = [plan.skill.name for plan in coding_target_plans] if blueprint_plan.get('coding_required') else []
        self.stdout.write(f'Coding skill targets: {", ".join(active_coding_target_names)}')
        quality_warning_codes = self._quality_warning_codes(blueprint_plan)
        self.stdout.write(f'Blueprint quality warnings: {", ".join(quality_warning_codes)}')
        if blueprint_plan.get('quality_issue'):
            self.stdout.write(f'Blueprint quality issue: {blueprint_plan.get("quality_issue")}')
        if blueprint_plan.get('quality_warnings'):
            self.stdout.write(f'Blueprint quality warning details: {json.dumps(blueprint_plan.get("quality_warnings"), sort_keys=True)}')
        self.stdout.write(f'Primary skill: {primary_plan.skill.name if primary_plan else ""}')
        self.stdout.write(f'Selected sub-skills: {", ".join(plan.skill.name for plan in runtime_sub_skill_plans)}')
        optional_names = [plan.skill.name for plan in plans if plan.skill_role == JobInterviewSkill.SkillRole.OPTIONAL]
        self.stdout.write(f'Optional skills: {", ".join(optional_names)}')

        self.stdout.write(f'Status: {"not-ready" if missing_reasons else "ready"}')
        if missing_reasons:
            self.stdout.write(f'Missing reason: {",".join(missing_reasons)}')

        for plan in selected_plans:
            self.stdout.write('')
            self._write_skill_audit(plan)

        if coding_target_plans:
            self.stdout.write('')
            self.stdout.write('Coding targets:')
            for plan in coding_target_plans:
                count = CodingQuestion.objects.filter(skill=plan.skill, is_active=True).count()
                self.stdout.write(f'- {plan.skill.name}: active_coding_count={count}, coding_questions_to_ask={plan.coding_questions_to_ask}')

        if blueprint or job:
            job_filter = {'job': job} if job else {}
            jobs = QuestionGenerationJob.objects.filter(**job_filter)
            if blueprint:
                jobs = QuestionGenerationJob.objects.filter(
                    models.Q(job=job) | models.Q(blueprint=blueprint) | models.Q(skill_id__in=[plan.skill_id for plan in plans])
                )
            job_counts = Counter(jobs.values_list('task_type', 'status'))
            self.stdout.write('')
            self.stdout.write(f'Generation jobs: {json.dumps({f"{task}:{status}": count for (task, status), count in job_counts.items()}, sort_keys=True)}')
            stale_coding_jobs = self._stale_coding_jobs(jobs, blueprint, active_plan_signature, active_coding_skill_ids)
            if stale_coding_jobs:
                stale_skill_ids = {job.skill_id for job in stale_coding_jobs if job.skill_id}
                stale_question_count = (
                    CodingQuestion.objects
                    .filter(skill_id__in=stale_skill_ids, is_active=True)
                    .exclude(skill_id__in=active_coding_skill_ids)
                    .count()
                )
                self.stdout.write('Stale coding jobs/questions ignored:')
                self.stdout.write(f'- jobs={len(stale_coding_jobs)}, active_coding_questions={stale_question_count}')
                for stale_job in stale_coding_jobs[:10]:
                    payload = stale_job.payload if isinstance(stale_job.payload, dict) else {}
                    self.stdout.write(
                        f'- job_id={stale_job.id}, skill={stale_job.skill.name if stale_job.skill else ""}, '
                        f'status={stale_job.status}, plan_signature={payload.get("plan_signature", "")}'
                    )

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
        audit = _question_bank_readiness_for_plan(plan)
        reasons = audit['reasons']
        status = 'not-ready' if reasons else 'ready'

        self.stdout.write(f'Skill: {plan.skill.name} ({plan.skill_role})')
        self.stdout.write(f'Approved count: {approved_count}')
        self.stdout.write(f'Coverage counts: {json.dumps(dict(sorted(coverage_counts.items())), sort_keys=True)}')
        self.stdout.write(f'Question type counts: {json.dumps(dict(sorted(question_type_counts.items())), sort_keys=True)}')
        self.stdout.write(f'Distinct family count: {distinct_family_count}')
        self.stdout.write(f'Target count: {audit["target_count"]}')
        self.stdout.write(f'Coverage ready count: {audit["coverage_ready_count"]}')
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

    def _quality_warning_codes(self, blueprint_plan):
        warnings = blueprint_plan.get('quality_warnings') if isinstance(blueprint_plan, dict) else []
        if not isinstance(warnings, list):
            return []
        codes = []
        for warning in warnings:
            code = warning.get('code') if isinstance(warning, dict) else ''
            if code and code not in codes:
                codes.append(code)
        return codes

    def _stale_coding_jobs(self, jobs, blueprint, active_plan_signature, active_coding_skill_ids):
        if not blueprint:
            return []
        stale = []
        for job in jobs.select_related('skill').filter(task_type=QuestionGenerationJob.TaskType.CODING_GENERATION):
            if not _generation_job_matches_active_plan(job, blueprint, active_plan_signature, active_coding_skill_ids):
                stale.append(job)
        return stale
