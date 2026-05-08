from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import QuerySet

from smartInterviewApp.models import CandidateSearchProfile, RoleSearchCache, Vacancies
from smartInterviewApp.pgvector_compat import HAS_PGVECTOR
from .candidate_profile_builder import build_role_aware_candidate_embedding_payload
from .embeddings import EMBEDDING_DIMENSION, cosine_similarity, get_embedding, raw_cosine_similarity
from .search_index import build_role_query_signature, build_role_search_text, normalize_location
from .skill_graph import best_skill_evidence

try:  # pragma: no cover - import path varies by environment
    from pgvector.django import CosineDistance
except Exception:  # pragma: no cover
    CosineDistance = None


logger = logging.getLogger(__name__)
ROLE_EMBEDDING_CACHE_TIMEOUT_SECONDS = 60 * 60 * 12


class RetrievalBackendUnavailable(RuntimeError):
    pass


def _coerce_vector(value: Any) -> list[float]:
    if value is None:
        return []
    try:
        return [float(item) for item in list(value)]
    except Exception:
        return []


def _profile_embedding_vector(profile: CandidateSearchProfile) -> list[float]:
    json_vector = _coerce_vector(profile.embedding_json)
    if json_vector:
        return json_vector
    return _coerce_vector(profile.embedding)


def _distance_similarity_debug(distance: float) -> tuple[float, float]:
    similarity_before_clamp = 1.0 - float(distance)
    similarity_after_clamp = max(-1.0, min(1.0, similarity_before_clamp))
    return similarity_before_clamp, similarity_after_clamp


def _using_postgres() -> bool:
    return connection.vendor == 'postgresql'


def _pgvector_ready() -> bool:
    return HAS_PGVECTOR and _using_postgres() and CosineDistance is not None


def _retrieval_backend_status() -> dict[str, Any]:
    using_postgres = _using_postgres()
    pgvector_backend_available = bool(HAS_PGVECTOR and CosineDistance is not None)
    pgvector_enabled = bool(_pgvector_ready())
    fallback_reason = ''
    if not pgvector_enabled:
        if not using_postgres:
            fallback_reason = 'database_vendor_not_postgresql'
        elif not HAS_PGVECTOR:
            fallback_reason = 'pgvector_python_package_missing'
        elif CosineDistance is None:
            fallback_reason = 'pgvector_distance_operator_unavailable'
        else:
            fallback_reason = 'pgvector_backend_unavailable'
    return {
        'pgvector_enabled': pgvector_enabled,
        'pgvector_backend_available': pgvector_backend_available,
        'retrieval_fallback_reason': fallback_reason,
    }


def require_retrieval_backend() -> None:
    if _pgvector_ready():
        return
    if (
        not getattr(settings, 'AI_TALENT_POOL_REQUIRE_PGVECTOR', True)
        and getattr(settings, 'AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK', False)
    ):
        return
    raise RetrievalBackendUnavailable(
        'AI Talent Pool indexed retrieval requires PostgreSQL + pgvector in this environment. '
        'Enable pgvector and run the candidate search profile backfill, or explicitly allow local index scan fallback for development.'
    )


def _location_tokens(value: str) -> set[str]:
    normalized = normalize_location(value)
    if not normalized:
        return set()
    tokens = {
        token for token in re.split(r'\s+', normalized)
        if token and not token.isdigit() and len(token) > 1
    }
    return tokens


def _role_family_matches(profile: CandidateSearchProfile, role_profile: dict[str, Any]) -> bool:
    role_family = str(role_profile.get('role_family') or '').strip()
    if not role_family:
        return True
    if str(profile.role_family or '').strip() == role_family:
        return True
    exposure = {str(item).strip() for item in (profile.domain_exposure or []) if str(item).strip()}
    return role_family in exposure


def _subfamily_matches(profile: CandidateSearchProfile, role_profile: dict[str, Any]) -> bool:
    role_subfamily = str(role_profile.get('role_subfamily') or '').strip()
    if not role_subfamily:
        return True
    candidate_subfamily = str(profile.role_subfamily or '').strip()
    if not candidate_subfamily:
        return True
    return candidate_subfamily == role_subfamily


def _experience_matches(profile: CandidateSearchProfile, role_profile: dict[str, Any]) -> bool:
    range_info = role_profile.get('experience_range') or {}
    min_years = range_info.get('min_years')
    max_years = range_info.get('max_years')
    experience = profile.experience_years
    if experience is None:
        return True
    try:
        experience_value = float(experience)
    except (TypeError, ValueError):
        return True

    if min_years is not None and experience_value < max(0.0, float(min_years) - 1.0):
        return False
    if max_years is not None and experience_value > float(max_years) + 4.0:
        return False
    return True


