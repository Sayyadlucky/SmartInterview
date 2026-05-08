from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger('smartInterview.notifications')


def mask_phone(phone: str) -> str:
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if len(digits) <= 4:
        return '*' * len(digits)
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def safe_log(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(extra or {})
    if 'phone' in payload:
        payload['phone'] = mask_phone(str(payload['phone']))
    if 'to' in payload:
        payload['to'] = mask_phone(str(payload['to']))
    return payload
