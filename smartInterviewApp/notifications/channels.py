from __future__ import annotations

from typing import Any

from smartInterviewApp.integrations.providers.exotel import ExotelVoiceProvider
from smartInterviewApp.integrations.providers.meta_whatsapp import MetaWhatsappProvider
from smartInterviewApp.integrations.providers.msg91 import Msg91SmsProvider


sms_provider = Msg91SmsProvider()
whatsapp_provider = MetaWhatsappProvider()
voice_provider = ExotelVoiceProvider()


def send_sms(to: str, message: str, metadata: dict[str, Any] | None = None):
    return sms_provider.send_sms(to=to, message=message, metadata=metadata)


def send_template_message(
    to: str,
    template_name: str,
    language_code: str,
    components: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
):
    return whatsapp_provider.send_template_message(
        to=to,
        template_name=template_name,
        language_code=language_code,
        components=components,
        metadata=metadata,
    )


def trigger_voice_alert(to: str, alert_type: str, payload: dict[str, Any]):
    return voice_provider.trigger_voice_alert(to=to, alert_type=alert_type, payload=payload)
