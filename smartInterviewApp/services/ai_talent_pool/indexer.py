from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from time import perf_counter
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Prefetch
from django.utils import timezone

from smartInterviewApp.models import CandidateResume, CandidateSearchProfile, Interview
from .candidate_profile_builder import build_candidate_profile
from .embeddings import EmbeddingProviderUnavailable, get_embedding
from .search_index import (
    build_candidate_search_text,
    build_candidate_source_signature,
    normalize_location,
    profile_quality_score,
)


logger = logging.getLogger(__name__)


def _inactive_reason_for_resume(resume: CandidateResume | None, *, searchable_profile_built: bool, missing_fields_summary: list[str]) -> str:
    if not resume:
        return 'no_active_resume'
    if resume.status != CandidateResume.ParseStatus.COMPLETED:
        return 'no_parsed_resume'
    if not searchable_profile_built:
        if missing_fields_summary:
            return 'missing_required_profile_fields'
        return 'insufficient_searchable_signal'
    return ''


def _search_profile_health(candidate_profile: dict[str, Any]) -> tuple[bool, list[str]]:
    exact_skills = list(candidate_profile.get('exact_candidate_skills') or [])
    experience_items = list(candidate_profile.get('experience_items') or [])
    checks = {
        'title': bool(str(candidate_profile.get('title') or '').strip()),
        'summary': bool(str(candidate_profile.get('summary') or '').strip()),
        'skills': bool(exact_skills),
        'experience': bool(experience_items),
        'location': bool(str(candidate_profile.get('location') or '').strip()),
    }
    searchable = checks['title'] or checks['skills'] or checks['summary'] or checks['experience']
    missing = [name for name, present in checks.items() if not present]
    return searchable, missing