def _location_matches(profile: CandidateSearchProfile, role_profile: dict[str, Any]) -> bool:
    if role_profile.get('remote_friendly'):
        return True
    role_tokens = _location_tokens(str(role_profile.get('location') or ''))
    if not role_tokens:
        return True
    candidate_tokens = _location_tokens(str(profile.location_normalized or ''))
    if not candidate_tokens:
        return True
    return bool(role_tokens & candidate_tokens)


def _skill_prefilter_matches(profile: CandidateSearchProfile, role_profile: dict[str, Any]) -> bool:
    required_skills = list(role_profile.get('exact_required_skills') or [])
    if not required_skills:
        return True
    candidate_skills = list(profile.normalized_skills or [])
    if not candidate_skills:
        return True
    return any(float(best_skill_evidence(skill, candidate_skills).get('score') or 0.0) > 0.0 for skill in required_skills[:6])


def _profile_debug_payload(profile: CandidateSearchProfile, reasons: list[str]) -> dict[str, Any]:
    return {
        'candidate_id': profile.candidate_id,
        'normalized_title': profile.normalized_title,
        'role_family': profile.role_family,
        'role_subfamily': profile.role_subfamily,
        'experience_years': float(profile.experience_years) if profile.experience_years is not None else None,
        'location_normalized': profile.location_normalized,
        'is_active': profile.is_active,
        'inactive_reason': profile.inactive_reason,
        'active_resume_found': profile.active_resume_found,
        'searchable_profile_built': profile.searchable_profile_built,
        'missing_fields_summary': list(profile.missing_fields_summary or []),
        'reasons': reasons,
    }


def _infer_inactive_reason(profile: CandidateSearchProfile) -> str:
    explicit = str(profile.inactive_reason or '').strip()
    if explicit:
        return explicit
    if not profile.active_resume_found or profile.active_resume_id is None:
        return 'no_active_resume'
    metadata = profile.search_metadata or {}
    resume_status = str(metadata.get('resume_status') or '').strip().lower()
    if resume_status and resume_status != 'completed':
        return 'no_parsed_resume'
    if list(profile.missing_fields_summary or []):
        return 'missing_required_profile_fields'
    if not profile.searchable_profile_built:
        return 'insufficient_searchable_signal'
    return 'inactive_unspecified'


