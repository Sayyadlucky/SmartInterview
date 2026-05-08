from __future__ import annotations

from typing import Any


def build_explanations(
    *,
    role_profile: dict[str, Any],
    candidate_profile: dict[str, Any],
    matched_skills: list[str],
    missing_skills: list[str],
    component_scores: dict[str, float],
    pipeline_signal_meta: dict[str, Any],
    ranking_confidence: str,
    graph_context: dict[str, Any] | None = None,
) -> list[str]:
    explanations: list[str] = []
    graph_context = graph_context or {}

    if role_profile.get('role_profile_is_sparse'):
        explanations.append('Role requirements are limited, so confidence is lower.')

    experience_years = float(candidate_profile.get('experience_years') or 0)
    if experience_years > 0:
        explanations.append(f'{experience_years:.1f} years of relevant experience from resume history.')

    if matched_skills:
        preview = ', '.join(matched_skills[:3])
        if role_profile.get('used_title_inference'):
            explanations.append(f'Matched signals against inferred role family skills: {preview}.')
        else:
            explanations.append(f'Strong overlap with required stack: {preview}.')

    related_skill_matches = graph_context.get('related_skill_matches') or []
    if related_skill_matches:
        top_related = related_skill_matches[0]
        required_skill = top_related.get('required_skill', '')
        evidence_skill = top_related.get('matched_candidate_skill', '')
        if required_skill and evidence_skill:
            explanations.append(f'{required_skill} evidence inferred through adjacent skill experience in {evidence_skill}.')

    title = (candidate_profile.get('title') or candidate_profile.get('headline') or '').strip()
    role_title = (role_profile.get('title') or '').strip()
    if title and role_title and component_scores.get('title_similarity', 0) >= 0.75:
        explanations.append(f'Recent title alignment with {role_title} responsibilities.')
    elif role_profile.get('inferred_role_family') and component_scores.get('title_similarity', 0) < 0.45:
        explanations.append(
            f'General engineering background detected, but {role_title} specialization is not strongly evidenced.'
        )

    title_adjacency_reason = (graph_context.get('title_adjacency_reason') or '').strip()
    if title_adjacency_reason:
        explanations.append(title_adjacency_reason)

    if component_scores.get('location_match', 0) >= 0.9 and role_profile.get('location'):
        explanations.append(f'Location is aligned with the role requirement in {role_profile.get("location")}.')

    average_interview_score = pipeline_signal_meta.get('average_interview_score')
    if average_interview_score is not None and average_interview_score >= 70:
        explanations.append(f'Past interview performance is strong with an average score of {int(round(average_interview_score))}.')

    if missing_skills:
        explanations.append(f'Primary gap to validate: {", ".join(missing_skills[:2])}.')

    if ranking_confidence == 'low' and not role_profile.get('role_profile_is_sparse'):
        explanations.append('Signal quality is limited, so this recommendation should be validated manually.')

    if related_skill_matches and missing_skills:
        explanations.append('Candidate has adjacent rather than exact specialization on part of the required stack.')

    unique_explanations: list[str] = []
    seen: set[str] = set()
    for explanation in explanations:
        text = explanation.strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        unique_explanations.append(text)
    return unique_explanations[:4]
