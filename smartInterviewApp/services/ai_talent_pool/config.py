from __future__ import annotations

from django.conf import settings


DEFAULT_SCORING_WEIGHTS = {
    'semantic_similarity': 0.35,
    'must_have_skills': 0.25,
    'preferred_skills': 0.10,
    'experience_fit': 0.10,
    'title_similarity': 0.10,
    'location_match': 0.05,
    'pipeline_signal': 0.05,
}

SPARSE_ROLE_SCORING_WEIGHTS = {
    'semantic_similarity': 0.30,
    'must_have_skills': 0.20,
    'preferred_skills': 0.05,
    'experience_fit': 0.15,
    'title_similarity': 0.15,
    'location_match': 0.05,
    'pipeline_signal': 0.10,
}

DEFAULT_SPARSE_ROLE_CONFIDENCE_PENALTY = 0.72
DEFAULT_MEDIUM_CONFIDENCE_PENALTY = 0.88
DEFAULT_GRAPH_EXACT_MATCH_BONUS = 0.0
DEFAULT_GRAPH_RELATED_MATCH_CAP = 0.92
DEFAULT_GRAPH_TITLE_ADJACENCY_BLEND = 0.65
DEFAULT_GRAPH_FAMILY_ALIGNMENT_BONUS = 0.08
DEFAULT_SEMANTIC_FLOOR_FULL_MATCH = 0.72
DEFAULT_SEMANTIC_FLOOR_STRONG_ADJACENT = 0.58


def _setting_float(name: str, default: float) -> float:
    value = getattr(settings, name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def get_scoring_weights(*, sparse_role: bool) -> dict[str, float]:
    base = SPARSE_ROLE_SCORING_WEIGHTS if sparse_role else DEFAULT_SCORING_WEIGHTS
    prefix = 'AI_TALENT_POOL_SPARSE_WEIGHT_' if sparse_role else 'AI_TALENT_POOL_WEIGHT_'
    return {
        key: _setting_float(f'{prefix}{key.upper()}', default)
        for key, default in base.items()
    }


def get_sparse_role_confidence_penalty() -> float:
    return _setting_float('AI_TALENT_POOL_SPARSE_ROLE_CONFIDENCE_PENALTY', DEFAULT_SPARSE_ROLE_CONFIDENCE_PENALTY)


def get_medium_confidence_penalty() -> float:
    return _setting_float('AI_TALENT_POOL_MEDIUM_CONFIDENCE_PENALTY', DEFAULT_MEDIUM_CONFIDENCE_PENALTY)


def get_graph_exact_match_bonus() -> float:
    return _setting_float('AI_TALENT_POOL_GRAPH_EXACT_MATCH_BONUS', DEFAULT_GRAPH_EXACT_MATCH_BONUS)


def get_graph_related_match_cap() -> float:
    return _setting_float('AI_TALENT_POOL_GRAPH_RELATED_MATCH_CAP', DEFAULT_GRAPH_RELATED_MATCH_CAP)


def get_graph_title_adjacency_blend() -> float:
    return _setting_float('AI_TALENT_POOL_GRAPH_TITLE_ADJACENCY_BLEND', DEFAULT_GRAPH_TITLE_ADJACENCY_BLEND)


def get_graph_family_alignment_bonus() -> float:
    return _setting_float('AI_TALENT_POOL_GRAPH_FAMILY_ALIGNMENT_BONUS', DEFAULT_GRAPH_FAMILY_ALIGNMENT_BONUS)


def get_semantic_floor_full_match() -> float:
    return _setting_float('AI_TALENT_POOL_SEMANTIC_FLOOR_FULL_MATCH', DEFAULT_SEMANTIC_FLOOR_FULL_MATCH)


def get_semantic_floor_strong_adjacent() -> float:
    return _setting_float('AI_TALENT_POOL_SEMANTIC_FLOOR_STRONG_ADJACENT', DEFAULT_SEMANTIC_FLOOR_STRONG_ADJACENT)


def get_scoring_config_snapshot() -> dict[str, object]:
    return {
        'default_weights': get_scoring_weights(sparse_role=False),
        'sparse_role_weights': get_scoring_weights(sparse_role=True),
        'sparse_role_confidence_penalty': get_sparse_role_confidence_penalty(),
        'medium_confidence_penalty': get_medium_confidence_penalty(),
        'graph_exact_match_bonus': get_graph_exact_match_bonus(),
        'graph_related_match_cap': get_graph_related_match_cap(),
        'graph_title_adjacency_blend': get_graph_title_adjacency_blend(),
        'graph_family_alignment_bonus': get_graph_family_alignment_bonus(),
        'semantic_floor_full_match': get_semantic_floor_full_match(),
        'semantic_floor_strong_adjacent': get_semantic_floor_strong_adjacent(),
    }
