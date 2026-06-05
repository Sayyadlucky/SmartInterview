from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from smartInterviewApp.integrations.providers.contracts import ProviderResult
from smartInterviewApp.integrations.providers.exotel import ExotelVoiceProvider
from smartInterviewApp.models import Interview, InterviewCallSession


logger = logging.getLogger(__name__)

exotel_voice_provider = ExotelVoiceProvider()

ACTIVE_STATUSES = {
    InterviewCallSession.Status.DIALING_AGENT,
    InterviewCallSession.Status.CONNECTING_CANDIDATE,
    InterviewCallSession.Status.IN_PROGRESS,
}
LIVE_LEG_STATUSES = {'in-progress', 'completed', 'answered', 'active', 'connected'}
RINGING_LEG_STATUSES = {'queued', 'ringing', 'initiated', 'dialing'}

UNSUPPORTED_DISCONNECT_MESSAGE = 'Exotel does not allow ending this live call through the current API flow.'
WEBHOOK_HISTORY_LIMIT = 25
VALID_OUTCOMES = {'connected', 'no_answer', 'busy', 'wrong_number', 'not_reachable'}


def _normalize_status(value: str) -> str:
    return (value or '').strip().lower().replace('_', '-')


def _parse_exotel_datetime(value: Any):
    raw = str(value or '').strip()
    if not raw:
        return None
    parsed = parse_datetime(raw.replace(' ', 'T'))
    if not parsed:
        return None
    if timezone.is_naive(parsed):
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(getattr(settings, 'EXOTEL_TIMEZONE', 'Asia/Kolkata') or 'Asia/Kolkata'))
        except Exception:
            parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _seconds_to_datetime(reference: datetime, total_seconds: int):
    if total_seconds <= 0:
        return None
    return reference - timedelta(seconds=total_seconds)


def _extract_call_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    call = payload.get('Call')
    return call if isinstance(call, dict) else payload


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _mask_phone(value: str) -> str:
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(digits) <= 4:
        return digits
    return f"{'•' * max(len(digits) - 4, 4)}{digits[-4:]}"


def _user_display_name(user: User | None) -> str:
    if not user:
        return ''
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name.title() if full_name else (user.email or user.username or '')


def _disconnect_supported(session: InterviewCallSession) -> bool:
    if session.status not in ACTIVE_STATUSES:
        return False
    provider_response = session.provider_response if isinstance(session.provider_response, dict) else {}
    return not bool(provider_response.get('disconnect_control_unsupported'))


def _disconnect_unavailable_reason(session: InterviewCallSession) -> str:
    provider_response = session.provider_response if isinstance(session.provider_response, dict) else {}
    if provider_response.get('disconnect_control_unsupported'):
        return 'Live disconnect is not available for the current Exotel call flow. Please end the call from your phone.'
    return ''


