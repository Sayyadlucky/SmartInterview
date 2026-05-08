from __future__ import annotations

import time
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction

from smartInterviewApp.integrations.providers.exotel import ExotelVoiceProvider
from smartInterviewApp.integrations.providers.meta_whatsapp import MetaWhatsappProvider
from smartInterviewApp.integrations.providers.msg91 import Msg91SmsProvider
from smartInterviewApp.models import Notification, NotificationAttempt, UserNotificationPreference, UserProfile
from smartInterviewApp.notifications.sms_templates import build_sms_message
from smartInterviewApp.notifications.utils import logger, safe_log


class NotificationService:
    def __init__(self) -> None:
        self.whatsapp_provider = MetaWhatsappProvider()
        self.sms_provider = Msg91SmsProvider()
        self.voice_provider = ExotelVoiceProvider()

    @transaction.atomic
    def send_notification(
        self,
        event_type: str,
        severity: str,
        user: User | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Notification:
        if idempotency_key:
            existing = Notification.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing

        notification = Notification.objects.create(
            user=user,
            event_type=event_type,
            severity=severity,
            status=Notification.Status.PENDING,
            payload=payload,
            metadata={'routing_started': True},
            idempotency_key=idempotency_key,
        )
        self._route(notification)
        return notification

    def _route(self, notification: Notification) -> None:
        user = notification.user
        to_phone = self._resolve_phone(user, notification.payload)
        if not to_phone:
            notification.status = Notification.Status.FAILED
            notification.metadata = {**notification.metadata, 'error': 'No destination phone number available'}
            notification.save(update_fields=['status', 'metadata', 'updated_at'])
            return

        severity = notification.severity
        success = False
        if severity == Notification.Severity.LOW:
            success = self._try_whatsapp(notification, to_phone)
        elif severity == Notification.Severity.MEDIUM:
            if not self._try_whatsapp(notification, to_phone):
                success = self._try_sms(notification, to_phone)
            else:
                success = True
        elif severity == Notification.Severity.CRITICAL:
            if not self._try_whatsapp(notification, to_phone):
                if not self._try_sms(notification, to_phone):
                    success = self._try_voice(notification, to_phone)
                else:
                    success = True
            else:
                success = True
        else:
            success = self._try_whatsapp(notification, to_phone)

        if not success and notification.status == Notification.Status.PENDING:
            notification.status = Notification.Status.FAILED
            notification.save(update_fields=['status', 'updated_at'])

    def _resolve_phone(self, user: User | None, payload: dict[str, Any]) -> str:
        direct = str(payload.get('to') or payload.get('phone') or '').strip()
        if direct:
            return direct
        if user:
            profile = UserProfile.objects.filter(user=user).only('phone').first()
            if profile and profile.phone:
                return profile.phone
        return ''

    def _is_opted_in(self, notification: Notification, channel: str) -> bool:
        if not notification.user:
            return True
        prefs, _ = UserNotificationPreference.objects.get_or_create(user=notification.user)
        if channel == NotificationAttempt.Channel.WHATSAPP:
            return prefs.whatsapp_opt_in
        if channel == NotificationAttempt.Channel.SMS:
            return prefs.sms_opt_in
        if channel == NotificationAttempt.Channel.VOICE:
            return prefs.voice_opt_in
        return True

    def _attempt_with_retry(self, func, *args):
        attempts = max(1, settings.NOTIFICATION_RETRY_LIMIT)
        last_result = None
        for i in range(attempts):
            last_result = func(*args)
            if last_result.success:
                return last_result
            if i < attempts - 1 and settings.NOTIFICATION_RETRY_BACKOFF_SECONDS > 0:
                time.sleep(min(1, settings.NOTIFICATION_RETRY_BACKOFF_SECONDS))
        return last_result

    def _create_attempt(self, notification: Notification, channel: str, provider: str, status: str, response: dict[str, Any], provider_message_id: str = '') -> NotificationAttempt:
        return NotificationAttempt.objects.create(
            notification=notification,
            channel=channel,
            provider=provider,
            status=status,
            response_payload=response,
            provider_message_id=provider_message_id,
            metadata={'event_type': notification.event_type},
        )

    def _finalize(self, notification: Notification, channel: str, success: bool) -> None:
        notification.final_channel = channel
        notification.status = Notification.Status.SENT if success else Notification.Status.FAILED
        notification.save(update_fields=['status', 'final_channel', 'updated_at'])

    def _try_whatsapp(self, notification: Notification, to_phone: str) -> bool:
        if not self._is_opted_in(notification, NotificationAttempt.Channel.WHATSAPP):
            return False

        payload = notification.payload
        result = self._attempt_with_retry(
            self.whatsapp_provider.send_template_message,
            to_phone,
            str(payload.get('template_name') or 'default_notification'),
            str(payload.get('language_code') or 'en'),
            payload.get('components') or [],
            payload.get('metadata') or {},
        )
        self._create_attempt(
            notification,
            NotificationAttempt.Channel.WHATSAPP,
            self.whatsapp_provider.name,
            NotificationAttempt.Status.SENT if result.success else NotificationAttempt.Status.FAILED,
            result.response_payload,
            result.provider_message_id,
        )
        logger.info('WhatsApp attempt complete', extra=safe_log({'notification_id': notification.id, 'to': to_phone, 'success': result.success}))
        if result.success:
            self._finalize(notification, NotificationAttempt.Channel.WHATSAPP, True)
            return True
        return False

    def _try_sms(self, notification: Notification, to_phone: str) -> bool:
        if not self._is_opted_in(notification, NotificationAttempt.Channel.SMS):
            return False

        payload = notification.payload
        message = build_sms_message(notification.event_type, payload)
        result = self._attempt_with_retry(self.sms_provider.send_sms, to_phone, message, payload.get('metadata') or {})
        self._create_attempt(
            notification,
            NotificationAttempt.Channel.SMS,
            self.sms_provider.name,
            NotificationAttempt.Status.SENT if result.success else NotificationAttempt.Status.FAILED,
            result.response_payload,
            result.provider_message_id,
        )
        logger.info('SMS attempt complete', extra=safe_log({'notification_id': notification.id, 'to': to_phone, 'success': result.success}))
        if result.success:
            self._finalize(notification, NotificationAttempt.Channel.SMS, True)
            return True
        return False

    def _try_voice(self, notification: Notification, to_phone: str) -> bool:
        if not self._is_opted_in(notification, NotificationAttempt.Channel.VOICE):
            return False

        payload = notification.payload
        result = self._attempt_with_retry(
            self.voice_provider.trigger_voice_alert,
            to_phone,
            str(payload.get('alert_type') or notification.event_type),
            payload.get('voice_payload') or {},
        )
        self._create_attempt(
            notification,
            NotificationAttempt.Channel.VOICE,
            self.voice_provider.name,
            NotificationAttempt.Status.SENT if result.success else NotificationAttempt.Status.FAILED,
            result.response_payload,
            result.provider_message_id,
        )
        logger.info('Voice attempt complete', extra=safe_log({'notification_id': notification.id, 'to': to_phone, 'success': result.success}))
        self._finalize(notification, NotificationAttempt.Channel.VOICE, result.success)
        return result.success