def _vector_index_diagnostics() -> dict[str, Any]:
    diagnostics = {
        'vector_index_present': False,
        'vector_index_type': '',
        'explain_plan_summary': '',
    }
    if not _using_postgres():
        return diagnostics
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'smartInterviewApp_candidatesearchprofile'
                  AND indexname = 'cand_search_embedding_hnsw'
                """
            )
            row = cursor.fetchone()
            if row:
                diagnostics['vector_index_present'] = True
                indexdef = str(row[1] or '')
                if 'USING hnsw' in indexdef:
                    diagnostics['vector_index_type'] = 'hnsw'
                elif 'USING ivfflat' in indexdef:
                    diagnostics['vector_index_type'] = 'ivfflat'
                else:
                    diagnostics['vector_index_type'] = 'other'
    except Exception:
        logger.exception('Unable to inspect pgvector index diagnostics.')
    return diagnostics


def _candidate_profile_from_search_profile(profile: CandidateSearchProfile) -> dict[str, Any]:
    metadata = profile.search_metadata or {}
    recent_companies = list(profile.recent_companies or [])
    experience_items: list[dict[str, Any]] = []
    if profile.latest_role_summary or recent_companies:
        experience_items.append({
            'role': metadata.get('title') or profile.latest_role_summary or profile.normalized_title,
            'company': recent_companies[0] if recent_companies else '',
            'tech_stack': list(metadata.get('exact_candidate_skills', []) or profile.normalized_skills or []),
        })
    return {
        'candidate_id': profile.candidate_id,
        'title': metadata.get('title') or profile.normalized_title,
        'headline': metadata.get('headline', ''),
        'summary': metadata.get('summary', ''),
        'location': metadata.get('location') or profile.location_normalized,
        'exact_candidate_skills': list(metadata.get('exact_candidate_skills', []) or profile.normalized_skills or []),
        'normalized_candidate_skills': list(profile.normalized_skills or []),
        'experience_items': experience_items,
        'project_items': [],
    }


def _role_embedding_cache_key(query_signature: str, vacancy_id: int | None = None) -> str:
    scope = vacancy_id or 'query'
    return f'ai-talent-pool:role-embedding:{scope}:{query_signature}'


def _role_aware_embedding_debug(profile: CandidateSearchProfile, role_profile: dict[str, Any], role_embedding: list[float]) -> dict[str, Any]:
    candidate_profile = _candidate_profile_from_search_profile(profile)
    candidate_embedding_payload = build_role_aware_candidate_embedding_payload(candidate_profile, role_profile)
    candidate_embedding_text = candidate_embedding_payload.get('embedding_text', '') or profile.search_text
    candidate_vector = get_embedding(candidate_embedding_text) if candidate_embedding_text else _profile_embedding_vector(profile)
    raw_role_aware_cosine = raw_cosine_similarity(role_embedding, candidate_vector) if candidate_vector and role_embedding else 0.0
    role_aware_similarity = max(0.0, raw_role_aware_cosine)
    clamp_reason = ''
    if raw_role_aware_cosine < 0:
        clamp_reason = 'negative_role_aware_cosine_clamped_to_zero'
    return {
        'candidate_embedding_text': candidate_embedding_text,
        'candidate_embedding_text_token_count': candidate_embedding_payload.get('embedding_text_token_count', 0),
        'selected_embedding_skills': candidate_embedding_payload.get('selected_embedding_skills', []),
        'omitted_embedding_skills': candidate_embedding_payload.get('omitted_embedding_skills', []),
        'embedding_selection_source': 'role_aware_candidate_embedding',
        'embedding_text_builder_version': candidate_embedding_payload.get('embedding_text_builder_version', ''),
        'candidate_embedding_sections_used': candidate_embedding_payload.get('candidate_embedding_sections_used', []),
        'candidate_embedding_present': len(candidate_vector) > 0,
        'role_embedding_present': len(role_embedding) > 0,
        'candidate_embedding_dimension': len(candidate_vector),
        'role_embedding_dimension': len(role_embedding),
        'cosine_similarity_before_calibration': round(raw_role_aware_cosine, 6),
        'recomputed_role_aware_cosine_similarity': round(raw_role_aware_cosine, 6),
        'semantic_similarity_raw': round(role_aware_similarity, 6),
        'semantic_similarity': round(role_aware_similarity, 6),
        'semantic_score_source': 'recomputed_role_aware_cosine',
        'semantic_score_clamp_reason': clamp_reason,
    }


def _apply_prefilters(role_profile: dict[str, Any], accessible_candidate_ids) -> tuple[QuerySet[CandidateSearchProfile], dict[str, Any]]:
    all_profiles = list(
        CandidateSearchProfile.objects
        .select_related('candidate', 'active_resume')
        .filter(candidate_id__in=accessible_candidate_ids)
    )
    total_profiles = len(all_profiles)
    base_qs = (
        CandidateSearchProfile.objects
        .select_related('candidate', 'active_resume')
        .filter(is_active=True, candidate_id__in=accessible_candidate_ids)
    )
    active_profiles = base_qs.count()
    profiles = list(base_qs)
    inactive_reason_counts: dict[str, int] = {}
    inactive_profiles: list[dict[str, Any]] = []
    for profile in all_profiles:
        if profile.is_active:
            continue
        reason = _infer_inactive_reason(profile)
        inactive_reason_counts[reason] = inactive_reason_counts.get(reason, 0) + 1
        inactive_profiles.append(_profile_debug_payload(profile, [reason]))

    strict_subfamily = bool(getattr(settings, 'AI_TALENT_POOL_ENABLE_STRICT_SUBFAMILY_PREFILTER', False))
    exclusion_reasons: list[dict[str, Any]] = []
    subfamily_excluded_candidate_ids: list[int] = []

    family_pass: list[CandidateSearchProfile] = []
    for profile in profiles:
        if _role_family_matches(profile, role_profile):
            family_pass.append(profile)
        else:
            exclusion_reasons.append(_profile_debug_payload(profile, ['role_family_mismatch']))

    subfamily_pass: list[CandidateSearchProfile] = []
    for profile in family_pass:
        if not strict_subfamily or _subfamily_matches(profile, role_profile):
            subfamily_pass.append(profile)
            continue
        subfamily_excluded_candidate_ids.append(profile.candidate_id)
        exclusion_reasons.append(_profile_debug_payload(profile, ['role_subfamily_mismatch']))

    skill_pass: list[CandidateSearchProfile] = []
    for profile in subfamily_pass:
        if _skill_prefilter_matches(profile, role_profile):
            skill_pass.append(profile)
        else:
            exclusion_reasons.append(_profile_debug_payload(profile, ['skill_prefilter_mismatch']))

    experience_pass: list[CandidateSearchProfile] = []
    for profile in skill_pass:
        if _experience_matches(profile, role_profile):
            experience_pass.append(profile)
        else:
            exclusion_reasons.append(_profile_debug_payload(profile, ['experience_range_mismatch']))

    location_pass: list[CandidateSearchProfile] = []
    for profile in experience_pass:
        if _location_matches(profile, role_profile):
            location_pass.append(profile)
        else:
            exclusion_reasons.append(_profile_debug_payload(profile, ['location_mismatch']))

    final_candidate_ids = [profile.id for profile in location_pass]
    diagnostics = {
        'total_profiles': total_profiles,
        'active_profiles': active_profiles,
        'inactive_profiles': total_profiles - active_profiles,
        'inactive_reason_counts': inactive_reason_counts,
        'inactive_profile_diagnostics': inactive_profiles,
        'family_filtered_count': len(family_pass),
        'subfamily_filtered_count': len(subfamily_pass),
        'skill_prefilter_count': len(skill_pass),
        'experience_filtered_count': len(experience_pass),
        'location_filtered_count': len(location_pass),
        'final_prefilter_count': len(location_pass),
        'prefilter_candidate_count': len(location_pass),
        'role_subfamily_hard_filter_applied': strict_subfamily,
        'candidates_excluded_by_subfamily': subfamily_excluded_candidate_ids,
        'prefilter_exclusion_reasons': exclusion_reasons,
    }
    return base_qs.filter(id__in=final_candidate_ids), diagnostics


def _get_role_embedding(role_profile: dict[str, Any], *, vacancy: Vacancies | None = None) -> tuple[list[float], bool]:
    query_signature = build_role_query_signature(role_profile)
    cache_hit = False
    cache_key = _role_embedding_cache_key(query_signature, vacancy.id if vacancy else None)
    cached_cache_embedding = cache.get(cache_key)
    if isinstance(cached_cache_embedding, list) and cached_cache_embedding:
        return [float(value) for value in cached_cache_embedding], True

    if vacancy:
        cache_obj, _created = RoleSearchCache.objects.get_or_create(vacancy=vacancy)
        cached_embedding = _coerce_vector(cache_obj.embedding_json) or _coerce_vector(cache_obj.embedding)
        if cache_obj.query_signature == query_signature and cached_embedding:
            cache_hit = True
            cache.set(cache_key, cached_embedding, timeout=ROLE_EMBEDDING_CACHE_TIMEOUT_SECONDS)
            return cached_embedding, cache_hit

    embedding = get_embedding(role_profile.get('embedding_text', ''))
    cache.set(cache_key, embedding, timeout=ROLE_EMBEDDING_CACHE_TIMEOUT_SECONDS)
    if vacancy:
        cache_obj, _created = RoleSearchCache.objects.get_or_create(vacancy=vacancy)
        cache_obj.query_signature = query_signature
        cache_obj.role_family = str(role_profile.get('role_family', ''))
        cache_obj.role_subfamily = str(role_profile.get('role_subfamily', ''))
        cache_obj.location_normalized = normalize_location(role_profile.get('location', ''))
        cache_obj.search_text = build_role_search_text(role_profile)
        cache_obj.embedding = embedding
        cache_obj.embedding_json = embedding
        cache_obj.search_metadata = {
            'required_skills': role_profile.get('exact_required_skills', []),
            'preferred_skills': role_profile.get('normalized_preferred_skills', []),
        }
        if not cache_obj.indexed_at:
            cache_obj.indexed_at = getattr(vacancy, 'updated_at', None)
        cache_obj.save()
    return embedding, cache_hit


def _local_fallback_retrieval(qs: QuerySet[CandidateSearchProfile], role_profile: dict[str, Any], role_embedding: list[float], *, retrieval_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for profile in qs.iterator():
        candidate_embedding_debug = _role_aware_embedding_debug(profile, role_profile, role_embedding)
        vector = get_embedding(candidate_embedding_debug.get('candidate_embedding_text', '')) if candidate_embedding_debug.get('candidate_embedding_text') else _profile_embedding_vector(profile)
        if not vector:
            continue
        similarity = cosine_similarity(role_embedding, vector)
        results.append({
            'search_profile': profile,
            **candidate_embedding_debug,
            'pgvector_distance_metric': 'local_cosine_similarity',
            'distance_to_similarity_formula': 'local_cosine_similarity = cosine(role_embedding, role_aware_candidate_embedding)',
            'similarity_before_clamp': round(similarity, 6),
            'similarity_after_clamp': round(max(-1.0, min(1.0, similarity)), 6),
            'raw_vector_distance': round(1.0 - similarity, 6),
            'cosine_similarity_before_calibration': round(similarity, 6),
            'retrieval_distance': round(1.0 - similarity, 6),
            'retrieval_similarity': round(similarity, 6),
        })
    results.sort(key=lambda item: item['retrieval_distance'])
    ranked = []
    for index, item in enumerate(results[:retrieval_k], start=1):
        item['vector_rank'] = index
        item['retrieval_source'] = 'local_index_scan'
        ranked.append(item)
    return ranked, {'retrieval_source': 'local_index_scan'}


def retrieve_indexed_shortlist(
    *,
    role_profile: dict[str, Any],
    accessible_candidate_ids,
    top_k: int,
    vacancy: Vacancies | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    require_retrieval_backend()
    configured_shortlist = int(getattr(settings, 'AI_TALENT_POOL_RETRIEVAL_SHORTLIST_SIZE', 200) or 200)
    retrieval_k = max(100, min(configured_shortlist, 300))
    started = perf_counter()
    embedding_started = perf_counter()
    role_embedding, cache_hit = _get_role_embedding(role_profile, vacancy=vacancy)
    embedding_latency_ms = int((perf_counter() - embedding_started) * 1000)
    role_profile['embedding_text'] = role_profile.get('embedding_text') or build_role_search_text(role_profile)
    qs, prefilter_meta = _apply_prefilters(role_profile, accessible_candidate_ids)
    backend_status = _retrieval_backend_status()
    index_meta = _vector_index_diagnostics()

    if backend_status['pgvector_enabled']:
        query_started = perf_counter()
        qs = qs.exclude(embedding__isnull=True)
        ranked_qs = (
            qs
            .annotate(retrieval_distance=CosineDistance('embedding', role_embedding))
            .order_by('retrieval_distance')[:retrieval_k]
        )
        ranked_results = []
        for index, profile in enumerate(ranked_qs, start=1):
            distance_value = float(profile.retrieval_distance)
            similarity_before_clamp, similarity_after_clamp = _distance_similarity_debug(distance_value)
            candidate_embedding_debug = _role_aware_embedding_debug(profile, role_profile, role_embedding)
            ranked_results.append({
                'search_profile': profile,
                **candidate_embedding_debug,
                'retrieval_distance': round(distance_value, 6),
                'retrieval_similarity': round(float(candidate_embedding_debug.get('semantic_similarity_raw', 0.0)), 6),
                'indexed_similarity_from_pgvector': round(similarity_after_clamp, 6),
                'vector_rank': index,
                'retrieval_source': 'pgvector',
                'pgvector_distance_metric': 'cosine_distance',
                'distance_to_similarity_formula': 'indexed_similarity = 1 - cosine_distance',
                'similarity_before_clamp': round(similarity_before_clamp, 6),
                'similarity_after_clamp': round(similarity_after_clamp, 6),
                'raw_vector_distance': round(distance_value, 6),
            })
        diagnostics = {
            **prefilter_meta,
            **backend_status,
            **index_meta,
            'retrieval_source': 'pgvector',
            'retrieved_candidate_count': len(ranked_results),
            'role_embedding_latency_ms': embedding_latency_ms,
            'ann_query_latency_ms': int((perf_counter() - query_started) * 1000),
            'vector_search_latency_ms': int((perf_counter() - started) * 1000),
            'cached_role_embedding_used': cache_hit,
            'role_embedding_present': len(role_embedding) > 0,
            'role_embedding_dimension': len(role_embedding),
            'embedding_dimension_expected': EMBEDDING_DIMENSION,
        }
        if getattr(settings, 'AI_TALENT_POOL_DEBUG_LOGGING', False):
            try:
                diagnostics['explain_plan_summary'] = ranked_qs.explain(format='text')
            except Exception:
                logger.exception('Unable to generate pgvector explain plan summary.')
        return ranked_results, diagnostics

    query_started = perf_counter()
    ranked_results, fallback_meta = _local_fallback_retrieval(qs, role_profile, role_embedding, retrieval_k=retrieval_k)
    diagnostics = {
        **prefilter_meta,
        **backend_status,
        **index_meta,
        **fallback_meta,
        'retrieved_candidate_count': len(ranked_results),
        'role_embedding_latency_ms': embedding_latency_ms,
        'ann_query_latency_ms': int((perf_counter() - query_started) * 1000),
        'vector_search_latency_ms': int((perf_counter() - started) * 1000),
        'cached_role_embedding_used': cache_hit,
        'role_embedding_present': len(role_embedding) > 0,
        'role_embedding_dimension': len(role_embedding),
        'embedding_dimension_expected': EMBEDDING_DIMENSION,
    }
    return ranked_results, diagnostics