def _append_webhook_event(provider_response: dict[str, Any] | None, payload: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(provider_response or {})
    event_entry = {
        'received_at': timezone.now().isoformat(),
        'payload': payload or {},
    }
    existing = base.get('webhook_events')
    if isinstance(existing, list):
        history = existing[-(WEBHOOK_HISTORY_LIMIT - 1):]
    else:
        history = []
    history.append(event_entry)
    base['webhook_events'] = history
    return base


class InterviewCallService:
    def __init__(self, provider: ExotelVoiceProvider | None = None):
        self.provider = provider or exotel_voice_provider

    def create_session(
        self,
        *,
        interview: Interview,
        initiated_by: User,
        caller_phone: str,
        candidate_phone: str,
        provider_result: ProviderResult,
    ) -> InterviewCallSession:
        payload = provider_result.response_payload or {}
        session = InterviewCallSession.objects.create(
            interview=interview,
            initiated_by=initiated_by,
            exotel_call_sid=provider_result.provider_message_id or '',
            status=InterviewCallSession.Status.DIALING_AGENT,
            caller_phone=caller_phone,
            candidate_phone=candidate_phone,
            provider_response={'start_response': payload},
            error_message=provider_result.error_message or '',
        )
        return session

    def get_session(self, *, user: User, interview_id: int, session_id: int) -> InterviewCallSession | None:
        from smartInterviewApp.commonViews import get_accessible_interviews

        return (
            InterviewCallSession.objects.select_related('interview', 'interview__candidate', 'initiated_by')
            .filter(id=session_id, interview_id=interview_id, interview__in=get_accessible_interviews(user))
            .first()
        )

    def list_sessions(self, *, user: User, interview_id: int, limit: int = 20) -> list[InterviewCallSession]:
        from smartInterviewApp.commonViews import get_accessible_interviews

        return list(
            InterviewCallSession.objects.select_related('interview', 'interview__candidate', 'initiated_by')
            .filter(interview_id=interview_id, interview__in=get_accessible_interviews(user))
            .order_by('-created_at', '-id')[:limit]
        )

    def serialize_session(self, session: InterviewCallSession) -> dict[str, Any]:
        now = timezone.now()
        billable_seconds = session.billable_seconds
        connected_seconds = session.connected_seconds
        provider_response = session.provider_response if isinstance(session.provider_response, dict) else {}
        webhook_events = provider_response.get('webhook_events') if isinstance(provider_response.get('webhook_events'), list) else []
        last_webhook_payload = webhook_events[-1]['payload'] if webhook_events else {}
        if session.status in ACTIVE_STATUSES:
            if session.billing_started_at:
                billable_seconds = max(billable_seconds, int((now - session.billing_started_at).total_seconds()))
            if session.candidate_connected_at:
                connected_seconds = max(connected_seconds, int((now - session.candidate_connected_at).total_seconds()))

        return {
            'id': session.id,
            'interview_id': session.interview_id,
            'call_sid': session.exotel_call_sid,
            'status': session.status,
            'caller_phone_masked': _mask_phone(session.caller_phone),
            'candidate_phone_masked': _mask_phone(session.candidate_phone),
            'billing_started_at': session.billing_started_at.isoformat() if session.billing_started_at else '',
            'candidate_connected_at': session.candidate_connected_at.isoformat() if session.candidate_connected_at else '',
            'ended_at': session.ended_at.isoformat() if session.ended_at else '',
            'billable_seconds': billable_seconds,
            'connected_seconds': connected_seconds,
            'created_at': session.created_at.isoformat() if session.created_at else '',
            'updated_at': session.updated_at.isoformat() if session.updated_at else '',
            'disconnect_requested_at': session.disconnect_requested_at.isoformat() if session.disconnect_requested_at else '',
            'outcome': session.outcome,
            'note': session.note,
            'note_updated_at': session.note_updated_at.isoformat() if session.note_updated_at else '',
            'error_message': session.error_message,
            'can_close': session.status not in ACTIVE_STATUSES,
            'can_disconnect': _disconnect_supported(session),
            'disconnect_unavailable_reason': _disconnect_unavailable_reason(session),
            'webhook_event_count': len(webhook_events),
            'last_webhook_event_type': str((last_webhook_payload or {}).get('EventType') or ''),
            'initiated_by_name': _user_display_name(session.initiated_by),
        }

    def save_session_note(self, *, user: User, interview_id: int, session_id: int, note: str, outcome: str = '') -> InterviewCallSession | None:
        session = self.get_session(user=user, interview_id=interview_id, session_id=session_id)
        if not session:
            return None

        normalized_note = (note or '').strip()[:500]
        normalized_outcome = (outcome or '').strip().lower()
        if normalized_outcome not in VALID_OUTCOMES:
            normalized_outcome = ''

        session.note = normalized_note
        session.outcome = normalized_outcome
        session.note_updated_at = timezone.now()
        session.save(update_fields=['note', 'outcome', 'note_updated_at', 'updated_at'])
        return session

    def refresh_session(self, session: InterviewCallSession) -> InterviewCallSession:
        if session.status not in ACTIVE_STATUSES or not session.exotel_call_sid:
            return session
        details_result = self.provider.get_call_details(session.exotel_call_sid)
        if details_result.success and details_result.response_payload:
            return self.sync_session(session, payload=details_result.response_payload)
        if details_result.error_message:
            session.error_message = details_result.error_message
            session.save(update_fields=['error_message', 'updated_at'])
        return session

    def disconnect_session(self, session: InterviewCallSession) -> ProviderResult:
        if not session.exotel_call_sid:
            return ProviderResult(success=False, status='failed', error_message='Exotel call session is missing a call sid.')
        result = self.provider.disconnect_call(session.exotel_call_sid)
        if result.success:
            session.disconnect_requested_at = timezone.now()
            payload = result.response_payload or {}
            session.provider_response = {
                **(session.provider_response or {}),
                'disconnect_response': payload,
                'disconnect_control_unsupported': False,
            }
            session.save(update_fields=['disconnect_requested_at', 'provider_response', 'updated_at'])
        else:
            error_message = result.error_message or 'Unable to disconnect the Exotel call.'
            if 'method not allowed' in error_message.strip().lower():
                error_message = 'Exotel does not allow ending this live call through the current API flow. Please end the call from the handset and keep this tracker open until the status updates.'
                session.error_message = error_message
                session.provider_response = {
                    **(session.provider_response or {}),
                    'disconnect_control_unsupported': True,
                    'disconnect_response': result.response_payload or {},
                }
                session.save(update_fields=['error_message', 'provider_response', 'updated_at'])
            else:
                session.error_message = error_message
                session.save(update_fields=['error_message', 'updated_at'])
            return ProviderResult(
                success=False,
                status='failed',
                provider_message_id=result.provider_message_id,
                response_payload=result.response_payload,
                error_message=error_message,
            )
        return result

    def sync_session_from_webhook(self, call_sid: str, payload: dict[str, Any]) -> InterviewCallSession | None:
        session = InterviewCallSession.objects.filter(exotel_call_sid=call_sid).order_by('-created_at').first()
        if not session:
            logger.info('Exotel webhook received for unknown call sid', extra={'call_sid': call_sid, 'payload': payload})
            return None
        logger.info('Exotel webhook received for call session', extra={'call_sid': call_sid, 'session_id': session.id, 'payload': payload})
        return self.sync_session(session, payload=payload)

    def sync_session(self, session: InterviewCallSession, payload: dict[str, Any] | None = None) -> InterviewCallSession:
        call_data = _extract_call_payload(payload)
        now = timezone.now()
        event_type = _normalize_status(str((payload or {}).get('EventType') or ''))
        call_status = _normalize_status(str(call_data.get('Status') or (payload or {}).get('CallStatus') or (payload or {}).get('Status') or ''))
        legs = call_data.get('Legs') if isinstance(call_data.get('Legs'), list) else []
        caller_leg = legs[0] if len(legs) > 0 and isinstance(legs[0], dict) else {}
        candidate_leg = legs[1] if len(legs) > 1 and isinstance(legs[1], dict) else {}
        caller_leg_status = _normalize_status(str(caller_leg.get('Status') or call_data.get('Leg1Status') or ''))
        candidate_leg_status = _normalize_status(str(candidate_leg.get('Status') or call_data.get('Leg2Status') or ''))
        start_time = _parse_exotel_datetime(call_data.get('StartTime'))
        end_time = _parse_exotel_datetime(call_data.get('EndTime'))
        conversation_duration = _safe_int(call_data.get('ConversationDuration'))
        caller_on_call_duration = _safe_int(caller_leg.get('OnCallDuration') or call_data.get('Duration') or 0)
        candidate_on_call_duration = _safe_int(candidate_leg.get('OnCallDuration') or conversation_duration)

        with transaction.atomic():
            session = InterviewCallSession.objects.select_for_update().get(id=session.id)
            session.provider_response = {**(session.provider_response or {}), 'last_sync': payload or {}}
            if payload and str((payload or {}).get('EventType') or '').strip():
                session.provider_response = _append_webhook_event(session.provider_response, payload)
            answered_event_count = _safe_int(session.provider_response.get('answered_event_count'))
            had_billable_state = bool(session.billing_started_at or session.billable_seconds > 0)
            had_connected_state = bool(session.candidate_connected_at or session.connected_seconds > 0)

            if event_type == 'answered':
                answered_event_count += 1
                session.provider_response['answered_event_count'] = answered_event_count

            if not session.billing_started_at:
                if event_type == 'answered':
                    session.billing_started_at = now
                elif caller_leg_status in LIVE_LEG_STATUSES:
                    session.billing_started_at = (
                        _parse_exotel_datetime(caller_leg.get('StartTime'))
                        or _seconds_to_datetime(end_time or now, caller_on_call_duration)
                        or start_time
                        or now
                    )
                elif call_status in {'in-progress', 'inprogress', 'completed', 'active'}:
                    session.billing_started_at = start_time or now
                elif caller_on_call_duration > 0:
                    session.billing_started_at = _seconds_to_datetime(end_time or now, caller_on_call_duration) or start_time or now

            if not session.candidate_connected_at and session.billing_started_at:
                if event_type == 'answered':
                    if answered_event_count >= 2:
                        session.candidate_connected_at = now
                elif candidate_leg_status in LIVE_LEG_STATUSES:
                    session.candidate_connected_at = (
                        _parse_exotel_datetime(candidate_leg.get('StartTime'))
                        or _seconds_to_datetime(end_time or now, candidate_on_call_duration or conversation_duration)
                        or now
                    )
                elif conversation_duration > 0:
                    session.candidate_connected_at = _seconds_to_datetime(end_time or now, conversation_duration) or now

            if session.billing_started_at and not session.candidate_connected_at:
                session.status = InterviewCallSession.Status.CONNECTING_CANDIDATE
            if session.candidate_connected_at:
                session.status = InterviewCallSession.Status.IN_PROGRESS

            if (call_status in {'queued', 'ringing'} or caller_leg_status in RINGING_LEG_STATUSES) and not session.billing_started_at:
                session.status = InterviewCallSession.Status.DIALING_AGENT
            elif call_status in {'in-progress', 'inprogress', 'active'}:
                if session.candidate_connected_at:
                    session.status = InterviewCallSession.Status.IN_PROGRESS
                elif session.billing_started_at:
                    session.status = InterviewCallSession.Status.CONNECTING_CANDIDATE
                else:
                    session.status = InterviewCallSession.Status.DIALING_AGENT

            if call_status in {'completed', 'failed', 'busy', 'no-answer', 'canceled', 'cancelled'} or event_type == 'terminal':
                ended_at = end_time or now
                session.ended_at = ended_at
                if call_status in {'busy'}:
                    session.status = InterviewCallSession.Status.BUSY
                elif call_status in {'no-answer'}:
                    session.status = InterviewCallSession.Status.NO_ANSWER
                elif call_status in {'canceled', 'cancelled'} and not (session.billing_started_at or had_billable_state):
                    session.status = InterviewCallSession.Status.CANCELLED
                elif session.disconnect_requested_at:
                    session.status = InterviewCallSession.Status.DISCONNECTED
                elif session.candidate_connected_at or had_connected_state or conversation_duration > 0 or candidate_on_call_duration > 0:
                    session.status = InterviewCallSession.Status.COMPLETED
                elif session.billing_started_at or had_billable_state or caller_on_call_duration > 0 or call_status == 'completed':
                    session.status = InterviewCallSession.Status.DISCONNECTED
                else:
                    session.status = InterviewCallSession.Status.FAILED

            if session.ended_at and session.billing_started_at:
                session.billable_seconds = max(session.billable_seconds, int((session.ended_at - session.billing_started_at).total_seconds()))
            else:
                session.billable_seconds = max(session.billable_seconds, caller_on_call_duration)
            if session.ended_at and session.candidate_connected_at:
                session.connected_seconds = max(session.connected_seconds, int((session.ended_at - session.candidate_connected_at).total_seconds()))
            else:
                session.connected_seconds = max(session.connected_seconds, candidate_on_call_duration)

            if call_data.get('Sid'):
                session.exotel_call_sid = str(call_data.get('Sid'))
            if call_status in {'failed', 'busy', 'no-answer'}:
                session.error_message = str(call_data.get('Status') or call_status).strip()
            elif session.status in {
                InterviewCallSession.Status.DIALING_AGENT,
                InterviewCallSession.Status.CONNECTING_CANDIDATE,
                InterviewCallSession.Status.IN_PROGRESS,
                InterviewCallSession.Status.COMPLETED,
                InterviewCallSession.Status.DISCONNECTED,
            }:
                session.error_message = ''

            session.save(update_fields=[
                'provider_response',
                'billing_started_at',
                'candidate_connected_at',
                'status',
                'ended_at',
                'billable_seconds',
                'connected_seconds',
                'exotel_call_sid',
                'error_message',
                'updated_at',
            ])
        return session
