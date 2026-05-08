from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .graph_taxonomy import ROLE_FAMILY_KEYWORDS, SKILL_TAXONOMY

AMBIGUOUS_NARRATIVE_SKILLS = {
    'Administrative Support',
    'Compliance',
    'Coordination',
    'Customer Support',
    'Documentation',
    'Issue Resolution',
    'Policy',
    'Risk',
}


def normalize_graph_text(value: str) -> str:
    text = str(value or '').strip().lower()
    text = re.sub(r'[/_&,+()-]+', ' ', text)
    text = re.sub(r'[^a-z0-9.+#\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


@lru_cache(maxsize=1)
def _skill_alias_map() -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for canonical, entry in SKILL_TAXONOMY.items():
        alias_map[normalize_graph_text(canonical)] = canonical
        for alias in entry.get('aliases', []):
            alias_map[normalize_graph_text(str(alias))] = canonical
    return alias_map


@lru_cache(maxsize=1)
def _skill_alias_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    for alias, canonical in sorted(_skill_alias_map().items(), key=lambda item: (-len(item[0]), item[0])):
        pattern = re.compile(rf'(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])', re.IGNORECASE)
        patterns.append((pattern, canonical))
    return patterns


def canonical_skill_name(value: str) -> str:
    normalized = normalize_graph_text(value)
    if not normalized:
        return ''
    return _skill_alias_map().get(normalized, value.strip())


def extract_canonical_skills(text: str, *, allow_ambiguous: bool = True) -> list[str]:
    normalized = normalize_graph_text(text)
    if not normalized:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for pattern, canonical in _skill_alias_patterns():
        if canonical in seen:
            continue
        if pattern.search(normalized):
            if not allow_ambiguous and canonical in AMBIGUOUS_NARRATIVE_SKILLS:
                continue
            seen.add(canonical)
            found.append(canonical)
    return found


def related_skill_weights(skill: str) -> dict[str, float]:
    canonical = canonical_skill_name(skill)
    if not canonical or canonical not in SKILL_TAXONOMY:
        return {}

    related = {canonical: 1.0}
    for related_skill, weight in dict(SKILL_TAXONOMY[canonical].get('related', {})).items():
        related[related_skill] = max(0.0, min(1.0, float(weight)))
    return related


def build_related_skill_evidence(skills: list[str]) -> dict[str, list[dict[str, float | str]]]:
    evidence: dict[str, list[dict[str, float | str]]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for skill in skills:
        canonical = canonical_skill_name(skill)
        if not canonical:
            continue
        related_entries: list[dict[str, float | str]] = []
        for related_skill, weight in related_skill_weights(canonical).items():
            if related_skill == canonical:
                continue
            pair = (canonical, related_skill)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            related_entries.append({
                'skill': related_skill,
                'weight': round(float(weight), 2),
            })
        if related_entries:
            evidence[canonical] = related_entries
    return evidence


def best_skill_evidence(required_skill: str, candidate_skills: list[str]) -> dict[str, Any]:
    canonical_required = canonical_skill_name(required_skill)
    normalized_candidates = []
    for skill in candidate_skills:
        canonical = canonical_skill_name(skill)
        if canonical:
            normalized_candidates.append(canonical)

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for skill in normalized_candidates:
        if skill in seen:
            continue
        seen.add(skill)
        unique_candidates.append(skill)

    if not canonical_required:
        return {
            'required_skill': required_skill,
            'canonical_required_skill': '',
            'score': 0.0,
            'match_type': 'none',
            'matched_candidate_skill': '',
        }

    if canonical_required in unique_candidates:
        return {
            'required_skill': required_skill,
            'canonical_required_skill': canonical_required,
            'score': 1.0,
            'match_type': 'exact',
            'matched_candidate_skill': canonical_required,
        }

    best_score = 0.0
    best_match = ''
    required_related = related_skill_weights(canonical_required)
    for candidate_skill in unique_candidates:
        score = max(
            required_related.get(candidate_skill, 0.0),
            related_skill_weights(candidate_skill).get(canonical_required, 0.0),
        )
        if score > best_score:
            best_score = score
            best_match = candidate_skill

    return {
        'required_skill': required_skill,
        'canonical_required_skill': canonical_required,
        'score': max(0.0, min(1.0, best_score)),
        'match_type': 'related' if best_score > 0 else 'none',
        'matched_candidate_skill': best_match,
    }


def infer_skill_families(skills: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for skill in skills:
        canonical = canonical_skill_name(skill)
        entry = SKILL_TAXONOMY.get(canonical)
        if not entry:
            continue
        family = str(entry.get('family', '')).strip()
        if not family:
            continue
        counts[family] = counts.get(family, 0) + 1
    return [family for family, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def infer_role_family_from_skills(skills: list[str]) -> tuple[str, str]:
    canonical_skills = {canonical_skill_name(skill) for skill in skills if canonical_skill_name(skill)}
    best_family = ''
    best_subfamily = ''
    best_score = 0

    for entry in ROLE_FAMILY_KEYWORDS.values():
        family = str(entry.get('family') or '')
        subfamily = str(entry.get('subfamily') or '')
        skill_hints = {canonical_skill_name(skill) for skill in entry.get('skill_hints', [])}
        score = len(canonical_skills & skill_hints)
        if score > best_score:
            best_score = score
            best_family = family
            best_subfamily = subfamily

    return best_family, best_subfamily
