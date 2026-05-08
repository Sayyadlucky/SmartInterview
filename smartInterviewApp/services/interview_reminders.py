from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from smartInterviewApp.models import Interview, InterviewReminderDelivery
from smartInterviewApp.notifications.channels import send_sms, send_template_message
from smartInterviewApp.services.cloud_tasks import CloudTasksConfigurationError, CloudTasksScheduler


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReminderSpec:
    reminder_type: str
    offset_minutes: int
    whatsapp_template: str


REMINDER_SPECS: tuple[ReminderSpec, ...] = (
    ReminderSpec(
        reminder_type=InterviewReminderDelivery.ReminderType.ONE_HOUR,
        offset_minutes=60,
        whatsapp_template=settings.INTERVIEW_REMINDER_ONE_HOUR_WHATSAPP_TEMPLATE,
    ),
    ReminderSpec(
        reminder_type=InterviewReminderDelivery.ReminderType.THIRTY_MIN,
        offset_minutes=30,
        whatsapp_template=settings.INTERVIEW_REMINDER_THIRTY_MIN_WHATSAPP_TEMPLATE,
    ),
    ReminderSpec(
        reminder_type=InterviewReminderDelivery.ReminderType.FIFTEEN_MIN,
        offset_minutes=15,
        whatsapp_template=settings.INTERVIEW_REMINDER_FIFTEEN_MIN_WHATSAPP_TEMPLATE,
    ),
)

CHANNELS: tuple[str, ...] = (
    InterviewReminderDelivery.Channel.SMS,
    InterviewReminderDelivery.Channel.WHATSAPP,
)

cloud_tasks_scheduler = CloudTasksScheduler()


def normalize_phone(value: str) -> str:
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(digits) == 10:
        return f'91{digits}'
    return digits


def clean_value(value: str, fallback: str) -> str:
    text = ' '.join(str(value or '').split()).strip()
    return text or fallback


def format_interview_time(value) -> str:
    if not value:
        return 'the scheduled time'
    return timezone.localtime(value).strftime('%I:%M %p').lstrip('0')


def get_sms_template_id(reminder_type: str) -> str:
    mapping = {
        InterviewReminderDelivery.ReminderType.ONE_HOUR: getattr(settings, 'MSG91_INTERVIEW_REMINDER_ONE_HOUR_TEMPLATE_ID', ''),
        InterviewReminderDelivery.ReminderType.THIRTY_MIN: getattr(settings, 'MSG91_INTERVIEW_REMINDER_THIRTY_MIN_TEMPLATE_ID', ''),
        InterviewReminderDelivery.ReminderType.FIFTEEN_MIN: getattr(settings, 'MSG91_INTERVIEW_REMINDER_FIFTEEN_MIN_TEMPLATE_ID', ''),
    }
    return str(mapping.get(reminder_type, '') or '').strip()


def build_litio_join_link(interview: Interview) -> str:
    from smartInterviewApp.commonViews import ensure_litio_interview_token

    token = ensure_litio_interview_token(interview)
    base_url = getattr(settings, 'LITIO_PUBLIC_BASE_URL', 'https://litio.shortlistii.com').rstrip('/')
    return f'{base_url}/i/{token}'


def build_reminder_message(
    reminder_type: str,
    candidate_name: str,
    role_name: str,
    interview_time: str,
    join_link: str = '',
) -> str:
    if reminder_type == InterviewReminderDelivery.ReminderType.ONE_HOUR:
        return (
            f"Hello {candidate_name}, reminder that your interview for {role_name} is scheduled at {interview_time}. "
            f"Please ensure your profile is completed and verified before the interview or you may not be able to join. "
            f"Kindly be ready 5-10 minutes early. Regards Team Shortlistii"
        )
    if reminder_type == InterviewReminderDelivery.ReminderType.THIRTY_MIN:
        return (
            f"Hello {candidate_name}, your interview for {role_name} starts in 30 minutes at {interview_time}. "
            f"Please ensure your profile is completed and verified otherwise you may not be able to join the interview. "
            f"Regards Team Shortlistii"
        )
    join_line = f" Please join using {join_link} or stay available now." if join_link else " Please join or stay available now."
    return (
        f"Hello {candidate_name}, your interview for {role_name} begins in 15 minutes.{join_line} "
        f"Wishing you the very best for your interview. Regards Team Shortlistii"
    )


