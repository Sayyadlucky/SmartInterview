from __future__ import annotations

from typing import Any

from .graph_taxonomy import ROLE_FAMILY_KEYWORDS, TITLE_ADJACENCY
from .skill_graph import canonical_skill_name, infer_role_family_from_skills, normalize_graph_text


def normalize_title(value: str) -> str:
    normalized = normalize_graph_text(value)
    if not normalized:
        return ''

    replacements = {
        'hr recruiter': 'recruiter',
        'talent acquisition specialist': 'talent acquisition specialist',
        'biz dev': 'business development',
        'business development executive': 'business development executive',
        'customer relationship management': 'crm',
        'salesfore': 'salesforce',
        'reactjs': 'react',
        'nodejs': 'node js',
        'full stack': 'fullstack',
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return ' '.join(normalized.split())


def title_display(value: str) -> str:
    title = normalize_title(value)
    if not title:
        return ''
    words = []
    for token in title.split():
        if token == 'crm':
            words.append('CRM')
        elif token == 'ui':
            words.append('UI')
        elif token == 'ux':
            words.append('UX')
        elif token == 'ml':
            words.append('ML')
        elif token == 'ai':
            words.append('AI')
        elif token == 'qa':
            words.append('QA')
        else:
            words.append(token.capitalize())
    return ' '.join(words)


def infer_role_family(*, title: str, skills: list[str], description: str = '') -> dict[str, Any]:
    normalized_title = normalize_title(title)
    title_hits: list[tuple[str, str, int]] = []
    haystack = ' '.join(filter(None, [normalized_title, normalize_title(description)]))
    for key, entry in ROLE_FAMILY_KEYWORDS.items():
        family = str(entry.get('family') or key.split('_', 1)[0] or '')
        subfamily = str(entry.get('subfamily') or '')
        score = 0
        for alias in entry.get('title_aliases', []):
            alias_normalized = normalize_title(str(alias))
            if alias_normalized and alias_normalized in haystack:
                score += max(1, len(alias_normalized.split()))
        if score:
            title_hits.append((family, subfamily, score))

    title_hits.sort(key=lambda item: (-item[2], item[0], item[1]))
    skill_family, skill_subfamily = infer_role_family_from_skills(skills)

    primary_family = title_hits[0][0] if title_hits else skill_family
    primary_subfamily = title_hits[0][1] if title_hits else skill_subfamily
    used_title_inference = bool(title_hits) and not bool(skills)

    return {
        'role_family': primary_family,
        'role_subfamily': primary_subfamily,
        'inferred_role_family': primary_subfamily or primary_family,
        'used_title_inference': used_title_inference,
    }


def infer_candidate_families(*, title: str, skills: list[str], summary: str = '') -> dict[str, Any]:
    title_data = infer_role_family(title=title, skills=skills, description=summary)
    family_buckets: dict[str, int] = {}
    for skill in skills:
        canonical = canonical_skill_name(skill)
        if not canonical:
            continue
        inferred = infer_role_family_from_skills([canonical])
        family = inferred[0]
        if not family:
            continue
        family_buckets[family] = family_buckets.get(family, 0) + 1

    ordered = [family for family, _count in sorted(family_buckets.items(), key=lambda item: (-item[1], item[0]))]
    primary = title_data.get('role_family') or (ordered[0] if ordered else '')
    secondary = [family for family in ordered if family != primary][:3]

    return {
        'candidate_primary_family': primary,
        'candidate_secondary_families': secondary,
    }


def title_adjacency(role_title: str, candidate_title: str, *, role_family: str = '', role_subfamily: str = '', candidate_primary_family: str = '') -> dict[str, Any]:
    role_display = title_display(role_title)
    candidate_display = title_display(candidate_title)
    role_normalized = normalize_title(role_title)
    candidate_normalized = normalize_title(candidate_title)

    if not role_normalized or not candidate_normalized:
        return {'score': 0.0, 'reason': ''}
    if role_normalized == candidate_normalized:
        return {'score': 1.0, 'reason': f'Exact title match: {candidate_display}.'}

    adjacency_map = TITLE_ADJACENCY.get(role_display, {})
    if candidate_display in adjacency_map:
        return {
            'score': float(adjacency_map[candidate_display]),
            'reason': f'Adjacent title match detected: {candidate_display} -> {role_display}.',
        }

    if role_subfamily and role_family and candidate_primary_family == role_family:
        return {
            'score': 0.62 if role_subfamily else 0.55,
            'reason': f'Family-level title alignment detected within {role_family.replace("_", " ")} roles.',
        }

    generic_titles = {'software engineer', 'engineer', 'developer', 'executive', 'associate', 'manager'}
    if candidate_normalized in generic_titles:
        return {'score': 0.32, 'reason': f'Generic title overlap exists, but {role_display} remains more specialized.'}

    role_tokens = set(role_normalized.split())
    candidate_tokens = set(candidate_normalized.split())
    overlap = len(role_tokens & candidate_tokens) / max(1, len(role_tokens))
    if overlap > 0:
        return {'score': min(0.7, 0.38 + (overlap * 0.28)), 'reason': 'Partial title-token overlap detected.'}

    return {'score': 0.0, 'reason': ''}
