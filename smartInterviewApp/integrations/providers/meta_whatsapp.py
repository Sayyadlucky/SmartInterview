from __future__ import annotations

import uuid

from django.conf import settings

from .contracts import ProviderResult, WhatsappProvider
from .http_utils import post_json


class MetaWhatsappProvider(WhatsappProvider):
    name = 'meta_whatsapp'

    def _messages_url(self) -> str:
        return (
            f"https://graph.facebook.com/{settings.META_WHATSAPP_API_VERSION}/"
            f"{settings.META_WHATSAPP_PHONE_NUMBER_ID}/messages"
        )

    def _send_template_payload(self, payload: dict) -> ProviderResult:
        if settings.NOTIFICATION_PROVIDER_MODE == 'mock' or settings.META_WHATSAPP_MOCK_MODE:
            msg_id = f'mock-wa-{uuid.uuid4().hex[:14]}'
            return ProviderResult(
                success=True,
                status='sent',
                provider_message_id=msg_id,
                response_payload={'mocked': True, 'messages': [{'id': msg_id}], 'payload': payload},
            )
        if not settings.META_WHATSAPP_TOKEN or not settings.META_WHATSAPP_PHONE_NUMBER_ID:
            return ProviderResult(success=False, status='failed', error_message='Meta WhatsApp config missing')

        status, data = post_json(
            self._messages_url(),
            payload,
            headers={'Authorization': f'Bearer {settings.META_WHATSAPP_TOKEN}'},
        )
        messages = data.get('messages') or []
        msg_id = str(messages[0].get('id')) if messages else ''
        ok = 200 <= status < 300
        return ProviderResult(
            success=ok,
            status='sent' if ok else 'failed',
            provider_message_id=msg_id,
            response_payload=data,
            error_message='' if ok else str(data.get('error', {}).get('message') or 'WhatsApp send failed'),
        )

    def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> ProviderResult:
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code},
                'components': components or [],
            },
        }
        return self._send_template_payload(payload)

    def send_authentication_message(
        self,
        to: str,
        template_name: str,
        language_code: str,
        code: str,
        metadata: dict | None = None,
    ) -> ProviderResult:
        normalized_code = str(code or '').strip()
        if not normalized_code:
            return ProviderResult(success=False, status='failed', error_message='Authentication code is required')
        if len(normalized_code) > 15:
            return ProviderResult(success=False, status='failed', error_message='Authentication code exceeds 15 characters')

        # Inference from Meta auth-template behavior: send-time data is the single verification code.
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code},
                'components': [
                    {
                        'type': 'body',
                        'parameters': [
                            {'type': 'text', 'text': normalized_code},
                        ],
                    }
                ],
            },
        }
        return self._send_template_payload(payload)
