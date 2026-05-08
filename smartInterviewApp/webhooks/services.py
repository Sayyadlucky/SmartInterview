from __future__ import annotations

import hashlib
import hmac
from typing import Any

from django.conf import settings

from smartInterviewApp.models import NotificationAttempt
from smartInterviewApp.notifications.utils import logger


class WebhookService:
    def update_attempt_status(self, provider_message_id: str, status: str, payload: dict[str, Any]) -> bool:
        if not provider_message_id:
            return False
        attempt = NotificationAttempt.objects.filter(provider_message_id=provider_message_id).order_by('-attempted_at').first()
        if not attempt:
            return False

        mapped = self._map_status(status)
        attempt.status = mapped
        attempt.response_payload = payload
        attempt.save(update_fields=['status', 'response_payload', 'updated_at'])

        notification = attempt.notification
        if mapped in (NotificationAttempt.Status.DELIVERED, NotificationAttempt.Status.READ):
            notification.status = mapped
            notification.final_channel = attempt.channel
            notification.save(update_fields=['status', 'final_channel', 'updated_at'])
        elif mapped == NotificationAttempt.Status.FAILED and notification.status == notification.Status.PENDING:
            notification.status = notification.Status.FAILED
            notification.save(update_fields=['status', 'updated_at'])

        return True

    def verify_meta_signature(self, raw_body: bytes, signature: str | None) -> bool:
        if not settings.META_WHATSAPP_APP_SECRET:
            return True
        if not signature or not signature.startswith('sha256='):
            return False
        expected = hmac.new(
            settings.META_WHATSAPP_APP_SECRET.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature.split('=', 1)[1])

    def verify_hmac_signature(self, raw_body: bytes, signature: str | None, secret: str) -> bool:
        if not secret:
            return True
        if not signature:
            return False
        provided = signature.split('=', 1)[1] if '=' in signature else signature
        expected = hmac.new(
            secret.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    def _map_status(self, status: str) -> str:
        normalized = (status or '').strip().lower()
        if normalized in ('sent', 'queued'):
            return NotificationAttempt.Status.SENT
        if normalized == 'delivered':
            return NotificationAttempt.Status.DELIVERED
        if normalized == 'read':
            return NotificationAttempt.Status.READ
        if normalized in ('failed', 'undelivered', 'busy', 'no-answer'):
            return NotificationAttempt.Status.FAILED
        return NotificationAttempt.Status.CALLBACK_RECEIVED

    def extract_meta_status_events(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                for status in value.get('statuses', []):
                    events.append(
                        {
                            'provider_message_id': str(status.get('id') or ''),
                            'status': str(status.get('status') or ''),
                        }
                    )
        return events
