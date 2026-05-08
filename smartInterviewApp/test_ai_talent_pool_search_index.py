from __future__ import annotations

import os
from unittest.mock import patch

import django
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartInterview.settings')
django.setup()

from django.contrib.auth.models import User
from smartInterviewApp.commonViews import ai_talent_pool_search
from smartInterviewApp.models import CandidateSearchProfile
from smartInterviewApp.services.ai_talent_pool.async_indexer import queue_candidate_reindex
from smartInterviewApp.services.ai_talent_pool.candidate_profile_builder import build_role_aware_candidate_embedding_payload
from smartInterviewApp.services.cloud_tasks import CloudTasksConfigurationError
from smartInterviewApp.services.ai_talent_pool.embeddings import get_embedding
from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import RetrievalBackendUnavailable, require_retrieval_backend
from smartInterviewApp.services.ai_talent_pool.reranker import rerank_candidate
from smartInterviewApp.services.ai_talent_pool.role_profile_builder import build_query_profile
from smartInterviewApp.services.ai_talent_pool.search_index import (
    build_candidate_search_text,
    build_candidate_source_signature,
    build_role_aware_candidate_search_text,
    build_role_search_text,
)


def test_candidate_search_text_is_compact_and_high_signal() -> None:
    payload = build_candidate_search_text({
        'title': 'Python Developer',
        'headline': 'Backend Engineer',
        'summary': 'Experienced Python backend engineer building APIs and fullstack systems with Django and Angular.',
        'exact_candidate_skills': ['Python', 'Django', 'REST API', 'Angular', 'SQL'],
        'experience_items': [{'role': 'Python Developer', 'company': 'Acme'}],
        'candidate_primary_family': 'engineering',
        'location': 'Pune',
    })

    assert 'Python' in payload
    assert 'Django' in payload
    assert 'Recent Roles' in payload


def test_role_search_text_is_compact_and_role_aware() -> None:
    payload = build_role_search_text({
        'title': 'Python Fullstack',
        'role_family': 'engineering',
        'role_subfamily': 'fullstack',
        'exact_required_skills': ['Python', 'Angular', 'REST API'],
        'role_supporting_skill_inference': ['Django', 'Flask'],
        'description': 'We need a Python fullstack developer with APIs and Angular experience.',
        'location': 'Pune',
    })

    assert 'Python Fullstack' in payload
    assert 'Angular' in payload
    assert 'Django' in payload


def test_candidate_source_signature_changes_when_skills_change() -> None:
    left = build_candidate_source_signature({'candidate_id': 1, 'skills': [], 'exact_candidate_skills': ['Python'], 'summary': 'A', 'title': 'Dev'})
    right = build_candidate_source_signature({'candidate_id': 1, 'skills': [], 'exact_candidate_skills': ['Python', 'Django'], 'summary': 'A', 'title': 'Dev'})
    assert left != right


@override_settings(AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK=False, AI_TALENT_POOL_REQUIRE_PGVECTOR=True)
def test_missing_pgvector_in_required_mode_fails_clearly() -> None:
    with patch('smartInterviewApp.services.ai_talent_pool.pgvector_retrieval._pgvector_ready', return_value=False):
        try:
            require_retrieval_backend()
            assert False, 'Expected RetrievalBackendUnavailable'
        except RetrievalBackendUnavailable:
            assert True


@override_settings(AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK=True, AI_TALENT_POOL_REQUIRE_PGVECTOR=False)
def test_local_index_scan_fallback_can_be_enabled_explicitly() -> None:
    with patch('smartInterviewApp.services.ai_talent_pool.pgvector_retrieval._pgvector_ready', return_value=False):
        require_retrieval_backend()


def test_query_profile_supports_natural_language_search() -> None:
    profile = build_query_profile(
        query='python backend developer with django and fintech experience',
        filters={'location': 'Pune', 'min_experience': 2, 'max_experience': 6},
    )

    assert profile['title']
    assert profile['location'] == 'Pune'
    assert 'Python' in profile['exact_required_skills']


