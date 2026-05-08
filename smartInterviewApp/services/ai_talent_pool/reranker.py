from __future__ import annotations

import re
from typing import Any

from .config import (
    get_graph_exact_match_bonus,
    get_graph_family_alignment_bonus,
    get_graph_related_match_cap,
    get_graph_title_adjacency_blend,
    get_medium_confidence_penalty,
    get_scoring_weights,
    get_semantic_floor_full_match,
    get_semantic_floor_strong_adjacent,
    get_sparse_role_confidence_penalty,
)
from .explanations import build_explanations
from .normalization import canonicalize_skill_label, canonical_display_list_from_tokens, expand_skill_label
from .role_graph import title_adjacency
from .skill_graph import best_skill_evidence, canonical_skill_name


TITLE_SYNONYMS = {
    'software engineer': 'software_engineer',
    'software developer': 'software_engineer',
    'developer': 'software_engineer',
    'engineer': 'software_engineer',
    'full stack': 'fullstack',
    'full-stack': 'fullstack',
    'fullstack developer': 'fullstack',
    'fullstack engineer': 'fullstack',
    'frontend': 'frontend',
    'front end': 'frontend',
    'backend': 'backend',
    'back end': 'backend',
    'python': 'python',
    'javascript': 'javascript',
    'salesforce': 'salesforce',
    'apex': 'salesforce',
}

SPECIALIZED_TITLE_TOKENS = {
    'salesforce',
    'python',
    'javascript',
    'fullstack',
    'backend',
    'frontend',
    'devops',
    'qa',
    'data_engineer',
    'ml_engineer',
    'machine_learning',
}

TITLE_ADJACENCY_GROUPS = [
    {'software_engineer', 'fullstack', 'backend', 'frontend'},
    {'python', 'backend', 'fullstack'},
    {'javascript', 'frontend', 'fullstack'},
    {'salesforce'},
    {'qa', 'tester', 'quality_assurance'},
    {'data_engineer', 'data_scientist', 'machine_learning', 'ml_engineer'},
    {'devops', 'platform_engineer', 'site_reliability'},
]


