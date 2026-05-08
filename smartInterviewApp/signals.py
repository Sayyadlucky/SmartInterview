from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from smartInterviewApp.models import CandidateResume, CandidateResumeSection, Interview, Vacancies
from smartInterviewApp.services.ai_talent_pool.async_indexer import queue_candidate_reindex
from smartInterviewApp.services.interview_blueprints import schedule_job_interview_blueprint_after_commit


logger = logging.getLogger(__name__)


def _schedule_candidate_reindex(candidate_id: int | None) -> None:
    if not candidate_id:
        return

    def _run():
        try:
            queue_candidate_reindex(candidate_id)
        except Exception:
            logger.exception('Candidate search profile signal reindex queue failed candidate_id=%s', candidate_id)

    transaction.on_commit(_run)


@receiver(post_save, sender=CandidateResume)
def candidate_resume_saved(sender, instance: CandidateResume, **kwargs):
    _schedule_candidate_reindex(instance.candidate_id)


@receiver(post_delete, sender=CandidateResume)
def candidate_resume_deleted(sender, instance: CandidateResume, **kwargs):
    _schedule_candidate_reindex(instance.candidate_id)


@receiver(post_save, sender=CandidateResumeSection)
def candidate_resume_section_saved(sender, instance: CandidateResumeSection, **kwargs):
    _schedule_candidate_reindex(instance.resume.candidate_id if instance.resume_id else None)


@receiver(post_delete, sender=CandidateResumeSection)
def candidate_resume_section_deleted(sender, instance: CandidateResumeSection, **kwargs):
    _schedule_candidate_reindex(instance.resume.candidate_id if instance.resume_id and instance.resume else None)


@receiver(post_save, sender=Interview)
def interview_saved(sender, instance: Interview, **kwargs):
    _schedule_candidate_reindex(instance.candidate_id)


@receiver(post_delete, sender=Interview)
def interview_deleted(sender, instance: Interview, **kwargs):
    _schedule_candidate_reindex(instance.candidate_id)


@receiver(post_save, sender=Vacancies)
def vacancy_saved(sender, instance: Vacancies, created: bool, **kwargs):
    schedule_job_interview_blueprint_after_commit(instance.id)