def test_role_aware_candidate_search_text_prioritizes_role_skills() -> None:
    payload = build_role_aware_candidate_search_text(
        {
            'title': 'Python Developer',
            'headline': 'Python Developer',
            'summary': 'APIs and Angular',
            'location': 'Pune',
            'exact_candidate_skills': ['Python', 'Django', 'Angular', 'Documentation'],
            'normalized_candidate_skills': ['Python', 'Django', 'Angular', 'Documentation'],
            'experience_items': [{'role': 'Python Developer', 'company': 'Acme', 'tech_stack': ['Python', 'Django', 'Angular']}],
            'project_items': [],
        },
        {
            'exact_required_skills': ['Python', 'Angular'],
            'normalized_required_skills': ['Python', 'Angular'],
            'normalized_preferred_skills': ['Django'],
            'role_supporting_skill_inference': ['REST API'],
        },
    )

    assert 'Python' in payload['selected_skills']
    assert 'Angular' in payload['selected_skills']


def test_role_aware_candidate_embedding_payload_uses_clean_structured_sections() -> None:
    payload = build_role_aware_candidate_embedding_payload(
        {
            'title': 'Software Engineer',
            'headline': 'Fullstack Engineer',
            'summary': 'Backend and frontend engineer with API and Angular delivery experience.',
            'location': 'Pune, Maharashtra',
            'exact_candidate_skills': ['Python', 'JavaScript', 'Django', 'DRF', 'Flask', 'Angular', 'REST API', 'Documentation'],
            'normalized_candidate_skills': ['Python', 'JavaScript', 'Django', 'DRF', 'Flask', 'Angular', 'REST API', 'Documentation'],
            'experience_items': [
                {
                    'role': 'Software Engineer',
                    'company': 'IRIS Software',
                    'tech_stack': ['Python', 'Django', 'Angular', 'MySQL'],
                    'description': 'Created API-based solutions for clients',
                },
                {
                    'role': 'Python Developer',
                    'company': 'Bajaj Finance',
                    'tech_stack': ['Python', 'Flask', 'DRF'],
                },
            ],
            'project_items': [],
        },
        {
            'exact_required_skills': ['Python', 'JavaScript'],
            'normalized_required_skills': ['Python', 'JavaScript'],
            'normalized_preferred_skills': ['Django', 'REST API'],
            'role_supporting_skill_inference': ['Flask', 'Angular'],
        },
    )

    assert payload['embedding_text_builder_version'] == 'v3_structured_sections'
    assert 'Core Skills:' in payload['embedding_text']
    assert 'Recent Roles:' in payload['embedding_text']
    assert 'Recent Stack:' in payload['embedding_text']
    assert 'Software Engineer at IRIS Software' in payload['embedding_text']
    assert 'Created API-based solutions' not in payload['embedding_text']


def test_confidence_reason_fields_do_not_mark_strong_alignment_as_downgrade() -> None:
    ranking = rerank_candidate(
        {
            'required_skills': ['Python'],
            'exact_required_skills': ['Python'],
            'normalized_required_skills': ['Python'],
            'preferred_skills': ['Django'],
            'normalized_preferred_skills': ['Django'],
            'role_profile_is_sparse': False,
            'used_title_inference': False,
            'role_family': 'engineering',
            'role_subfamily': 'fullstack',
            'title': 'Python Fullstack',
            'location': 'Pune',
        },
        {
            'exact_candidate_skills': ['Python', 'Django', 'JavaScript'],
            'normalized_candidate_skills': ['Python', 'Django', 'JavaScript'],
            'skills': ['Python', 'Django', 'JavaScript'],
            'semantic_similarity_raw': 0.82,
            'semantic_similarity': 0.82,
            'title': 'Software Engineer',
            'headline': 'Fullstack Engineer',
            'candidate_primary_family': 'engineering',
            'candidate_secondary_families': [],
            'location': 'Pune',
            'experience_years': 6,
            'interview_stats': {},
        },
    )

    assert ranking['ranking_confidence'] == 'high'
    assert ranking['confidence_adjustment_reason'] == 'strong_semantic_alignment'
    assert ranking['confidence_upgrade_reason'] == ''
    assert ranking['confidence_downgrade_reason'] == ''


