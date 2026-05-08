from __future__ import annotations

import uuid

from django.conf import settings

from .contracts import OtpProvider, ProviderResult, SmsProvider
from .http_utils import post_form, post_json


class Msg91OtpProvider(OtpProvider):
    name = 'msg91_otp'

    def request_otp(self, phone: str, otp: str, purpose: str, expires_in_seconds: int) -> ProviderResult:
        if settings.NOTIFICATION_PROVIDER_MODE == 'mock' or settings.MSG91_MOCK_MODE:
            request_id = f'mock-msg91-otp-{uuid.uuid4().hex[:12]}'
            return ProviderResult(
                success=True,
                status='sent',
                provider_request_id=request_id,
                response_payload={'mocked': True, 'request_id': request_id},
            )
        if not settings.MSG91_AUTH_KEY:
            return ProviderResult(success=False, status='failed', error_message='MSG91 auth key not configured')
        if not settings.MSG91_OTP_TEMPLATE_ID:
            return ProviderResult(success=False, status='failed', error_message='MSG91 OTP template id not configured')

        payload = {
            'flow_id': settings.MSG91_OTP_TEMPLATE_ID,
            'sender': settings.MSG91_SENDER_ID,
            'route': settings.MSG91_ROUTE,
            'recipients': [
                {
                    'mobiles': str(phone or '').strip(),
                    'OTP': str(otp or '').strip(),
                }
            ],
        }
        status, data = post_json('https://control.msg91.com/api/v5/flow/', payload, headers={'authkey': settings.MSG91_AUTH_KEY})
        request_id = str(data.get('message') or data.get('request_id') or data.get('requestId') or '')
        ok = 200 <= status < 300 and str(data.get('type') or '').strip().lower() == 'success'
        return ProviderResult(
            success=ok,
            status='sent' if ok else 'failed',
            provider_request_id=request_id,
            response_payload=data,
            error_message='' if ok else str(data.get('message') or 'OTP request failed'),
        )


class Msg91SmsProvider(SmsProvider):
    name = 'msg91_sms'

    def send_sms(self, to: str, message: str, metadata: dict | None = None) -> ProviderResult:
        metadata = metadata or {}
        if settings.NOTIFICATION_PROVIDER_MODE == 'mock' or settings.MSG91_MOCK_MODE:
            message_id = f'mock-msg91-sms-{uuid.uuid4().hex[:12]}'
            return ProviderResult(
                success=True,
                status='sent',
                provider_message_id=message_id,
                response_payload={'mocked': True, 'request_id': message_id},
            )
        if not settings.MSG91_AUTH_KEY:
            return ProviderResult(success=False, status='failed', error_message='MSG91 auth key not configured')

        template_id = str(
            metadata.get('msg91_template_id')
            or metadata.get('template_id')
            or ''
        ).strip()
        if template_id:
            recipient = {'mobiles': str(to or '').strip()}
            flow_variables = metadata.get('msg91_flow_variables') or metadata.get('flow_variables') or {}
            if isinstance(flow_variables, dict):
                for key, value in flow_variables.items():
                    key_name = str(key or '').strip()
                    if key_name:
                        recipient[key_name] = str(value or '').strip()
            payload = {
                'flow_id': template_id,
                'sender': settings.MSG91_SENDER_ID,
                'route': settings.MSG91_ROUTE,
                'recipients': [recipient],
            }
            status, data = post_json('https://control.msg91.com/api/v5/flow/', payload, headers={'authkey': settings.MSG91_AUTH_KEY})
            message_id = str(data.get('message') or data.get('request_id') or '')
            ok = 200 <= status < 300 and str(data.get('type') or '').strip().lower() == 'success'
            return ProviderResult(
                success=ok,
                status='sent' if ok else 'failed',
                provider_message_id=message_id,
                response_payload=data,
                error_message='' if ok else str(data.get('message') or 'SMS send failed'),
            )

        payload = {
            'authkey': settings.MSG91_AUTH_KEY,
            'mobiles': str(to or '').strip(),
            'message': message,
            'sender': settings.MSG91_SENDER_ID,
            'route': settings.MSG91_ROUTE,
            'country': metadata.get('country') or '91',
            'response': 'json',
        }
        status, data = post_form('https://control.msg91.com/api/v2/sendsms', payload, headers={})
        message_id = str(data.get('request_id') or data.get('type') or '')
        ok = 200 <= status < 300 and str(data.get('type') or '').strip().lower() != 'error'
        return ProviderResult(
            success=ok,
            status='sent' if ok else 'failed',
            provider_message_id=message_id,
            response_payload=data,
            error_message='' if ok else str(data.get('message') or 'SMS send failed'),
        )
