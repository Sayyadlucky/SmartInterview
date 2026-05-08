from __future__ import annotations

import base64
import re
import uuid
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings

from .contracts import ProviderResult, VoiceProvider
from .http_utils import get_json, post_form


class ExotelVoiceProvider(VoiceProvider):
    name = 'exotel_voice'
    _HOST_PATTERN = re.compile(r'^[A-Za-z0-9.-]+$')

    def _missing_config_message(self) -> str:
        missing: list[str] = []
        if not settings.EXOTEL_SID:
            missing.append('EXOTEL_SID')
        if not settings.EXOTEL_API_KEY:
            missing.append('EXOTEL_API_KEY')
        if not settings.EXOTEL_TOKEN:
            missing.append('EXOTEL_TOKEN')
        if not settings.EXOTEL_CALLER_ID:
            missing.append('EXOTEL_CALLER_ID')
        if not missing:
            return ''
        return f"Exotel config missing: {', '.join(missing)}"

    def _extract_error_message(self, data: Any, fallback: str) -> str:
        if not isinstance(data, dict):
            return fallback

        direct_keys = (
            'message',
            'Message',
            'error',
            'Error',
            'description',
            'Description',
            'raw',
        )
        for key in direct_keys:
            value = data.get(key)
            if value:
                return str(value)

        for nested_key in ('RestException', 'exception', 'error_data', 'response'):
            nested = data.get(nested_key)
            if isinstance(nested, dict):
                for key in direct_keys:
                    value = nested.get(key)
                    if value:
                        return str(value)
                if nested:
                    return str(nested)

        if data:
            return str(data)
        return fallback

    def _status_callback_url(self) -> str:
        raw = str(getattr(settings, 'EXOTEL_STATUS_CALLBACK_URL', '') or '').strip()
        if not raw:
            return ''
        token = str(getattr(settings, 'EXOTEL_WEBHOOK_TOKEN', '') or '').strip()
        if not token:
            return raw
        parsed = urlparse(raw)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault('token', token)
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _api_host(self) -> str:
        raw = str(getattr(settings, 'EXOTEL_SUBDOMAIN', '') or '').strip()
        if not raw:
            return 'api.exotel.com'
        raw = raw.strip('\'"')
        if raw.startswith('os.getenv('):
            return ''
        if '://' in raw:
            raw = urlparse(raw).netloc or raw
        raw = raw.split('/')[0].split('?')[0].strip().strip('\'"').lstrip('@')
        if raw in {'my.exotel.com', 'my.sg.exotel.com'}:
            return 'api.exotel.com'
        if raw in {'my.in.exotel.com', 'my.mum1.exotel.com'}:
            return 'api.in.exotel.com'
        if not raw or any(ch.isspace() for ch in raw) or '(' in raw or ')' in raw:
            return ''
        if '.' not in raw or not self._HOST_PATTERN.fullmatch(raw):
            return ''
        return raw

    def _authorization_header(self) -> str:
        username = settings.EXOTEL_API_KEY
        secret = settings.EXOTEL_TOKEN
        auth_token = base64.b64encode(f"{username}:{secret}".encode('utf-8')).decode('utf-8')
        return f'Basic {auth_token}'

    def _connect_call(self, payload: dict[str, Any]) -> ProviderResult:
        if settings.NOTIFICATION_PROVIDER_MODE == 'mock' or settings.EXOTEL_MOCK_MODE:
            sid = f'mock-exotel-{uuid.uuid4().hex[:12]}'
            return ProviderResult(
                success=True,
                status='sent',
                provider_message_id=sid,
                response_payload={'mocked': True, 'Call': {'Sid': sid}, 'payload': payload},
            )
        missing_config_message = self._missing_config_message()
        if missing_config_message:
            return ProviderResult(success=False, status='failed', error_message=missing_config_message)
        api_host = self._api_host()
        if not api_host:
            return ProviderResult(
                success=False,
                status='failed',
                error_message='EXOTEL_SUBDOMAIN is invalid. Set it to a hostname like api.exotel.com or your assigned Exotel API host.',
            )

        url = f"https://{api_host}/v1/Accounts/{settings.EXOTEL_SID}/Calls/connect.json"
        status, data = post_form(url, payload, headers={'Authorization': self._authorization_header()})
        call = data.get('Call', {}) if isinstance(data, dict) else {}
        sid = str(call.get('Sid') or '')
        ok = 200 <= status < 300
        error_message = '' if ok else self._extract_error_message(data, 'Voice call trigger failed')
        return ProviderResult(
            success=ok,
            status='sent' if ok else 'failed',
            provider_message_id=sid,
            response_payload=data,
            error_message=error_message,
        )

    def trigger_voice_alert(self, to: str, alert_type: str, payload: dict) -> ProviderResult:
        body = {
            'From': settings.EXOTEL_CALLER_ID,
            'To': to,
            'CallerId': settings.EXOTEL_CALLER_ID,
            'CustomField': alert_type,
        }
        body.update(payload or {})
        return self._connect_call(body)

    def connect_agent_to_candidate(
        self,
        *,
        agent_phone: str,
        candidate_phone: str,
        interview_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResult:
        body: dict[str, Any] = {
            'From': agent_phone,
            'To': candidate_phone,
            'CallerId': settings.EXOTEL_CALLER_ID,
            'CustomField': f'interview:{interview_id}',
        }
        status_callback_url = self._status_callback_url()
        if status_callback_url:
            body['StatusCallback'] = status_callback_url
            body['StatusCallbackContentType'] = 'application/json'
            body['StatusCallbackEvents[0]'] = 'answered'
            body['StatusCallbackEvents[1]'] = 'terminal'
        if metadata:
            for key, value in metadata.items():
                if value not in {None, ''}:
                    body[key] = value
        return self._connect_call(body)

    def get_call_details(self, call_sid: str) -> ProviderResult:
        if settings.NOTIFICATION_PROVIDER_MODE == 'mock' or settings.EXOTEL_MOCK_MODE:
            return ProviderResult(
                success=True,
                status='sent',
                provider_message_id=call_sid,
                response_payload={'Call': {'Sid': call_sid, 'Status': 'completed'}},
            )
        missing_config_message = self._missing_config_message()
        if missing_config_message:
            return ProviderResult(success=False, status='failed', error_message=missing_config_message)
        api_host = self._api_host()
        if not api_host:
            return ProviderResult(
                success=False,
                status='failed',
                error_message='EXOTEL_SUBDOMAIN is invalid. Set it to a hostname like api.exotel.com or your assigned Exotel API host.',
            )

        url = f"https://{api_host}/v1/Accounts/{settings.EXOTEL_SID}/Calls/{call_sid}.json?details=true"
        status, data = get_json(url, headers={'Authorization': self._authorization_header()})
        call = data.get('Call', {}) if isinstance(data, dict) else {}
        sid = str(call.get('Sid') or call_sid or '')
        ok = 200 <= status < 300
        return ProviderResult(
            success=ok,
            status='sent' if ok else 'failed',
            provider_message_id=sid,
            response_payload=data,
            error_message='' if ok else self._extract_error_message(data, 'Unable to fetch Exotel call details'),
        )

    def disconnect_call(self, call_sid: str) -> ProviderResult:
        if settings.NOTIFICATION_PROVIDER_MODE == 'mock' or settings.EXOTEL_MOCK_MODE:
            return ProviderResult(
                success=True,
                status='sent',
                provider_message_id=call_sid,
                response_payload={'mocked': True, 'Call': {'Sid': call_sid, 'Status': 'completed'}},
            )
        missing_config_message = self._missing_config_message()
        if missing_config_message:
            return ProviderResult(success=False, status='failed', error_message=missing_config_message)
        api_host = self._api_host()
        if not api_host:
            return ProviderResult(
                success=False,
                status='failed',
                error_message='EXOTEL_SUBDOMAIN is invalid. Set it to a hostname like api.exotel.com or your assigned Exotel API host.',
            )

        url = f"https://{api_host}/v1/Accounts/{settings.EXOTEL_SID}/Calls/{call_sid}.json"
        status, data = post_form(url, {'Status': 'completed'}, headers={'Authorization': self._authorization_header()})
        ok = 200 <= status < 300
        return ProviderResult(
            success=ok,
            status='sent' if ok else 'failed',
            provider_message_id=call_sid,
            response_payload=data,
            error_message='' if ok else self._extract_error_message(data, 'Unable to disconnect the Exotel call'),
        )
