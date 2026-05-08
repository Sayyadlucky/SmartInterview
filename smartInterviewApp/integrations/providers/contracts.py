from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    success: bool
    status: str
    provider_message_id: str = ''
    provider_request_id: str = ''
    response_payload: dict[str, Any] = field(default_factory=dict)
    error_message: str = ''


class OtpProvider(ABC):
    name: str

    @abstractmethod
    def request_otp(self, phone: str, otp: str, purpose: str, expires_in_seconds: int) -> ProviderResult:
        raise NotImplementedError


class SmsProvider(ABC):
    name: str

    @abstractmethod
    def send_sms(self, to: str, message: str, metadata: dict[str, Any] | None = None) -> ProviderResult:
        raise NotImplementedError


class WhatsappProvider(ABC):
    name: str

    @abstractmethod
    def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    def send_authentication_message(
        self,
        to: str,
        template_name: str,
        language_code: str,
        code: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResult:
        raise NotImplementedError


class VoiceProvider(ABC):
    name: str

    @abstractmethod
    def trigger_voice_alert(
        self,
        to: str,
        alert_type: str,
        payload: dict[str, Any],
    ) -> ProviderResult:
        raise NotImplementedError