def _normalize_text(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def _normalize_skill_set(values: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        normalized.update(expand_skill_label(value))
    return normalized


def _exact_skill_set(values: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        canonical = canonicalize_skill_label(value)
        if canonical:
            normalized.add(_normalize_text(canonical))
    return normalized


def _ratio_match(matched: set[str], universe: set[str], *, neutral_if_empty: float = 0.0) -> float:
    if not universe:
        return neutral_if_empty
    if not matched:
        return 0.0
    return len(matched & universe) / max(1, len(universe))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value)
    return output


def _match_skills(role_skills: list[str], candidate_skills: set[str]) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for role_skill in role_skills:
        normalized = _normalize_text(role_skill)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        expanded = expand_skill_label(role_skill)
        if expanded & candidate_skills:
            matched.append(role_skill)
        else:
            missing.append(role_skill)
    return matched, missing


def _graph_skill_score(role_skills: list[str], candidate_skill_inputs: list[str]) -> dict[str, Any]:
    if not role_skills:
        return {
            'score': 0.0,
            'matched_skills': [],
            'missing_skills': [],
            'exact_skill_matches': [],
            'related_skill_matches': [],
            'related_skill_matches_summary': [],
            'matched_required_skills_count': 0,
            'missing_required_skills_count': 0,
        }

    exact_bonus = get_graph_exact_match_bonus()
    related_cap = get_graph_related_match_cap()
    evidence_rows: list[dict[str, Any]] = []

    for role_skill in role_skills:
        evidence = best_skill_evidence(role_skill, candidate_skill_inputs)
        if evidence['match_type'] == 'exact':
            evidence['score'] = min(1.0, evidence['score'] + exact_bonus)
        elif evidence['match_type'] == 'related':
            evidence['score'] = min(related_cap, evidence['score'])
        evidence_rows.append(evidence)

    total_score = sum(float(row['score']) for row in evidence_rows) / max(1, len(evidence_rows))
    exact_matches = [row['canonical_required_skill'] for row in evidence_rows if row['match_type'] == 'exact']
    related_rows = [row for row in evidence_rows if row['match_type'] == 'related']
    matched_skills = [row['required_skill'] for row in evidence_rows if float(row['score']) > 0]
    missing_skills = [row['required_skill'] for row in evidence_rows if float(row['score']) <= 0]

    related_summary = [
        f"{row['required_skill']} via {row['matched_candidate_skill']} ({int(round(float(row['score']) * 100))}%)"
        for row in related_rows
    ]

    return {
        'score': max(0.0, min(1.0, total_score)),
        'matched_skills': matched_skills,
        'missing_skills': missing_skills,
        'evidence_rows': evidence_rows,
        'exact_skill_matches': _dedupe_preserve_order(exact_matches),
        'related_skill_matches': related_rows,
        'related_skill_matches_summary': related_summary,
        'matched_required_skills_count': len(matched_skills),
        'missing_required_skills_count': len(missing_skills),
    }


def _normalize_title_tokens(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()

    title = f' {normalized} '
    canonical_tokens: set[str] = set()
    for phrase, canonical in TITLE_SYNONYMS.items():
        if f' {phrase} ' in title:
            canonical_tokens.add(canonical)

    token_map = {
        'fullstack': 'fullstack',
        'backend': 'backend',
        'frontend': 'frontend',
        'python': 'python',
        'javascript': 'javascript',
        'salesforce': 'salesforce',
        'apex': 'salesforce',
        'engineer': 'software_engineer',
        'developer': 'software_engineer',
        'qa': 'qa',
        'tester': 'tester',
        'devops': 'devops',
        'platform': 'platform_engineer',
        'reliability': 'site_reliability',
        'data': 'data_engineer',
        'ml': 'ml_engineer',
        'machine': 'machine_learning',
    }
    for token in re.findall(r'[a-z0-9+#.-]+', normalized):
        mapped = token_map.get(token)
        if mapped:
            canonical_tokens.add(mapped)
    return canonical_tokens


def _experience_fit(role_profile: dict[str, Any], candidate_profile: dict[str, Any]) -> float:
    experience_range = role_profile.get('experience_range') or {}
    min_years = experience_range.get('min_years')
    max_years = experience_range.get('max_years')
    candidate_years = float(candidate_profile.get('experience_years') or 0)

    if min_years is None and max_years is None:
        return 0.45 if role_profile.get('role_profile_is_sparse') else 0.65
    if min_years is not None and candidate_years < float(min_years):
        gap = float(min_years) - candidate_years
        return max(0.0, 1.0 - (gap / 4.0))
    if max_years is not None and candidate_years > float(max_years):
        gap = candidate_years - float(max_years)
        return max(0.45, 1.0 - (gap / 8.0))
    return 1.0


def _title_similarity(role_profile: dict[str, Any], candidate_profile: dict[str, Any]) -> float:
    role_title = role_profile.get('title', '')
    candidate_title = candidate_profile.get('title', '') or candidate_profile.get('headline', '')
    normalized_role_title = _normalize_text(role_title)
    normalized_candidate_title = _normalize_text(candidate_title)
    if not normalized_role_title or not normalized_candidate_title:
        return 0.25 if role_profile.get('role_profile_is_sparse') else 0.4

    if normalized_role_title == normalized_candidate_title:
        return 1.0

    role_tokens = _normalize_title_tokens(role_title)
    candidate_tokens = _normalize_title_tokens(candidate_title)
    if not role_tokens or not candidate_tokens:
        return 0.25 if role_profile.get('role_profile_is_sparse') else 0.4

    overlap_ratio = len(role_tokens & candidate_tokens) / max(1, len(role_tokens))
    best_score = overlap_ratio

    for group in TITLE_ADJACENCY_GROUPS:
        role_group = role_tokens & group
        candidate_group = candidate_tokens & group
        if role_group and candidate_group:
            group_overlap = len(role_group & candidate_group) / max(1, len(role_group | candidate_group))
            best_score = max(best_score, 0.48 + (group_overlap * 0.28))

    role_is_specialized = bool(role_tokens & SPECIALIZED_TITLE_TOKENS)
    candidate_is_generic_engineer = candidate_tokens == {'software_engineer'}
    has_specialized_overlap = bool((role_tokens & candidate_tokens) & SPECIALIZED_TITLE_TOKENS)

    if role_is_specialized and candidate_is_generic_engineer and not has_specialized_overlap:
        return min(best_score, 0.32)

    if role_is_specialized and not has_specialized_overlap and overlap_ratio == 0:
        return min(best_score, 0.22 if role_profile.get('role_profile_is_sparse') else 0.28)

    return min(1.0, best_score)


def _location_match(role_profile: dict[str, Any], candidate_profile: dict[str, Any]) -> float:
    role_location = _normalize_text(role_profile.get('location', ''))
    candidate_location = _normalize_text(candidate_profile.get('location', ''))
    if not role_location:
        return 0.45 if role_profile.get('role_profile_is_sparse') else 0.7
    if role_profile.get('remote_friendly'):
        return 1.0
    if not candidate_location:
        return 0.45
    if role_location == candidate_location:
        return 1.0
    role_tokens = set(role_location.replace(',', ' ').split())
    candidate_tokens = set(candidate_location.replace(',', ' ').split())
    if role_tokens & {'remote', 'hybrid'} or candidate_tokens & {'remote', 'hybrid'}:
        return 1.0
    if role_tokens & candidate_tokens:
        return 0.82
    return 0.0


def _normalize_interview_score(value: Any) -> float:
    if value is None:
        return 0.5
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.5
    if numeric <= 0:
        return 0.0
    if numeric <= 10:
        return min(1.0, numeric / 10.0)
    return min(1.0, numeric / 100.0)


def _pipeline_signal(candidate_profile: dict[str, Any], role_profile: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    interview_stats = candidate_profile.get('interview_stats') or {}
    average_score = interview_stats.get('average_score')
    same_role_score = interview_stats.get('same_role_average_score')
    signal = 0.4 if role_profile.get('role_profile_is_sparse') else 0.5
    if average_score is not None:
        signal = _normalize_interview_score(average_score)
    if same_role_score is not None and candidate_profile.get('latest_role_id') == role_profile.get('role_id'):
        signal = max(signal, _normalize_interview_score(same_role_score))
    return signal, {
        'average_interview_score': average_score,
        'same_role_average_score': same_role_score,
    }


def _band(score: int, confidence: str) -> str:
    if confidence == 'low' and score >= 82:
        return 'good'
    if confidence == 'low' and score >= 62:
        return 'watch'
    if confidence == 'medium' and score >= 90:
        return 'strong'
    if score >= 82:
        return 'strong'
    if score >= 62:
        return 'good'
    return 'watch'


def _apply_band_caps(
    *,
    band: str,
    confidence: str,
    required_count: int,
    missing_required_count: int,
    role_profile_is_sparse: bool,
) -> str:
    if role_profile_is_sparse and band == 'strong':
        return 'good'
    if confidence == 'low' and band == 'strong':
        return 'good'
    if confidence == 'low' and band == 'good':
        return 'watch'
    if required_count > 0 and missing_required_count > 0 and band == 'strong':
        return 'good'
    if required_count >= 2 and missing_required_count >= max(1, required_count // 2) and band == 'good':
        return 'watch'
    return band


def _apply_band_uplift(
    *,
    band: str,
    must_have_score: float,
    confidence: str,
    family_aligned: bool,
    title_similarity: float,
    missing_required_count: int,
    preferred_score: float,
    pipeline_signal: float,
) -> tuple[str, bool, str]:
    if missing_required_count > 0:
        return band, False, ''
    if must_have_score < 0.999:
        return band, False, ''
    if confidence != 'high':
        return band, False, ''
    if not family_aligned:
        return band, False, ''
    if title_similarity < 0.45:
        return band, False, ''

    negative_signal = preferred_score < 0.15 and pipeline_signal < 0.2
    if negative_signal:
        return band, False, ''

    if band == 'watch':
        return 'good', True, 'uplifted_for_exact_required_high_confidence_family_aligned_adjacent_title'
    return band, False, ''


def _ranking_confidence(role_profile: dict[str, Any], semantic_similarity: float, required_count: int, preferred_count: int, used_title_inference: bool) -> tuple[str, str]:
    if role_profile.get('role_profile_is_sparse'):
        return 'low', 'sparse_role'
    if used_title_inference and required_count <= 2 and semantic_similarity < 0.35:
        return 'low', 'title_inference_with_weak_semantics'
    if required_count == 0 and preferred_count == 0:
        return 'low', 'no_skill_requirements'
    if semantic_similarity < 0.25 and required_count < 2:
        return 'low', 'very_low_semantic_similarity'
    if semantic_similarity < 0.45 or used_title_inference:
        return 'medium', 'moderate_semantic_similarity_or_title_inference'
    return 'high', 'strong_semantic_alignment'


def _calibrate_semantic_similarity(
    *,
    raw_similarity: float,
    must_have_score: float,
    title_similarity: float,
    preferred_score: float,
    graph_related_count: int,
    family_aligned: bool,
) -> float:
    calibrated = max(0.0, min(1.0, raw_similarity))

    if must_have_score >= 0.999 and title_similarity >= 0.78:
        calibrated = max(calibrated, get_semantic_floor_full_match())
    elif must_have_score >= 0.9 and title_similarity >= 0.58 and (graph_related_count > 0 or family_aligned):
        calibrated = max(calibrated, get_semantic_floor_strong_adjacent())
    elif must_have_score >= 0.8 and title_similarity >= 0.5 and preferred_score >= 0.4:
        calibrated = max(calibrated, 0.5)

    return max(0.0, min(1.0, calibrated))


def _semantic_floor_debug(
    *,
    raw_similarity: float,
    calibrated_similarity: float,
    must_have_score: float,
    title_similarity: float,
    family_aligned: bool,
) -> tuple[bool, str]:
    if calibrated_similarity <= raw_similarity:
        return False, ''
    if must_have_score >= 0.999 and title_similarity >= 0.45 and family_aligned:
        return True, 'full_required_match_with_title_and_family_alignment'
    if must_have_score >= 0.9 and title_similarity >= 0.45 and family_aligned:
        return True, 'strong_adjacent_title_with_family_alignment'
    return True, 'semantic_floor_calibration_applied'


def rerank_candidate(role_profile: dict[str, Any], candidate_profile: dict[str, Any]) -> dict[str, Any]:
    required_skills = _dedupe_preserve_order(role_profile.get('required_skills') or role_profile.get('exact_required_skills') or [])
    preferred_skills = _dedupe_preserve_order(role_profile.get('preferred_skills') or [])
    normalized_required_inputs = _dedupe_preserve_order([*(role_profile.get('exact_required_skills') or []), *(role_profile.get('normalized_required_skills') or []), *required_skills])
    normalized_preferred_inputs = _dedupe_preserve_order([*(role_profile.get('normalized_preferred_skills') or []), *preferred_skills])
    exact_candidate_skills = _dedupe_preserve_order(candidate_profile.get('exact_candidate_skills') or candidate_profile.get('normalized_candidate_skills') or [])
    candidate_skill_inputs = _dedupe_preserve_order([*exact_candidate_skills, *(candidate_profile.get('skills') or [])])

    role_required = _exact_skill_set(normalized_required_inputs)
    role_preferred = _exact_skill_set(normalized_preferred_inputs)
    candidate_skills = _exact_skill_set(candidate_skill_inputs)

    required_graph = _graph_skill_score(required_skills, candidate_skill_inputs)
    preferred_graph = _graph_skill_score(preferred_skills, candidate_skill_inputs)
    matched_required = required_graph['matched_skills']
    missing_required = required_graph['missing_skills']
    matched_preferred = preferred_graph['matched_skills']

    semantic_similarity_raw = float(candidate_profile.get('semantic_similarity_raw', candidate_profile.get('semantic_similarity') or 0.0))
    normalized_required_skills = canonical_display_list_from_tokens(role_required)
    normalized_candidate_skills = exact_candidate_skills or canonical_display_list_from_tokens(candidate_skills)
    normalized_preferred_skills = canonical_display_list_from_tokens(role_preferred)

    must_have_score = float(required_graph['score'])
    preferred_score = float(preferred_graph['score'])
    experience_fit = _experience_fit(role_profile, candidate_profile)
    base_title_similarity = _title_similarity(role_profile, candidate_profile)
    title_graph = title_adjacency(
        role_profile.get('title', ''),
        candidate_profile.get('title', '') or candidate_profile.get('headline', ''),
        role_family=role_profile.get('role_family', ''),
        role_subfamily=role_profile.get('role_subfamily', ''),
        candidate_primary_family=candidate_profile.get('candidate_primary_family', ''),
    )
    family_alignment_bonus = (
        get_graph_family_alignment_bonus()
        if role_profile.get('role_family') and role_profile.get('role_family') == candidate_profile.get('candidate_primary_family')
        else 0.0
    )
    family_aligned = bool(role_profile.get('role_family') and role_profile.get('role_family') == candidate_profile.get('candidate_primary_family'))
    title_similarity = max(
        base_title_similarity,
        min(1.0, (base_title_similarity * (1.0 - get_graph_title_adjacency_blend())) + (float(title_graph.get('score') or 0.0) * get_graph_title_adjacency_blend()) + family_alignment_bonus),
    )
    location_match = _location_match(role_profile, candidate_profile)
    pipeline_signal, pipeline_signal_meta = _pipeline_signal(candidate_profile, role_profile)
    semantic_similarity = _calibrate_semantic_similarity(
        raw_similarity=semantic_similarity_raw,
        must_have_score=must_have_score,
        title_similarity=title_similarity,
        preferred_score=preferred_score,
        graph_related_count=len(required_graph['related_skill_matches']),
        family_aligned=family_aligned,
    )
    semantic_floor_applied, semantic_floor_reason = _semantic_floor_debug(
        raw_similarity=semantic_similarity_raw,
        calibrated_similarity=semantic_similarity,
        must_have_score=must_have_score,
        title_similarity=title_similarity,
        family_aligned=family_aligned,
    )

    confidence, confidence_reason = _ranking_confidence(
        role_profile,
        semantic_similarity,
        len(required_skills),
        len(preferred_skills),
        bool(role_profile.get('used_title_inference')),
    )
    confidence_adjustment_reason = confidence_reason
    confidence_upgrade_reason = ''
    confidence_downgrade_reason = confidence_reason if confidence in {'low', 'medium'} else ''
    if must_have_score >= 0.999 and title_similarity >= 0.45 and family_aligned and confidence in {'medium', 'low'}:
        confidence = 'high'
        confidence_upgrade_reason = 'promoted_for_exact_match_title_and_family_alignment'
        confidence_adjustment_reason = confidence_upgrade_reason
        confidence_downgrade_reason = ''
    elif must_have_score >= 0.999 and title_similarity >= 0.58 and confidence == 'medium':
        confidence = 'high'
        confidence_upgrade_reason = 'promoted_for_exact_required_and_strong_title_alignment'
        confidence_adjustment_reason = confidence_upgrade_reason
        confidence_downgrade_reason = ''
    elif must_have_score >= 0.9 and title_similarity >= 0.45 and family_aligned and confidence == 'low':
        confidence = 'medium'
        confidence_upgrade_reason = 'promoted_for_family_aligned_strong_adjacent_match'
        confidence_adjustment_reason = confidence_upgrade_reason
        confidence_downgrade_reason = ''
    elif must_have_score >= 0.9 and title_similarity >= 0.5 and confidence == 'low':
        confidence = 'medium'
        confidence_upgrade_reason = 'promoted_for_strong_adjacent_match'
        confidence_adjustment_reason = confidence_upgrade_reason
        confidence_downgrade_reason = ''

    weights = get_scoring_weights(sparse_role=bool(role_profile.get('role_profile_is_sparse')))

    component_scores = {
        'semantic_similarity': semantic_similarity,
        'must_have_skills': must_have_score,
        'preferred_skills': preferred_score,
        'experience_fit': experience_fit,
        'title_similarity': title_similarity,
        'location_match': location_match,
        'pipeline_signal': pipeline_signal,
    }

    total_score = sum(component_scores[key] * weight for key, weight in weights.items())
    if confidence == 'low':
        total_score *= get_sparse_role_confidence_penalty()
    elif confidence == 'medium':
        total_score *= get_medium_confidence_penalty()

    ai_score = max(0, min(100, int(round(total_score * 100))))
    pre_calibration_band = _band(ai_score, confidence)
    capped_band = _apply_band_caps(
        band=pre_calibration_band,
        confidence=confidence,
        required_count=len(required_skills),
        missing_required_count=required_graph['missing_required_skills_count'],
        role_profile_is_sparse=bool(role_profile.get('role_profile_is_sparse')),
    )
    ai_band, band_calibration_applied, band_calibration_reason = _apply_band_uplift(
        band=capped_band,
        must_have_score=must_have_score,
        confidence=confidence,
        family_aligned=family_aligned,
        title_similarity=title_similarity,
        missing_required_count=required_graph['missing_required_skills_count'],
        preferred_score=preferred_score,
        pipeline_signal=pipeline_signal,
    )

    explanations = build_explanations(
        role_profile=role_profile,
        candidate_profile=candidate_profile,
        matched_skills=matched_required or matched_preferred,
        missing_skills=missing_required,
        component_scores=component_scores,
        pipeline_signal_meta=pipeline_signal_meta,
        ranking_confidence=confidence,
        graph_context={
            'related_skill_matches': required_graph['related_skill_matches'],
            'related_skill_matches_summary': required_graph['related_skill_matches_summary'],
            'exact_skill_matches': required_graph['exact_skill_matches'],
            'title_adjacency_reason': title_graph.get('reason', ''),
            'graph_boost_applied': title_similarity > base_title_similarity or bool(required_graph['related_skill_matches']),
        },
    )

    graph_boost_applied = title_similarity > base_title_similarity or bool(required_graph['related_skill_matches'])

    return {
        'ai_score': ai_score,
        'ai_band': ai_band,
        'pre_calibration_band': pre_calibration_band,
        'post_calibration_band': ai_band,
        'band_calibration_applied': band_calibration_applied,
        'band_calibration_reason': band_calibration_reason,
        'matched_skills': (matched_required or matched_preferred)[:6],
        'missing_skills': missing_required[:6],
        'required_skills_count': len(required_skills),
        'matched_required_skills_count': required_graph['matched_required_skills_count'],
        'missing_required_skills_count': required_graph['missing_required_skills_count'],
        'matched_required_skills': matched_required[:],
        'missing_required_skills': missing_required[:],
        'exact_required_skills': role_profile.get('exact_required_skills', normalized_required_skills),
        'exact_skill_matches': required_graph['exact_skill_matches'],
        'related_skill_matches': required_graph['related_skill_matches'],
        'related_skill_matches_summary': required_graph['related_skill_matches_summary'],
        'exact_candidate_skills': exact_candidate_skills,
        'candidate_related_skill_evidence': candidate_profile.get('candidate_related_skill_evidence', {}),
        'role_supporting_skill_inference': role_profile.get('role_supporting_skill_inference', []),
        'role_adjacent_skill_inference': role_profile.get('role_adjacent_skill_inference', []),
        'normalized_required_skills': normalized_required_skills,
        'normalized_preferred_skills': normalized_preferred_skills,
        'normalized_candidate_skills': normalized_candidate_skills,
        'component_scores': component_scores,
        'semantic_similarity_raw': round(semantic_similarity_raw, 4),
        'semantic_similarity_calibrated': round(semantic_similarity, 4),
        'semantic_floor_applied': semantic_floor_applied,
        'semantic_floor_reason': semantic_floor_reason,
        'semantic_similarity_score': round(semantic_similarity * 100, 2),
        'must_have_score': round(must_have_score * 100, 2),
        'preferred_score': round(preferred_score * 100, 2),
        'experience_fit_score': round(experience_fit * 100, 2),
        'title_fit_score': round(title_similarity * 100, 2),
        'location_score': round(location_match * 100, 2),
        'pipeline_signal_score': round(pipeline_signal * 100, 2),
        'role_profile_is_sparse': bool(role_profile.get('role_profile_is_sparse')),
        'role_family': role_profile.get('role_family', ''),
        'role_subfamily': role_profile.get('role_subfamily', ''),
        'candidate_primary_family': candidate_profile.get('candidate_primary_family', ''),
        'candidate_secondary_families': candidate_profile.get('candidate_secondary_families', []),
        'title_adjacency_reason': title_graph.get('reason', ''),
        'graph_boost_applied': graph_boost_applied,
        'inferred_role_family': role_profile.get('inferred_role_family', ''),
        'used_title_inference': bool(role_profile.get('used_title_inference')),
        'ranking_confidence': confidence,
        'confidence_adjustment_reason': confidence_adjustment_reason,
        'confidence_upgrade_reason': confidence_upgrade_reason,
        'confidence_downgrade_reason': confidence_downgrade_reason,
        'explanations': explanations,
    }