def test_search_endpoint_preserves_contract_shape() -> None:
    factory = RequestFactory()
    request = factory.post('/api/ai-talent-pool/search', data='{"query":"python developer","top_k":10}', content_type='application/json')
    request.user = type('UserStub', (), {'username': 'admin'})()

    fake_response = {
        'role_summary': {'title': 'python developer'},
        'retrieval_diagnostics': {'retrieval_source': 'pgvector'},
        'scoring_config': {},
        'results': [],
    }

    with patch('smartInterviewApp.commonViews.get_object_or_404', return_value=type('U', (), {'id': 1, 'username': 'admin'})()), \
         patch('smartInterviewApp.commonViews.get_user_role', return_value='admin'), \
         patch('smartInterviewApp.commonViews.get_admin_for_user', return_value=object()), \
         patch('smartInterviewApp.commonViews.get_accessible_interviews') as accessible_mock, \
         patch('smartInterviewApp.commonViews.AiTalentPoolService') as service_cls:
        accessible_mock.return_value = []
        service_cls.return_value.build_search.return_value = fake_response
        response = ai_talent_pool_search(request)

    assert response.status_code == 200


class CandidatePrefilterTests(TestCase):
    def _create_profile(
        self,
        *,
        user_id: int,
        title: str,
        role_family: str,
        role_subfamily: str,
        experience_years: float,
        location_normalized: str,
        normalized_skills: list[str],
    ) -> CandidateSearchProfile:
        user = User.objects.create(username=f'candidate_{user_id}')
        return CandidateSearchProfile.objects.create(
            candidate=user,
            normalized_title=title,
            normalized_skills=normalized_skills,
            role_family=role_family,
            role_subfamily=role_subfamily,
            experience_years=experience_years,
            location_normalized=location_normalized,
            search_text='candidate search text',
            embedding_json=[0.1, 0.2, 0.3],
            is_active=True,
            active_resume_found=True,
            searchable_profile_built=True,
        )

    @override_settings(AI_TALENT_POOL_ENABLE_STRICT_SUBFAMILY_PREFILTER=False)
    def test_blank_candidate_subfamily_does_not_exclude_relevant_engineering_candidate(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _apply_prefilters

        profile = self._create_profile(
            user_id=1,
            title='Software Engineer',
            role_family='engineering',
            role_subfamily='',
            experience_years=6.0,
            location_normalized='pune maharashtra 411041',
            normalized_skills=['Python', 'Django', 'REST API', 'Angular'],
        )
        qs, diagnostics = _apply_prefilters(
            {
                'role_family': 'engineering',
                'role_subfamily': 'fullstack',
                'location': 'noida, pune',
                'remote_friendly': False,
                'experience_range': {'min_years': 5.0, 'max_years': 10.0},
                'exact_required_skills': ['Python'],
            },
            [profile.candidate_id],
        )

        assert list(qs.values_list('candidate_id', flat=True)) == [profile.candidate_id]
        assert diagnostics['role_subfamily_hard_filter_applied'] is False
        assert diagnostics['final_prefilter_count'] == 1

    @override_settings(AI_TALENT_POOL_ENABLE_STRICT_SUBFAMILY_PREFILTER=False)
    def test_python_fullstack_role_still_retrieves_software_engineer_with_python_stack(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _apply_prefilters

        profile_one = self._create_profile(
            user_id=2,
            title='Software Engineer',
            role_family='engineering',
            role_subfamily='',
            experience_years=6.0,
            location_normalized='pune maharashtra',
            normalized_skills=['Python', 'Flask', 'Angular', 'MySQL'],
        )
        profile_two = self._create_profile(
            user_id=3,
            title='Backend Engineer',
            role_family='engineering',
            role_subfamily='backend',
            experience_years=7.58,
            location_normalized='pune india',
            normalized_skills=['Python', 'Django', 'DRF', 'REST API'],
        )
        qs, diagnostics = _apply_prefilters(
            {
                'role_family': 'engineering',
                'role_subfamily': 'fullstack',
                'location': 'noida, pune',
                'remote_friendly': False,
                'experience_range': {'min_years': 5.0, 'max_years': 10.0},
                'exact_required_skills': ['Python'],
            },
            [profile_one.candidate_id, profile_two.candidate_id],
        )

        assert set(qs.values_list('candidate_id', flat=True)) == {profile_one.candidate_id, profile_two.candidate_id}
        assert diagnostics['family_filtered_count'] == 2
        assert diagnostics['location_filtered_count'] == 2
        assert diagnostics['final_prefilter_count'] == 2

    @override_settings(AI_TALENT_POOL_ENABLE_STRICT_SUBFAMILY_PREFILTER=False)
    def test_subfamily_influences_debug_but_does_not_kill_retrieval(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _apply_prefilters

        matching = self._create_profile(
            user_id=4,
            title='Fullstack Developer',
            role_family='engineering',
            role_subfamily='fullstack',
            experience_years=6.5,
            location_normalized='pune',
            normalized_skills=['Python', 'Angular', 'REST API'],
        )
        blank = self._create_profile(
            user_id=5,
            title='Software Engineer',
            role_family='engineering',
            role_subfamily='',
            experience_years=6.0,
            location_normalized='pune',
            normalized_skills=['Python', 'Django'],
        )
        qs, diagnostics = _apply_prefilters(
            {
                'role_family': 'engineering',
                'role_subfamily': 'fullstack',
                'location': 'pune',
                'remote_friendly': False,
                'experience_range': {'min_years': 5.0, 'max_years': 10.0},
                'exact_required_skills': ['Python'],
            },
            [matching.candidate_id, blank.candidate_id],
        )

        assert set(qs.values_list('candidate_id', flat=True)) == {matching.candidate_id, blank.candidate_id}
        assert diagnostics['role_subfamily_hard_filter_applied'] is False
        assert diagnostics['candidates_excluded_by_subfamily'] == []

    def test_inactive_reason_is_inferred_for_profiles_without_active_resume(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _infer_inactive_reason

        profile = self._create_profile(
            user_id=6,
            title='',
            role_family='',
            role_subfamily='',
            experience_years=0,
            location_normalized='',
            normalized_skills=[],
        )
        profile.is_active = False
        profile.active_resume = None
        profile.active_resume_found = False
        profile.searchable_profile_built = False
        profile.inactive_reason = ''
        profile.save()

        assert _infer_inactive_reason(profile) == 'no_active_resume'


class LocalFallbackRetrievalTests(TestCase):
    def _create_profile(
        self,
        *,
        username: str,
        title: str,
        skills: list[str],
        family: str = 'engineering',
        location: str = 'pune',
        years: float = 6.0,
    ) -> CandidateSearchProfile:
        user = User.objects.create(username=username)
        return CandidateSearchProfile.objects.create(
            candidate=user,
            normalized_title=title,
            normalized_skills=skills,
            role_family=family,
            role_subfamily='',
            experience_years=years,
            location_normalized=location,
            search_text='',
            embedding_json=[],
            search_metadata={
                'title': title,
                'headline': title,
                'summary': 'Python fullstack engineer building APIs with Django and JavaScript.',
                'location': location,
                'exact_candidate_skills': skills,
                'embedding_text_token_count': 0,
            },
            is_active=True,
            active_resume_found=True,
            searchable_profile_built=True,
        )

    @override_settings(AI_TALENT_POOL_ENABLE_STRICT_SUBFAMILY_PREFILTER=False)
    def test_local_index_scan_similarity_is_non_zero_for_strong_python_fullstack_match(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _apply_prefilters, _local_fallback_retrieval

        profile = self._create_profile(
            username='candidate_similarity',
            title='Software Engineer',
            skills=['Python', 'JavaScript', 'Django', 'REST API', 'Angular'],
        )
        role_profile = {
            'title': 'Python Fullstack',
            'role_family': 'engineering',
            'role_subfamily': 'fullstack',
            'location': 'pune',
            'remote_friendly': False,
            'experience_range': {'min_years': 5.0, 'max_years': 10.0},
            'exact_required_skills': ['Python', 'JavaScript'],
            'normalized_required_skills': ['Python', 'JavaScript'],
            'normalized_preferred_skills': ['Django', 'REST API'],
            'role_supporting_skill_inference': ['Angular'],
        }
        qs, _diagnostics = _apply_prefilters(role_profile, [profile.candidate_id])
        ranked, meta = _local_fallback_retrieval(qs, role_profile, get_embedding('Role: Python Fullstack\nSkills: Python, JavaScript, Django, REST API, Angular'), retrieval_k=10)

        assert meta['retrieval_source'] == 'local_index_scan'
        assert len(ranked) == 1
        assert ranked[0]['retrieval_similarity'] > 0.0
        assert ranked[0]['candidate_embedding_present'] is True
        assert ranked[0]['role_embedding_present'] is True
        assert 'Python' in ranked[0]['selected_embedding_skills']
        assert ranked[0]['candidate_embedding_dimension'] > 0

    def test_backend_status_reports_local_fallback_reason_when_pgvector_unavailable(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _retrieval_backend_status

        with patch('smartInterviewApp.services.ai_talent_pool.pgvector_retrieval._using_postgres', return_value=True), \
             patch('smartInterviewApp.services.ai_talent_pool.pgvector_retrieval.HAS_PGVECTOR', False), \
             patch('smartInterviewApp.services.ai_talent_pool.pgvector_retrieval.CosineDistance', object()):
            status = _retrieval_backend_status()

        assert status['pgvector_enabled'] is False
        assert status['pgvector_backend_available'] is False
        assert status['retrieval_fallback_reason'] == 'pgvector_python_package_missing'

    def test_cached_role_embedding_reuses_repeat_request(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _get_role_embedding

        role_profile = {
            'role_id': 1,
            'title': 'Python Fullstack',
            'role_family': 'engineering',
            'role_subfamily': 'fullstack',
            'exact_required_skills': ['Python', 'JavaScript'],
            'normalized_preferred_skills': ['Django'],
            'location': 'Pune',
            'experience_required': '5-8 years',
            'embedding_text': 'Role: Python Fullstack\nExact Required Skills: Python, JavaScript\nSupporting Skills: Django',
        }

        with patch('smartInterviewApp.services.ai_talent_pool.pgvector_retrieval.get_embedding', return_value=[0.1, 0.2, 0.3]) as embed_mock:
            first_embedding, first_hit = _get_role_embedding(role_profile, vacancy=None)
            second_embedding, second_hit = _get_role_embedding(role_profile, vacancy=None)

        assert first_embedding == [0.1, 0.2, 0.3]
        assert second_embedding == [0.1, 0.2, 0.3]
        assert first_hit is False
        assert second_hit is True
        assert embed_mock.call_count == 1

    def test_pgvector_distance_debug_does_not_clamp_negative_similarity_to_zero(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _distance_similarity_debug

        before, after = _distance_similarity_debug(1.017996)
        assert round(before, 6) == round(-0.017996, 6)
        assert round(after, 6) == round(-0.017996, 6)

    def test_role_aware_embedding_debug_for_python_fullstack_overlap_is_non_zero(self) -> None:
        from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _role_aware_embedding_debug

        profile = self._create_profile(
            username='candidate_pgvector_overlap',
            title='Software Engineer',
            skills=['Python', 'JavaScript', 'Django', 'Flask', 'DRF', 'REST API'],
        )
        role_profile = {
            'title': 'Python Fullstack',
            'role_family': 'engineering',
            'role_subfamily': 'fullstack',
            'location': 'pune',
            'remote_friendly': False,
            'experience_range': {'min_years': 5.0, 'max_years': 10.0},
            'exact_required_skills': ['Python', 'JavaScript'],
            'normalized_required_skills': ['Python', 'JavaScript'],
            'normalized_preferred_skills': ['Django', 'REST API'],
            'role_supporting_skill_inference': ['Flask', 'Angular'],
        }
        role_embedding = get_embedding('Role: Python Fullstack\nFamily: engineering\nRequired Skills: Python, JavaScript\nSupporting Skills: Django, Flask, REST API')
        debug = _role_aware_embedding_debug(profile, role_profile, role_embedding)

        assert debug['embedding_selection_source'] == 'role_aware_candidate_embedding'
        assert debug['candidate_embedding_present'] is True
        assert debug['semantic_similarity_raw'] > 0.0
        assert debug['recomputed_role_aware_cosine_similarity'] > 0.0
        assert debug['semantic_score_source'] == 'recomputed_role_aware_cosine'
        assert 'Python' in debug['selected_embedding_skills']


def test_candidate_reindex_queue_does_not_block_request_when_cloud_tasks_is_unavailable() -> None:
    cache.clear()

    class FailingScheduler:
        def create_http_task(self, **kwargs):
            raise CloudTasksConfigurationError('Cloud Tasks configuration is incomplete')

        def build_task_id(self, *args, **kwargs):
            return 'candidate-search-reindex-test'

    with patch('smartInterviewApp.services.ai_talent_pool.async_indexer.process_candidate_reindex') as process_mock:
        result = queue_candidate_reindex(123, scheduler=FailingScheduler())

    process_mock.assert_not_called()
    assert result == {
        'queued': False,
        'mode': 'cloud_tasks_unavailable',
        'candidate_id': 123,
        'message': 'Cloud Tasks configuration is incomplete',
    }