def build_whatsapp_parameters(
    reminder_type: str,
    candidate_name: str,
    role_name: str,
    interview_time: str,
    join_link: str = '',
) -> list[str]:
    parameters = [candidate_name, role_name, interview_time]
    if reminder_type == InterviewReminderDelivery.ReminderType.FIFTEEN_MIN and join_link:
        parameters.append(join_link)
    return parameters


def send_whatsapp_template(phone: str, template_name: str, parameters: list[str], metadata: dict | None = None) -> dict:
    components = [{
        'type': 'body',
        'parameters': [{'type': 'text', 'text': str(value or '').strip()} for value in parameters],
    }]
    result = send_template_message(
        to=phone,
        template_name=template_name,
        language_code=getattr(settings, 'DEFAULT_WHATSAPP_LANGUAGE_CODE', 'en'),
        components=components,
        metadata=metadata or {},
    )
    return {
        'success': result.success,
        'provider_message_id': result.provider_message_id,
        'response_payload': result.response_payload,
        'error_message': result.error_message or '',
        'template_name': template_name,
    }


class InterviewReminderService:
    def __init__(self, scheduler: CloudTasksScheduler | None = None):
        self.scheduler = scheduler or cloud_tasks_scheduler

    def schedule_interview_reminders(self, interview: Interview) -> list[InterviewReminderDelivery]:
        interview = Interview.objects.select_related('candidate__profile', 'role').get(id=interview.id)
        if interview.status != 'scheduled' or not interview.date:
            logger.info('Interview reminders not scheduled for inactive interview', extra={'interview_id': interview.id, 'status': interview.status})
            return []

        deliveries: list[InterviewReminderDelivery] = []
        now = timezone.now()
        grace_seconds = max(0, int(settings.INTERVIEW_REMINDER_GRACE_SECONDS))
        grace_cutoff = now - timedelta(seconds=grace_seconds)

        for spec in REMINDER_SPECS:
            scheduled_for = interview.date - timedelta(minutes=spec.offset_minutes)
            for channel in CHANNELS:
                status = InterviewReminderDelivery.Status.PENDING
                error_message = ''
                task_schedule_for = scheduled_for
                if scheduled_for < grace_cutoff:
                    status = InterviewReminderDelivery.Status.SKIPPED
                    error_message = 'Reminder window is already in the past.'
                elif scheduled_for < now:
                    task_schedule_for = now

                delivery, _ = InterviewReminderDelivery.objects.get_or_create(
                    interview=interview,
                    reminder_type=spec.reminder_type,
                    channel=channel,
                    expected_interview_time=interview.date,
                    defaults={
                        'scheduled_for': task_schedule_for,
                        'status': status,
                        'error_message': error_message,
                    },
                )

                if delivery.status == InterviewReminderDelivery.Status.SENT:
                    deliveries.append(delivery)
                    continue
                if (
                    delivery.status == InterviewReminderDelivery.Status.PENDING
                    and delivery.cloud_task_name
                    and delivery.expected_interview_time == interview.date
                    and delivery.scheduled_for == task_schedule_for
                ):
                    deliveries.append(delivery)
                    continue

                delivery.scheduled_for = task_schedule_for
                delivery.status = status
                delivery.error_message = error_message
                delivery.sent_at = None
                delivery.provider_response = {}

                if status == InterviewReminderDelivery.Status.SKIPPED:
                    delivery.cloud_task_name = ''
                    delivery.save(update_fields=['scheduled_for', 'status', 'error_message', 'sent_at', 'provider_response', 'cloud_task_name', 'updated_at'])
                    deliveries.append(delivery)
                    continue

                payload = {
                    'interview_id': interview.id,
                    'reminder_type': spec.reminder_type,
                    'channel': channel,
                    'expected_interview_time': interview.date.isoformat(),
                }
                task_id = self.scheduler.build_task_id(
                    'interview-reminder',
                    interview.id,
                    spec.reminder_type,
                    channel,
                    interview.date.isoformat(),
                )
                try:
                    task_name = self.scheduler.create_http_task(
                        task_id=task_id,
                        relative_path='/internal/tasks/send-interview-reminder/',
                        payload=payload,
                        schedule_for=task_schedule_for,
                    )
                    delivery.cloud_task_name = task_name
                    delivery.save(update_fields=['scheduled_for', 'status', 'error_message', 'sent_at', 'provider_response', 'cloud_task_name', 'updated_at'])
                    logger.info('Interview reminder scheduled', extra={'interview_id': interview.id, 'reminder_type': spec.reminder_type, 'channel': channel, 'task_name': task_name})
                except CloudTasksConfigurationError as exc:
                    delivery.status = InterviewReminderDelivery.Status.FAILED
                    delivery.error_message = str(exc)
                    delivery.cloud_task_name = ''
                    delivery.save(update_fields=['scheduled_for', 'status', 'error_message', 'sent_at', 'provider_response', 'cloud_task_name', 'updated_at'])
                    logger.error('Interview reminder scheduling failed', extra={'interview_id': interview.id, 'reminder_type': spec.reminder_type, 'channel': channel, 'error': str(exc)})
                deliveries.append(delivery)

        return deliveries

    def cancel_pending_interview_reminders(self, interview: Interview, reason: str = 'Interview no longer active') -> int:
        deliveries = list(
            InterviewReminderDelivery.objects.filter(
                interview=interview,
                status__in=[InterviewReminderDelivery.Status.PENDING, InterviewReminderDelivery.Status.FAILED],
            )
        )
        for delivery in deliveries:
            if delivery.cloud_task_name:
                self.scheduler.delete_task(delivery.cloud_task_name)
            delivery.status = InterviewReminderDelivery.Status.CANCELLED
            delivery.error_message = reason
            delivery.cloud_task_name = ''
            delivery.save(update_fields=['status', 'error_message', 'cloud_task_name', 'updated_at'])
        if deliveries:
            logger.info('Interview reminders cancelled', extra={'interview_id': interview.id, 'count': len(deliveries), 'reason': reason})
        return len(deliveries)

    def reschedule_interview_reminders(self, interview: Interview) -> list[InterviewReminderDelivery]:
        self.cancel_pending_interview_reminders(interview, reason='Interview rescheduled')
        return self.schedule_interview_reminders(interview)

    def execute_interview_reminder(self, *, interview_id: int, reminder_type: str, channel: str, expected_interview_time: str):
        expected_dt = parse_datetime(expected_interview_time or '')
        if not expected_dt:
            return {'ok': False, 'status': 'invalid_payload', 'retryable': False, 'message': 'Expected interview time is invalid.'}
        if timezone.is_naive(expected_dt):
            expected_dt = timezone.make_aware(expected_dt, timezone.get_current_timezone())

        with transaction.atomic():
            delivery = (
                InterviewReminderDelivery.objects.select_for_update()
                .select_related('interview__candidate__profile', 'interview__role')
                .filter(
                    interview_id=interview_id,
                    reminder_type=reminder_type,
                    channel=channel,
                    expected_interview_time=expected_dt,
                )
                .first()
            )
            if not delivery:
                return {'ok': True, 'status': 'skipped', 'retryable': False, 'message': 'Reminder delivery record not found.'}
            if delivery.status == InterviewReminderDelivery.Status.SENT:
                return {'ok': True, 'status': 'already_sent', 'retryable': False, 'message': 'Reminder already sent.'}
            if delivery.status in {InterviewReminderDelivery.Status.CANCELLED, InterviewReminderDelivery.Status.SKIPPED}:
                return {'ok': True, 'status': delivery.status, 'retryable': False, 'message': 'Reminder is no longer active.'}

            interview = delivery.interview
            if interview.status != 'scheduled' or not interview.date:
                delivery.status = InterviewReminderDelivery.Status.CANCELLED
                delivery.error_message = 'Interview is no longer scheduled.'
                delivery.cloud_task_name = ''
                delivery.save(update_fields=['status', 'error_message', 'cloud_task_name', 'updated_at'])
                return {'ok': True, 'status': 'cancelled', 'retryable': False, 'message': delivery.error_message}

            if interview.date != expected_dt:
                delivery.status = InterviewReminderDelivery.Status.CANCELLED
                delivery.error_message = 'Interview time changed before reminder delivery.'
                delivery.cloud_task_name = ''
                delivery.save(update_fields=['status', 'error_message', 'cloud_task_name', 'updated_at'])
                return {'ok': True, 'status': 'cancelled', 'retryable': False, 'message': delivery.error_message}

            stale_after = max(0, int(settings.INTERVIEW_REMINDER_STALE_AFTER_SECONDS))
            if timezone.now() > interview.date + timedelta(seconds=stale_after):
                delivery.status = InterviewReminderDelivery.Status.SKIPPED
                delivery.error_message = 'Reminder became stale after interview start.'
                delivery.cloud_task_name = ''
                delivery.save(update_fields=['status', 'error_message', 'cloud_task_name', 'updated_at'])
                return {'ok': True, 'status': 'skipped', 'retryable': False, 'message': delivery.error_message}

            candidate_profile = getattr(interview.candidate, 'profile', None)
            phone = normalize_phone(getattr(candidate_profile, 'phone', '') or '')
            if len(phone) < 12:
                delivery.status = InterviewReminderDelivery.Status.SKIPPED
                delivery.error_message = 'Candidate phone number is missing.'
                delivery.cloud_task_name = ''
                delivery.save(update_fields=['status', 'error_message', 'cloud_task_name', 'updated_at'])
                return {'ok': True, 'status': 'skipped', 'retryable': False, 'message': delivery.error_message}

            candidate_name = clean_value(getattr(interview.candidate, 'first_name', ''), 'Candidate')
            role_name = clean_value(getattr(getattr(interview, 'role', None), 'role', ''), 'your scheduled role')
            interview_time = format_interview_time(interview.date)
            join_link = build_litio_join_link(interview) if delivery.reminder_type == InterviewReminderDelivery.ReminderType.FIFTEEN_MIN else ''
            message = build_reminder_message(delivery.reminder_type, candidate_name, role_name, interview_time, join_link)
            metadata = {
                'event_type': f'interview_reminder_{delivery.reminder_type}',
                'interview_id': interview.id,
                'reminder_type': delivery.reminder_type,
                'channel': delivery.channel,
            }

            if delivery.channel == InterviewReminderDelivery.Channel.SMS:
                flow_variables = {
                    'name': candidate_name,
                    'role': role_name,
                }
                if delivery.reminder_type in {
                    InterviewReminderDelivery.ReminderType.ONE_HOUR,
                    InterviewReminderDelivery.ReminderType.THIRTY_MIN,
                }:
                    flow_variables['time'] = interview_time
                if delivery.reminder_type == InterviewReminderDelivery.ReminderType.FIFTEEN_MIN:
                    flow_variables['url'] = join_link or ''
                provider_result = send_sms(
                    phone,
                    message,
                    metadata={
                        **metadata,
                        'msg91_template_id': get_sms_template_id(delivery.reminder_type),
                        'msg91_flow_variables': flow_variables,
                    },
                )
                success = provider_result.success
                provider_message_id = provider_result.provider_message_id
                response_payload = provider_result.response_payload
                error_message = provider_result.error_message or ''
            else:
                template_name = next(spec.whatsapp_template for spec in REMINDER_SPECS if spec.reminder_type == delivery.reminder_type)
                whatsapp_result = send_whatsapp_template(
                    phone=phone,
                    template_name=template_name,
                    parameters=build_whatsapp_parameters(delivery.reminder_type, candidate_name, role_name, interview_time, join_link),
                    metadata=metadata,
                )
                success = whatsapp_result['success']
                provider_message_id = whatsapp_result.get('provider_message_id', '')
                response_payload = whatsapp_result
                error_message = whatsapp_result.get('error_message', '')

            delivery.cloud_task_name = ''
            delivery.provider_response = {
                'provider_message_id': provider_message_id,
                'response': response_payload,
                'message': message,
            }
            delivery.error_message = error_message
            if success:
                delivery.status = InterviewReminderDelivery.Status.SENT
                delivery.sent_at = timezone.now()
                delivery.save(update_fields=['cloud_task_name', 'provider_response', 'error_message', 'status', 'sent_at', 'updated_at'])
                logger.info('Interview reminder sent', extra={'delivery_id': delivery.id, 'interview_id': interview.id, 'channel': delivery.channel, 'reminder_type': delivery.reminder_type})
                return {'ok': True, 'status': 'sent', 'retryable': False, 'message': 'Reminder sent successfully.'}

            delivery.status = InterviewReminderDelivery.Status.FAILED
            delivery.sent_at = None
            delivery.save(update_fields=['cloud_task_name', 'provider_response', 'error_message', 'status', 'sent_at', 'updated_at'])
            logger.warning('Interview reminder failed', extra={'delivery_id': delivery.id, 'interview_id': interview.id, 'channel': delivery.channel, 'reminder_type': delivery.reminder_type, 'error': error_message})
            return {'ok': False, 'status': 'failed', 'retryable': True, 'message': error_message or 'Reminder delivery failed.'}
