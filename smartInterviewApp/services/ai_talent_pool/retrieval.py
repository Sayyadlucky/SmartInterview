from __future__ import annotations

import re
from typing import Any

from .candidate_profile_builder import build_role_aware_candidate_embedding_payload
from .embeddings import cosine_similarity, get_embedding


REMOTE_TOKENS = {'remote', 'hybrid', 'work from home', 'wfh', 'anywhere'}


def _normalize_text(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def _tokenize_location(value: str) -> set[str]:
    normalized = _normalize_text(value)
    return {token for token in re.split(r'[\s,/-]+', normalized) if token}


def _location_matches(role_location: str, candidate_location: str, remote_friendly: bool) -> bool:
    if remote_friendly:
        return True
    role_tokens = _tokenize_location(role_location)
    if not role_tokens:
        return True
    candidate_tokens = _tokenize_location(candidate_location)
    if not candidate_tokens:
        return True
    if role_tokens & REMOTE_TOKENS or candidate_tokens & REMOTE_TOKENS:
        return True
    return bool(role_tokens & candidate_tokens)


def _experience_matches(role_profile: dict[str, Any], candidate_profile: dict[str, Any]) -> bool:
    range_info = role_profile.get('experience_range') or {}
    min_years = range_info.get('min_years')
    candidate_years = float(candidate_profile.get('experience_years') or 0)
    if min_years is None:
        return True
    return candidate_years >= max(0.0, float(min_years) - 1.0)


def retrieve_candidates(role_profile: dict[str, Any], candidate_profiles: list[dict[str, Any]], *, top_k: int = 100) -> list[dict[str, Any]]:
    role_embedding = get_embedding(role_profile.get('embedding_text', ''))
    shortlisted: list[dict[str, Any]] = []

    for candidate in candidate_profiles:
        if not _experience_matches(role_profile, candidate):
            continue
        if not _location_matches(role_profile.get('location', ''), candidate.get('location', ''), bool(role_profile.get('remote_friendly'))):
            continue

        candidate_embedding_payload = build_role_aware_candidate_embedding_payload(candidate, role_profile)
        candidate_embedding = get_embedding(candidate_embedding_payload.get('embedding_text', ''))
        similarity = cosine_similarity(role_embedding, candidate_embedding)
        shortlisted.append({
            **candidate,
            'embedding_text': candidate_embedding_payload.get('embedding_text', candidate.get('embedding_text', '')),
            'embedding_text_token_count': candidate_embedding_payload.get('embedding_text_token_count', candidate.get('embedding_text_token_count', 0)),
            'selected_embedding_skills': candidate_embedding_payload.get('selected_embedding_skills', []),
            'omitted_embedding_skills': candidate_embedding_payload.get('omitted_embedding_skills', []),
            'semantic_similarity_raw': similarity,
            'semantic_similarity': similarity,
        })

    shortlisted.sort(key=lambda item: item.get('semantic_similarity', 0.0), reverse=True)
    return shortlisted[:max(1, min(int(top_k or 100), 100))]
