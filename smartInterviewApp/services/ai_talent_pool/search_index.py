from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .candidate_profile_builder import build_role_aware_candidate_embedding_payload
from .role_graph import normalize_title
from .skill_graph import normalize_graph_text


def _short_text(value: str, *, max_words: int = 42) -> str:
    words = str(value or '').strip().split()
    if len(words) <= max_words:
        return ' '.join(words)
    return ' '.join(words[:max_words]).strip() + '...'


def _token_count(value: str) -> int:
    return len(re.findall(r'[A-Za-z0-9+#./-]+', value or ''))


def build_candidate_search_text(candidate_profile: dict[str, Any]) -> str:
    if candidate_profile.get('embedding_text'):
        return str(candidate_profile.get('embedding_text')).strip()
    exact_skills = candidate_profile.get('exact_candidate_skills') or candidate_profile.get('normalized_candidate_skills') or []
    recent_roles = []
    for entry in (candidate_profile.get('experience_items') or [])[:3]:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get('role') or entry.get('title') or '').strip()
        company = str(entry.get('company') or '').strip()
        if role and company:
            recent_roles.append(f'{role} at {company}')
        elif role:
            recent_roles.append(role)

    parts = [
        f"Title: {candidate_profile.get('title', '')}".strip(),
        f"Headline: {candidate_profile.get('headline', '')}".strip(),
        f"Summary: {_short_text(candidate_profile.get('summary', ''), max_words=28)}".strip(),
        f"Skills: {', '.join(exact_skills[:14])}".strip() if exact_skills else '',
        f"Recent Roles: {' | '.join(recent_roles[:3])}".strip() if recent_roles else '',
        f"Family: {candidate_profile.get('candidate_primary_family', '')}".strip() if candidate_profile.get('candidate_primary_family') else '',
        f"Location: {candidate_profile.get('location', '')}".strip() if candidate_profile.get('location') else '',
    ]
    return '\n'.join(part for part in parts if part).strip()


def build_role_search_text(role_profile: dict[str, Any]) -> str:
    if role_profile.get('embedding_text'):
        return str(role_profile.get('embedding_text')).strip()
    parts = [
        f"Role: {role_profile.get('title', '')}".strip(),
        f"Family: {role_profile.get('role_family', '')}".strip() if role_profile.get('role_family') else '',
        f"Subfamily: {role_profile.get('role_subfamily', '')}".strip() if role_profile.get('role_subfamily') else '',
        f"Required Skills: {', '.join(role_profile.get('exact_required_skills', [])[:12])}".strip() if role_profile.get('exact_required_skills') else '',
        f"Supporting Skills: {', '.join(role_profile.get('role_supporting_skill_inference', [])[:8])}".strip() if role_profile.get('role_supporting_skill_inference') else '',
        f"JD Summary: {_short_text(role_profile.get('description', ''), max_words=42)}".strip() if role_profile.get('description') else '',
        f"Experience Required: {role_profile.get('experience_required', '')}".strip() if role_profile.get('experience_required') else '',
        f"Location: {role_profile.get('location', '')}".strip() if role_profile.get('location') else '',
    ]
    return '\n'.join(part for part in parts if part).strip()


def build_role_aware_candidate_search_text(candidate_profile: dict[str, Any], role_profile: dict[str, Any]) -> dict[str, Any]:
    payload = build_role_aware_candidate_embedding_payload(candidate_profile, role_profile)
    return {
        'search_text': payload.get('embedding_text', ''),
        'token_count': payload.get('embedding_text_token_count', 0),
        'selected_skills': payload.get('selected_embedding_skills', []),
        'omitted_skills': payload.get('omitted_embedding_skills', []),
    }


def build_candidate_source_signature(candidate_profile: dict[str, Any]) -> str:
    payload = {
        'candidate_id': candidate_profile.get('candidate_id'),
        'resume_id': candidate_profile.get('resume_id'),
        'title': candidate_profile.get('title'),
        'headline': candidate_profile.get('headline'),
        'summary': candidate_profile.get('summary'),
        'skills': candidate_profile.get('exact_candidate_skills') or candidate_profile.get('normalized_candidate_skills') or [],
        'experience_years': candidate_profile.get('experience_years'),
        'location': candidate_profile.get('location'),
        'resume_status': candidate_profile.get('resume_status'),
        'latest_interview_id': candidate_profile.get('latest_interview_id'),
        'latest_pipeline_status': candidate_profile.get('latest_pipeline_status'),
        'updated_hint': candidate_profile.get('latest_interview_date'),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def build_role_query_signature(role_profile: dict[str, Any]) -> str:
    payload = {
        'role_id': role_profile.get('role_id'),
        'title': role_profile.get('title'),
        'role_family': role_profile.get('role_family'),
        'role_subfamily': role_profile.get('role_subfamily'),
        'required': role_profile.get('exact_required_skills', []),
        'preferred': role_profile.get('normalized_preferred_skills', []),
        'location': normalize_graph_text(role_profile.get('location', '')),
        'experience_required': role_profile.get('experience_required', ''),
        'search_text': role_profile.get('embedding_text', ''),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def normalize_location(value: str) -> str:
    return normalize_graph_text(value)


def profile_quality_score(candidate_profile: dict[str, Any]) -> float:
    score = 0.0
    if candidate_profile.get('title'):
        score += 0.2
    if candidate_profile.get('headline'):
        score += 0.1
    if candidate_profile.get('summary'):
        score += 0.2
    if candidate_profile.get('exact_candidate_skills'):
        score += min(0.3, len(candidate_profile.get('exact_candidate_skills') or []) * 0.03)
    if candidate_profile.get('experience_years'):
        score += 0.1
    if candidate_profile.get('location'):
        score += 0.1
    return round(min(1.0, score) * 100, 2)
