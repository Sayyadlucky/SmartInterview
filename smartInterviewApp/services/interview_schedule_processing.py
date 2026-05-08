from __future__ import annotations

import json
import logging
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from smartInterviewApp.models import Interview
from smartInterviewApp.services.cloud_tasks import CloudTasksConfigurationError, CloudTasksScheduler
from smartInterviewApp.services.interview_reminders import InterviewReminderService


logger = logging.getLogger(__name__)


cloud_tasks_scheduler = CloudTasksScheduler()


def _normalize_expected_datetime(value: str | datetime | None):
    if isinstance(value, datetime):
        expected_dt = value
    else:
        expected_dt = parse_datetime(str(value or '').strip())
    if not expected_dt:
        return None
    if timezone.is_naive(expected_dt):
        expected_dt = timezone.make_aware(expected_dt, timezone.get_current_timezone())
    return expected_dt


def process_scheduled_interview(interview_id: int, expected_interview_time: str | datetime) -> dict:
    expected_dt = _normalize_expected_datetime(expected_interview_time)
    if not expected_dt:
        return {
            'ok': False,
            'status': 'invalid_payload',
            'interview_id': interview_id,
            'message': 'Expected interview time is invalid.',
        }

    interview = (
        Interview.objects.select_related('candidate__profile', 'recruiter', 'interviewer', 'role')
        .filter(id=interview_id)
        .first()
    )
    if not interview:
        return {
            'ok': True,
            'status': 'skipped',
            'interview_id': interview_id,
            'message': 'Interview no longer exists.',
        }

    if interview.status != 'scheduled' or not interview.date:
        return {
            'ok': True,
            'status': 'skipped',
            'interview_id': interview_id,
            'message': 'Interview is no longer scheduled.',
        }

    if interview.date != expected_dt:
        return {
            'ok': True,
            'status': 'skipped',
            'interview_id': interview_id,
            'message': 'Interview timing changed before background processing.',
        }

    try:
        InterviewReminderService().reschedule_interview_reminders(interview)
        logger.info(
            'Interview reminder scheduling completed',
            extra={
                'interview_id': interview.id,
            },
        )
        return {
            'ok': True,
            'status': 'processed',
            'interview_id': interview.id,
            'message': 'Interview reminders scheduled.',
        }
    except Exception as exc:
        logger.exception('Interview post-schedule processing failed', extra={'interview_id': interview.id})
        return {
            'ok': False,
            'status': 'failed',
            'interview_id': interview.id,
            'message': str(exc),
        }


def process_scheduled_interview_batch(items: list[dict]) -> list[dict]:
    results: list[dict] = []
    for item in items:
        try:
            interview_id = int(item.get('interview_id'))
        except (TypeError, ValueError):
            results.append({
                'ok': False,
                'status': 'invalid_payload',
                'interview_id': item.get('interview_id'),
                'message': 'Interview id is invalid.',
            })
            continue
        try:
            results.append(process_scheduled_interview(interview_id, item.get('expected_interview_time')))
        except Exception as exc:
            logger.exception('Interview batch processing failed unexpectedly', extra={'interview_id': interview_id})
            results.append({
                'ok': False,
                'status': 'failed',
                'interview_id': interview_id,
                'message': str(exc),
            })
    return results


def queue_scheduled_interview_processing(items: list[dict], scheduler: CloudTasksScheduler | None = None) -> dict:
    if not items:
        return {'queued': False, 'count': 0, 'mode': 'noop', 'results': []}

    scheduler = scheduler or cloud_tasks_scheduler
    task_payload = {'items': items}

    try:
        task_name = scheduler.create_http_task(
            task_id=scheduler.build_task_id(
                'interview-post-schedule',
                timezone.now().isoformat(),
                json.dumps(items, sort_keys=True),
            ),
            relative_path='/internal/tasks/process-scheduled-interviews/',
            payload=task_payload,
            schedule_for=timezone.now(),
        )
        return {
            'queued': True,
            'count': len(items),
            'mode': 'cloud_tasks',
            'task_name': task_name,
        }
    except CloudTasksConfigurationError as exc:
        logger.warning('Cloud Tasks unavailable for interview post-schedule processing, falling back inline', extra={'error': str(exc)})
        return {
            'queued': False,
            'count': len(items),
            'mode': 'inline_fallback',
            'results': process_scheduled_interview_batch(items),
            'error': str(exc),
        }
