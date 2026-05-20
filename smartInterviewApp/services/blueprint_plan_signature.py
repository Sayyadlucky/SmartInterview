from __future__ import annotations

import hashlib
import json
from typing import Any

from smartInterviewApp.models import normalize_skill_key


def blueprint_plan_signature(plan: dict[str, Any] | None) -> str:
    if not isinstance(plan, dict):
        return ''
    payload = {
        'primary_skill': _skill_identity(plan.get('primary_skill')),
        'selected_sections': _selected_section_identities(plan),
        'coding_required': bool(plan.get('coding_required')),
        'coding_skill_targets': _normalized_unique_target_keys(plan.get('coding_skill_targets')),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def ensure_blueprint_plan_signature(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    signature = blueprint_plan_signature(plan)
    return {**plan, 'plan_signature': signature}


def _selected_section_identities(plan: dict[str, Any]) -> list[dict[str, Any]]:
    runtime_sections = _list_of_dicts(plan.get('runtime_sections'))
    source = runtime_sections if runtime_sections else _list_of_dicts(plan.get('sub_skills'))
    return _unique_skill_identities(source)


def _unique_skill_identities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        identity = _skill_identity(item, include_role=True)
        key = json.dumps(identity, sort_keys=True, separators=(',', ':'))
        if key in seen:
            continue
        seen.add(key)
        identities.append(identity)
    return identities


def _normalized_unique_target_keys(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    keys = {
        normalize_skill_key(_target_name(item))
        for item in items
        if normalize_skill_key(_target_name(item))
    }
    return sorted(keys)


def _skill_identity(item: Any, *, include_role: bool = False) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    skill_id = item.get('skill_id') or item.get('id') or ''
    try:
        skill_id = int(skill_id)
    except (TypeError, ValueError):
        skill_id = ''
    name = str(item.get('name') or item.get('skill') or item.get('skill_name') or '').strip()
    key = str(item.get('skill_key') or item.get('key') or normalize_skill_key(name)).strip()
    identity: dict[str, Any] = {}
    if skill_id:
        identity['skill_id'] = skill_id
    else:
        identity['skill_key'] = normalize_skill_key(key or name)
        identity['name'] = normalize_skill_key(name)
    if include_role:
        role = normalize_skill_key(str(item.get('skill_role') or item.get('role') or '').strip())
        if role:
            identity['role'] = role
    return identity


def _target_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get('name') or item.get('skill') or item.get('skill_name') or '').strip()
    return str(item or '').strip()


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