class CandidateSearchIndexer:
    def rebuild_candidate(self, *, candidate: User, force: bool = False) -> CandidateSearchProfile | None:
        latest_interview = (
            Interview.objects
            .select_related('role', 'recruiter')
            .filter(candidate=candidate)
            .order_by('-date', '-id')
            .first()
        )
        resume = (
            CandidateResume.objects
            .filter(candidate=candidate, is_active=True)
            .prefetch_related(Prefetch('sections'))
            .order_by('-processed_at', '-updated_at', '-id')
            .first()
        )
        if not resume:
            CandidateSearchProfile.objects.filter(candidate=candidate).delete()
            return None

        candidate_profile = build_candidate_profile(candidate=candidate, resume=resume, latest_interview=latest_interview)
        searchable_profile_built, missing_fields_summary = _search_profile_health(candidate_profile)
        source_signature = build_candidate_source_signature(candidate_profile)
        search_profile, created = CandidateSearchProfile.objects.get_or_create(candidate=candidate)
        if (
            not force
            and not created
            and search_profile.source_signature == source_signature
            and search_profile.is_active
            and search_profile.searchable_profile_built
        ):
            return search_profile

        if not searchable_profile_built:
            search_profile.active_resume = resume
            search_profile.normalized_title = str(candidate_profile.get('title', '')).strip()
            search_profile.normalized_skills = list(candidate_profile.get('exact_candidate_skills') or [])
            search_profile.role_family = str(candidate_profile.get('candidate_primary_family', '')).strip()
            search_profile.role_subfamily = ''
            search_profile.experience_years = Decimal(str(candidate_profile.get('experience_years') or 0)) if candidate_profile.get('experience_years') is not None else None
            search_profile.location_normalized = normalize_location(candidate_profile.get('location', ''))
            search_profile.latest_role_summary = str(candidate_profile.get('latest_role', '') or candidate_profile.get('title', '')).strip()
            search_profile.recent_companies = self._recent_companies(candidate_profile)
            search_profile.domain_exposure = self._domain_exposure(candidate_profile)
            search_profile.availability = ''
            search_profile.profile_quality_score = Decimal(str(profile_quality_score(candidate_profile)))
            search_profile.search_text = ''
            search_profile.embedding = None
            search_profile.embedding_json = []
            search_profile.search_metadata = {
                'headline': candidate_profile.get('headline', ''),
                'summary': candidate_profile.get('summary', ''),
                'title': candidate_profile.get('title', ''),
                'location': candidate_profile.get('location', ''),
                'current_company': candidate_profile.get('current_company', ''),
                'candidate_secondary_families': candidate_profile.get('candidate_secondary_families', []),
                'exact_candidate_skills': candidate_profile.get('exact_candidate_skills', []),
                'resume_id': candidate_profile.get('resume_id'),
                'resume_status': candidate_profile.get('resume_status', ''),
                'latest_role_id': candidate_profile.get('latest_role_id'),
                'latest_pipeline_status': candidate_profile.get('latest_pipeline_status', ''),
                'embedding_text_token_count': 0,
                'selected_embedding_skills': candidate_profile.get('exact_candidate_skills', []),
                'omitted_embedding_skills': [],
                'embedding_selection_source': 'inactive_unsearchable_profile',
                'embedding_text_builder_version': candidate_profile.get('embedding_text_builder_version', ''),
                'candidate_embedding_sections_used': candidate_profile.get('candidate_embedding_sections_used', []),
            }
            search_profile.parser_signature = f"{resume.parser_provider}:{resume.parser_version}:{resume.status}"
            search_profile.source_signature = source_signature
            search_profile.inactive_reason = _inactive_reason_for_resume(
                resume,
                searchable_profile_built=searchable_profile_built,
                missing_fields_summary=missing_fields_summary,
            )
            search_profile.active_resume_found = True
            search_profile.searchable_profile_built = False
            search_profile.missing_fields_summary = missing_fields_summary
            search_profile.indexed_at = timezone.now()
            search_profile.is_active = False
            search_profile.save()
            return search_profile

        started = perf_counter()
        search_text = build_candidate_search_text(candidate_profile)
        try:
            embedding = get_embedding(search_text)
        except EmbeddingProviderUnavailable:
            if getattr(settings, 'AI_TALENT_POOL_REQUIRE_REAL_EMBEDDINGS', True):
                raise
            embedding = []

        recent_companies = self._recent_companies(candidate_profile)
        domain_exposure = self._domain_exposure(candidate_profile)

        search_profile.active_resume = resume
        search_profile.normalized_title = str(candidate_profile.get('title', '')).strip()
        search_profile.normalized_skills = list(candidate_profile.get('exact_candidate_skills') or [])
        search_profile.role_family = str(candidate_profile.get('candidate_primary_family', '')).strip()
        search_profile.role_subfamily = ''
        search_profile.experience_years = Decimal(str(candidate_profile.get('experience_years') or 0))
        search_profile.location_normalized = normalize_location(candidate_profile.get('location', ''))
        search_profile.latest_role_summary = str(candidate_profile.get('latest_role', '') or candidate_profile.get('title', '')).strip()
        search_profile.recent_companies = recent_companies
        search_profile.domain_exposure = domain_exposure
        search_profile.availability = ''
        search_profile.profile_quality_score = Decimal(str(profile_quality_score(candidate_profile)))
        search_profile.search_text = search_text
        search_profile.embedding = embedding or None
        search_profile.embedding_json = embedding or []
        search_profile.search_metadata = {
            'headline': candidate_profile.get('headline', ''),
            'summary': candidate_profile.get('summary', ''),
            'title': candidate_profile.get('title', ''),
            'location': candidate_profile.get('location', ''),
            'current_company': candidate_profile.get('current_company', ''),
            'candidate_secondary_families': candidate_profile.get('candidate_secondary_families', []),
            'exact_candidate_skills': candidate_profile.get('exact_candidate_skills', []),
            'resume_id': candidate_profile.get('resume_id'),
            'resume_status': candidate_profile.get('resume_status', ''),
            'latest_role_id': candidate_profile.get('latest_role_id'),
            'latest_pipeline_status': candidate_profile.get('latest_pipeline_status', ''),
            'embedding_text_token_count': candidate_profile.get('embedding_text_token_count', 0),
            'selected_embedding_skills': candidate_profile.get('exact_candidate_skills', []),
            'omitted_embedding_skills': [],
            'embedding_selection_source': 'generic_candidate_search_profile',
            'embedding_text_builder_version': candidate_profile.get('embedding_text_builder_version', ''),
            'candidate_embedding_sections_used': candidate_profile.get('candidate_embedding_sections_used', []),
        }
        search_profile.parser_signature = f"{resume.parser_provider}:{resume.parser_version}:{resume.status}"
        search_profile.source_signature = source_signature
        search_profile.inactive_reason = ''
        search_profile.active_resume_found = True
        search_profile.searchable_profile_built = True
        search_profile.missing_fields_summary = missing_fields_summary
        search_profile.indexed_at = timezone.now()
        search_profile.is_active = True
        search_profile.save()

        logger.info(
            'Candidate search profile indexed candidate_id=%s resume_id=%s latency_ms=%s',
            candidate.id,
            resume.id,
            int((perf_counter() - started) * 1000),
        )
        return search_profile

    def rebuild_all(self, *, candidate_ids: list[int] | None = None, stale_only: bool = False) -> dict[str, int]:
        qs = User.objects.filter(profile__role='candidate').select_related('profile')
        if candidate_ids:
            qs = qs.filter(id__in=candidate_ids)

        results = {'processed': 0, 'updated': 0, 'skipped': 0}
        for candidate in qs.iterator():
            results['processed'] += 1
            try:
                before_signature = ''
                existing = getattr(candidate, 'search_profile', None)
                if existing:
                    before_signature = existing.source_signature
                profile = self.rebuild_candidate(candidate=candidate, force=not stale_only)
                if profile and profile.source_signature == before_signature and not stale_only:
                    results['skipped'] += 1
                else:
                    results['updated'] += 1
            except Exception:
                logger.exception('Candidate search profile reindex failed candidate_id=%s', candidate.id)
                raise
        return results

    def _recent_companies(self, candidate_profile: dict[str, Any]) -> list[str]:
        companies: list[str] = []
        for entry in (candidate_profile.get('experience_items') or [])[:5]:
            if not isinstance(entry, dict):
                continue
            company = str(entry.get('company') or '').strip()
            if company and company not in companies:
                companies.append(company)
        current_company = str(candidate_profile.get('current_company') or '').strip()
        if current_company and current_company not in companies:
            companies.insert(0, current_company)
        return companies[:5]

    def _domain_exposure(self, candidate_profile: dict[str, Any]) -> list[str]:
        families = [str(candidate_profile.get('candidate_primary_family') or '').strip()]
        families.extend(str(item).strip() for item in (candidate_profile.get('candidate_secondary_families') or []))
        output: list[str] = []
        for family in families:
            if family and family not in output:
                output.append(family)
        return output[:5]


def bulk_rebuild_candidate_search_index(*, candidate_ids: list[int] | None = None, stale_only: bool = False) -> dict[str, int]:
    return CandidateSearchIndexer().rebuild_all(candidate_ids=candidate_ids, stale_only=stale_only)
