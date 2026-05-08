from __future__ import annotations

import logging
from collections import defaultdict
from time import perf_counter
from typing import Any

from django.conf import settings
from django.db.models import QuerySet

from smartInterviewApp.models import CandidateSearchProfile, Interview, Vacancies
from .config import get_scoring_config_snapshot
from .pgvector_retrieval import RetrievalBackendUnavailable, retrieve_indexed_shortlist
from .reranker import rerank_candidate
from .role_graph import title_display
from .role_profile_builder import build_query_profile, build_role_profile
from .search_index import build_role_search_text
from .skill_graph import build_related_skill_evidence


logger = logging.getLogger(__name__)


def _vector_values(value: Any) -> list[float]:
    if value is None:
        return []
    try:
        return [float(item) for item in list(value)]
    except Exception:
        return []


class AiTalentPoolService:
    def build_matches(
        self,
        *,
        role: Vacancies,
        top_k: int,
        accessible_interviews,
    ) -> dict[str, Any]:
        started = perf_counter()
        role_profile = build_role_profile(role)
        accessible_candidate_ids = accessible_interviews.values_list('candidate_id', flat=True).distinct()
        retrieved, retrieval_diagnostics = retrieve_indexed_shortlist(
            role_profile=role_profile,
            accessible_candidate_ids=accessible_candidate_ids,
            top_k=top_k,
            vacancy=role,
        )
        candidate_profiles = self._hydrate_indexed_candidates(retrieved, accessible_interviews)

        ranked_results: list[dict[str, Any]] = []
        for candidate in candidate_profiles:
            ranking = rerank_candidate(role_profile, candidate)
            ranked_results.append({
                'candidate_id': candidate['candidate_id'],
                'interview_id': candidate.get('latest_interview_id'),
                'name': candidate['name'],
                'email': candidate['email'],
                'title': candidate.get('title', ''),
                'location': candidate.get('location', ''),
                'experience_years': candidate.get('experience_years', 0),
                'role': candidate.get('latest_role', ''),
                'role_id': candidate.get('latest_role_id'),
                'recruiter': candidate.get('recruiter_name', 'Unassigned'),
                'current_stage': candidate.get('latest_pipeline_status', ''),
                'latest_interview_date': candidate.get('latest_interview_date', ''),
                'vector_rank': candidate.get('vector_rank'),
                'retrieval_distance': candidate.get('retrieval_distance'),
                'retrieval_similarity': candidate.get('retrieval_similarity'),
                'retrieval_source': candidate.get('retrieval_source', retrieval_diagnostics.get('retrieval_source', 'unknown')),
                'ai_score': ranking['ai_score'],
                'ai_band': ranking['ai_band'],
                'pre_calibration_band': ranking['pre_calibration_band'],
                'post_calibration_band': ranking['post_calibration_band'],
                'band_calibration_applied': ranking['band_calibration_applied'],
                'band_calibration_reason': ranking['band_calibration_reason'],
                'matched_skills': ranking['matched_skills'],
                'missing_skills': ranking['missing_skills'],
                'required_skills_count': ranking['required_skills_count'],
                'matched_required_skills_count': ranking['matched_required_skills_count'],
                'missing_required_skills_count': ranking['missing_required_skills_count'],
                'matched_required_skills': ranking['matched_required_skills'],
                'missing_required_skills': ranking['missing_required_skills'],
                'exact_required_skills': ranking['exact_required_skills'],
                'exact_skill_matches': ranking['exact_skill_matches'],
                'related_skill_matches': ranking['related_skill_matches'],
                'related_skill_matches_summary': ranking['related_skill_matches_summary'],
                'exact_candidate_skills': ranking['exact_candidate_skills'],
                'candidate_related_skill_evidence': ranking['candidate_related_skill_evidence'],
                'selected_embedding_skills': candidate.get('selected_embedding_skills', []),
                'omitted_embedding_skills': candidate.get('omitted_embedding_skills', []),
                'embedding_selection_source': candidate.get('embedding_selection_source', ''),
                'embedding_text_builder_version': candidate.get('embedding_text_builder_version', ''),
                'candidate_embedding_sections_used': candidate.get('candidate_embedding_sections_used', []),
                'role_supporting_skill_inference': ranking['role_supporting_skill_inference'],
                'role_adjacent_skill_inference': ranking['role_adjacent_skill_inference'],
                'normalized_candidate_skills': ranking['normalized_candidate_skills'],
                'normalized_required_skills': ranking['normalized_required_skills'],
                'normalized_preferred_skills': ranking['normalized_preferred_skills'],
                'role_embedding_text': role_profile.get('embedding_text', ''),
                'role_embedding_builder_version': role_profile.get('embedding_text_builder_version', ''),
                'candidate_embedding_text': candidate.get('embedding_text', ''),
                'candidate_embedding_text_token_count': candidate.get('embedding_text_token_count', 0),
                'role_embedding_text_token_count': role_profile.get('embedding_text_token_count', 0),
                'role_embedding_sections_used': role_profile.get('role_embedding_sections_used', []),
                'candidate_embedding_present': candidate.get('candidate_embedding_present', False),
                'role_embedding_present': candidate.get('role_embedding_present', retrieval_diagnostics.get('role_embedding_present', False)),
                'candidate_embedding_dimension': candidate.get('candidate_embedding_dimension', 0),
                'role_embedding_dimension': candidate.get('role_embedding_dimension', retrieval_diagnostics.get('role_embedding_dimension', 0)),
                'raw_vector_distance': candidate.get('raw_vector_distance'),
                'indexed_similarity_from_pgvector': candidate.get('indexed_similarity_from_pgvector', candidate.get('similarity_after_clamp')),
                'pgvector_distance_metric': candidate.get('pgvector_distance_metric', ''),
                'distance_to_similarity_formula': candidate.get('distance_to_similarity_formula', ''),
                'similarity_before_clamp': candidate.get('similarity_before_clamp'),
                'similarity_after_clamp': candidate.get('similarity_after_clamp'),
                'cosine_similarity_before_calibration': candidate.get('cosine_similarity_before_calibration', 0.0),
                'recomputed_role_aware_cosine_similarity': candidate.get('recomputed_role_aware_cosine_similarity', candidate.get('cosine_similarity_before_calibration', 0.0)),
                'semantic_score_source': candidate.get('semantic_score_source', ''),
                'semantic_score_clamp_reason': candidate.get('semantic_score_clamp_reason', ''),
                'explanations': ranking['explanations'],
                'component_scores': ranking['component_scores'],
                'semantic_similarity_raw': ranking['semantic_similarity_raw'],
                'semantic_similarity_calibrated': ranking['semantic_similarity_calibrated'],
                'semantic_floor_applied': ranking['semantic_floor_applied'],
                'semantic_floor_reason': ranking['semantic_floor_reason'],
                'semantic_similarity_score': ranking['semantic_similarity_score'],
                'must_have_score': ranking['must_have_score'],
                'preferred_score': ranking['preferred_score'],
                'experience_fit_score': ranking['experience_fit_score'],
                'title_fit_score': ranking['title_fit_score'],
                'location_score': ranking['location_score'],
                'pipeline_signal_score': ranking['pipeline_signal_score'],
                'role_profile_is_sparse': ranking['role_profile_is_sparse'],
                'role_family': ranking['role_family'],
                'role_subfamily': ranking['role_subfamily'],
                'candidate_primary_family': ranking['candidate_primary_family'],
                'candidate_secondary_families': ranking['candidate_secondary_families'],
                'title_adjacency_reason': ranking['title_adjacency_reason'],
                'graph_boost_applied': ranking['graph_boost_applied'],
                'inferred_role_family': ranking['inferred_role_family'],
                'used_title_inference': ranking['used_title_inference'],
                'ranking_confidence': ranking['ranking_confidence'],
                'confidence_adjustment_reason': ranking['confidence_adjustment_reason'],
                'confidence_upgrade_reason': ranking['confidence_upgrade_reason'],
                'confidence_downgrade_reason': ranking['confidence_downgrade_reason'],
                'pgvector_enabled': retrieval_diagnostics.get('pgvector_enabled', False),
                'pgvector_backend_available': retrieval_diagnostics.get('pgvector_backend_available', False),
                'retrieval_fallback_reason': retrieval_diagnostics.get('retrieval_fallback_reason', ''),
            })

            if getattr(settings, 'AI_TALENT_POOL_DEBUG_LOGGING', False):
                logger.info(
                    'AI Talent Pool ranking role_id=%s candidate_id=%s ai_score=%s band=%s confidence=%s sparse=%s semantic=%.2f must_have=%.2f '
                    'preferred=%.2f experience=%.2f title=%.2f location=%.2f pipeline=%.2f matched_skills=%s missing_skills=%s inferred_family=%s',
                    role.id,
                    candidate['candidate_id'],
                    ranking['ai_score'],
                    ranking['ai_band'],
                    ranking['ranking_confidence'],
                    ranking['role_profile_is_sparse'],
                    ranking['semantic_similarity_score'],
                    ranking['must_have_score'],
                    ranking['preferred_score'],
                    ranking['experience_fit_score'],
                    ranking['title_fit_score'],
                    ranking['location_score'],
                    ranking['pipeline_signal_score'],
                    ','.join(ranking['matched_skills']),
                    ','.join(ranking['missing_skills']),
                    ranking['inferred_role_family'],
                )

        ranked_results.sort(key=lambda item: (-item['ai_score'], item.get('vector_rank') or 999999, item['name']))
        limited_results = ranked_results[:max(1, min(int(top_k or 20), 100))]
        retrieval_diagnostics.update({
            'reranked_candidate_count': len(candidate_profiles),
            'returned_candidate_count': len(limited_results),
            'total_request_latency_ms': int((perf_counter() - started) * 1000),
        })

        return {
            'role_summary': {
                'role_id': role_profile['role_id'],
                'title': role_profile['title'],
                'position': role_profile['position'],
                'location': role_profile['location'],
                'job_type': role_profile['job_type'],
                'experience_required': role_profile['experience_required'],
                'required_skills': role_profile['required_skills'],
                'exact_required_skills': role_profile.get('exact_required_skills', role_profile['required_skills']),
                'normalized_required_skills': role_profile.get('normalized_required_skills', role_profile['required_skills']),
                'preferred_skills': role_profile['preferred_skills'],
                'normalized_preferred_skills': role_profile.get('normalized_preferred_skills', role_profile['preferred_skills']),
                'role_supporting_skill_inference': role_profile.get('role_supporting_skill_inference', []),
                'role_adjacent_skill_inference': role_profile.get('role_adjacent_skill_inference', []),
                'company_name': role_profile['company_name'],
                'status': role_profile['status'],
                'status_label': role_profile['status_label'],
                'role_embedding_text': role_profile.get('embedding_text', ''),
                'role_embedding_text_token_count': role_profile.get('embedding_text_token_count', 0),
                'role_embedding_builder_version': role_profile.get('embedding_text_builder_version', ''),
                'role_embedding_sections_used': role_profile.get('role_embedding_sections_used', []),
                'role_profile_is_sparse': role_profile['role_profile_is_sparse'],
                'role_family': role_profile.get('role_family', ''),
                'role_subfamily': role_profile.get('role_subfamily', ''),
                'inferred_role_family': role_profile['inferred_role_family'],
                'used_title_inference': role_profile['used_title_inference'],
            },
            'retrieval_diagnostics': retrieval_diagnostics,
            'scoring_config': get_scoring_config_snapshot(),
            'results': limited_results,
        }

    def build_search(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None,
        top_k: int,
        accessible_interviews,
    ) -> dict[str, Any]:
        started = perf_counter()
        role_profile = build_query_profile(query=query, filters=filters or {})
        accessible_candidate_ids = accessible_interviews.values_list('candidate_id', flat=True).distinct()
        retrieved, retrieval_diagnostics = retrieve_indexed_shortlist(
            role_profile=role_profile,
            accessible_candidate_ids=accessible_candidate_ids,
            top_k=top_k,
            vacancy=None,
        )
        candidate_profiles = self._hydrate_indexed_candidates(retrieved, accessible_interviews)

        ranked_results: list[dict[str, Any]] = []
        for candidate in candidate_profiles:
            ranking = rerank_candidate(role_profile, candidate)
            ranked_results.append({
                'candidate_id': candidate['candidate_id'],
                'interview_id': candidate.get('latest_interview_id'),
                'name': candidate['name'],
                'email': candidate['email'],
                'title': candidate.get('title', ''),
                'location': candidate.get('location', ''),
                'experience_years': candidate.get('experience_years', 0),
                'role': candidate.get('latest_role', ''),
                'role_id': candidate.get('latest_role_id'),
                'recruiter': candidate.get('recruiter_name', 'Unassigned'),
                'current_stage': candidate.get('latest_pipeline_status', ''),
                'latest_interview_date': candidate.get('latest_interview_date', ''),
                'vector_rank': candidate.get('vector_rank'),
                'retrieval_distance': candidate.get('retrieval_distance'),
                'retrieval_similarity': candidate.get('retrieval_similarity'),
                'retrieval_source': candidate.get('retrieval_source', retrieval_diagnostics.get('retrieval_source', 'unknown')),
                **ranking,
            })
        ranked_results.sort(key=lambda item: (-item['ai_score'], item.get('vector_rank') or 999999, item['name']))
        limited_results = ranked_results[:max(1, min(int(top_k or 20), 100))]
        retrieval_diagnostics.update({
            'reranked_candidate_count': len(candidate_profiles),
            'returned_candidate_count': len(limited_results),
            'total_request_latency_ms': int((perf_counter() - started) * 1000),
        })
        return {
            'role_summary': {
                'role_id': None,
                'title': role_profile['title'],
                'position': '',
                'location': role_profile['location'],
                'job_type': '',
                'experience_required': role_profile['experience_required'],
                'required_skills': role_profile['required_skills'],
                'exact_required_skills': role_profile.get('exact_required_skills', role_profile['required_skills']),
                'normalized_required_skills': role_profile.get('normalized_required_skills', role_profile['required_skills']),
                'preferred_skills': role_profile['preferred_skills'],
                'normalized_preferred_skills': role_profile.get('normalized_preferred_skills', role_profile['preferred_skills']),
                'role_supporting_skill_inference': role_profile.get('role_supporting_skill_inference', []),
                'role_adjacent_skill_inference': role_profile.get('role_adjacent_skill_inference', []),
                'company_name': '',
                'status': 'query',
                'status_label': 'Query',
                'role_embedding_text': role_profile.get('embedding_text', build_role_search_text(role_profile)),
                'role_embedding_text_token_count': role_profile.get('embedding_text_token_count', 0),
                'role_embedding_builder_version': role_profile.get('embedding_text_builder_version', ''),
                'role_embedding_sections_used': role_profile.get('role_embedding_sections_used', []),
                'role_profile_is_sparse': role_profile['role_profile_is_sparse'],
                'role_family': role_profile.get('role_family', ''),
                'role_subfamily': role_profile.get('role_subfamily', ''),
                'inferred_role_family': role_profile['inferred_role_family'],
                'used_title_inference': role_profile['used_title_inference'],
            },
            'retrieval_diagnostics': retrieval_diagnostics,
            'scoring_config': get_scoring_config_snapshot(),
            'results': limited_results,
        }

    def _hydrate_indexed_candidates(self, retrieved: list[dict[str, Any]], accessible_interviews: QuerySet[Interview]) -> list[dict[str, Any]]:
        candidate_ids = [item['search_profile'].candidate_id for item in retrieved if item.get('search_profile')]
        if not candidate_ids:
            return []

        interview_rows = list(
            accessible_interviews
            .filter(candidate_id__in=candidate_ids)
            .select_related('candidate', 'candidate__profile', 'recruiter', 'role')
            .order_by('-date')
        )
        latest_interview_by_candidate: dict[int, Interview] = {}
        grouped_interviews: dict[int, list[Interview]] = defaultdict(list)
        for interview in interview_rows:
            grouped_interviews[interview.candidate_id].append(interview)
            if interview.candidate_id not in latest_interview_by_candidate:
                latest_interview_by_candidate[interview.candidate_id] = interview

        search_profiles_by_candidate: dict[int, CandidateSearchProfile] = {
            item['search_profile'].candidate_id: item['search_profile']
            for item in retrieved if item.get('search_profile')
        }
        retrieval_meta_by_candidate: dict[int, dict[str, Any]] = {
            item['search_profile'].candidate_id: item
            for item in retrieved if item.get('search_profile')
        }

        candidate_profiles: list[dict[str, Any]] = []
        for candidate_id in candidate_ids:
            search_profile = search_profiles_by_candidate.get(candidate_id)
            latest_interview = latest_interview_by_candidate.get(candidate_id)
            candidate = (latest_interview.candidate if latest_interview else None) or (search_profile.candidate if search_profile else None)
            if not candidate:
                continue

            if not search_profile:
                logger.info('Skipping candidate %s for AI talent pool because no search profile is available.', candidate_id)
                continue

            metadata = search_profile.search_metadata or {}
            interviews = grouped_interviews.get(candidate_id, [])
            retrieval_meta = retrieval_meta_by_candidate.get(candidate_id, {})
            candidate_profile = {
                'candidate_id': candidate.id,
                'user_id': candidate.id,
                'name': f'{candidate.first_name} {candidate.last_name}'.strip().title() or candidate.username,
                'email': candidate.email,
                'title': metadata.get('title') or search_profile.normalized_title or title_display(search_profile.normalized_title),
                'headline': metadata.get('headline', ''),
                'summary': metadata.get('summary', ''),
                'experience_years': float(search_profile.experience_years or 0),
                'skills': list(metadata.get('exact_candidate_skills', []) or search_profile.normalized_skills or []),
                'exact_candidate_skills': list(metadata.get('exact_candidate_skills', []) or search_profile.normalized_skills or []),
                'normalized_candidate_skills': list(search_profile.normalized_skills or []),
                'candidate_related_skill_evidence': build_related_skill_evidence(list(search_profile.normalized_skills or [])),
                'candidate_primary_family': search_profile.role_family,
                'candidate_secondary_families': list(metadata.get('candidate_secondary_families', []) or search_profile.domain_exposure or []),
                'location': metadata.get('location') or search_profile.location_normalized,
                'current_company': metadata.get('current_company', ''),
                'embedding_text': retrieval_meta.get('candidate_embedding_text') or (retrieval_meta.get('search_profile').search_text if retrieval_meta.get('search_profile') else search_profile.search_text),
                'embedding_text_token_count': int(retrieval_meta.get('candidate_embedding_text_token_count') or metadata.get('embedding_text_token_count') or search_profile.search_metadata.get('embedding_text_token_count') or 0),
                'selected_embedding_skills': retrieval_meta.get('selected_embedding_skills', metadata.get('selected_embedding_skills', [])),
                'omitted_embedding_skills': retrieval_meta.get('omitted_embedding_skills', metadata.get('omitted_embedding_skills', [])),
                'embedding_selection_source': retrieval_meta.get('embedding_selection_source', metadata.get('embedding_selection_source', '')),
                'embedding_text_builder_version': retrieval_meta.get('embedding_text_builder_version', metadata.get('embedding_text_builder_version', '')),
                'candidate_embedding_sections_used': retrieval_meta.get('candidate_embedding_sections_used', metadata.get('candidate_embedding_sections_used', [])),
                'candidate_embedding_present': retrieval_meta.get('candidate_embedding_present', bool(_vector_values(search_profile.embedding_json) or _vector_values(search_profile.embedding))),
                'role_embedding_present': retrieval_meta.get('role_embedding_present', False),
                'candidate_embedding_dimension': retrieval_meta.get('candidate_embedding_dimension', len(_vector_values(search_profile.embedding_json) or _vector_values(search_profile.embedding))),
                'role_embedding_dimension': retrieval_meta.get('role_embedding_dimension', 0),
                'raw_vector_distance': retrieval_meta.get('raw_vector_distance'),
                'indexed_similarity_from_pgvector': retrieval_meta.get('indexed_similarity_from_pgvector', retrieval_meta.get('similarity_after_clamp')),
                'pgvector_distance_metric': retrieval_meta.get('pgvector_distance_metric', ''),
                'distance_to_similarity_formula': retrieval_meta.get('distance_to_similarity_formula', ''),
                'similarity_before_clamp': retrieval_meta.get('similarity_before_clamp'),
                'similarity_after_clamp': retrieval_meta.get('similarity_after_clamp'),
                'cosine_similarity_before_calibration': retrieval_meta.get('cosine_similarity_before_calibration', retrieval_meta.get('retrieval_similarity', 0.0)),
                'recomputed_role_aware_cosine_similarity': retrieval_meta.get('recomputed_role_aware_cosine_similarity', retrieval_meta.get('cosine_similarity_before_calibration', retrieval_meta.get('retrieval_similarity', 0.0))),
                'semantic_score_source': retrieval_meta.get('semantic_score_source', ''),
                'semantic_score_clamp_reason': retrieval_meta.get('semantic_score_clamp_reason', ''),
                'resume_id': metadata.get('resume_id'),
                'resume_status': metadata.get('resume_status', ''),
                'latest_role_id': latest_interview.role_id if latest_interview else metadata.get('latest_role_id'),
                'latest_role': latest_interview.role.role if latest_interview and latest_interview.role else search_profile.latest_role_summary,
                'latest_interview_id': latest_interview.id if latest_interview else None,
                'latest_interview_date': latest_interview.date.isoformat() if latest_interview and latest_interview.date else '',
                'latest_pipeline_status': latest_interview.status if latest_interview else metadata.get('latest_pipeline_status', ''),
                'recruiter_name': (
                    f'{latest_interview.recruiter.first_name} {latest_interview.recruiter.last_name}'.strip().title()
                    if latest_interview and latest_interview.recruiter else 'Unassigned'
                ),
                'interview_stats': self._compute_interview_stats(interviews),
                'semantic_similarity_raw': retrieval_meta.get('semantic_similarity_raw', retrieval_meta.get('retrieval_similarity', 0.0)),
                'semantic_similarity': retrieval_meta.get('semantic_similarity', retrieval_meta.get('retrieval_similarity', 0.0)),
                'vector_rank': retrieval_meta.get('vector_rank'),
                'retrieval_distance': retrieval_meta.get('retrieval_distance'),
                'retrieval_similarity': retrieval_meta.get('retrieval_similarity'),
                'retrieval_source': retrieval_meta.get('retrieval_source'),
            }
            candidate_profiles.append(candidate_profile)

        return candidate_profiles

    def _compute_interview_stats(self, interviews: list[Interview]) -> dict[str, Any]:
        score_values: list[float] = []
        same_role_scores: dict[int, list[float]] = defaultdict(list)

        for interview in interviews:
            if interview.score is None:
                continue
            try:
                numeric = float(interview.score)
            except (TypeError, ValueError):
                continue
            if numeric <= 0:
                continue
            normalized = numeric * 10 if numeric <= 10 else numeric
            score_values.append(normalized)
            if interview.role_id:
                same_role_scores[interview.role_id].append(normalized)

        latest_role_id = interviews[0].role_id if interviews else None
        same_role_average_score = None
        if latest_role_id and same_role_scores.get(latest_role_id):
            values = same_role_scores[latest_role_id]
            same_role_average_score = sum(values) / len(values)

        return {
            'average_score': (sum(score_values) / len(score_values)) if score_values else None,
            'same_role_average_score': same_role_average_score,
        }
