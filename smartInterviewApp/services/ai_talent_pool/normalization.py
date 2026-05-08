from __future__ import annotations

from .skill_graph import canonical_skill_name, extract_canonical_skills, related_skill_weights, normalize_graph_text


def normalize_text(value: str) -> str:
    return normalize_graph_text(value)


def extract_skill_tokens(text: str) -> set[str]:
    return {normalize_text(canonical) for canonical in extract_canonical_skills(text)}


def extract_exact_display_skills(text: str, *, allow_ambiguous: bool = True) -> list[str]:
    return extract_canonical_skills(text, allow_ambiguous=allow_ambiguous)


def extract_display_skills(text: str) -> list[str]:
    return extract_exact_display_skills(text)


def canonicalize_skill_label(value: str) -> str:
    canonical = canonical_skill_name(value)
    return canonical or value.strip()


def expand_skill_label(value: str) -> set[str]:
    canonical = canonical_skill_name(value)
    if not canonical:
        return set()
    expanded = {normalize_text(skill) for skill in related_skill_weights(canonical).keys()}
    return expanded or {normalize_text(canonical)}


def canonical_display_list_from_tokens(tokens: set[str]) -> list[str]:
    labels = [canonical_skill_name(token) or token.title() for token in sorted(tokens)]
    seen: set[str] = set()
    output: list[str] = []
    for label in labels:
        key = normalize_text(label)
        if key in seen:
            continue
        seen.add(key)
        output.append(label)
    return output
