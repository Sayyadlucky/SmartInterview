from __future__ import annotations

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartInterview.settings')
django.setup()

from smartInterviewApp.services.ai_talent_pool.role_profile_builder import build_role_profile
from smartInterviewApp.services.ai_talent_pool.reranker import rerank_candidate


def _base_role(**overrides):
    role = {
        'role_id': 12,
        'title': 'Python Fullstack',
        'required_skills': ['Python', 'JavaScript'],
        'normalized_required_skills': ['Python', 'JavaScript'],
        'preferred_skills': ['AWS'],
        'normalized_preferred_skills': ['AWS'],
        'experience_range': {'min_years': 3, 'max_years': 6},
        'location': 'Bangalore',
        'remote_friendly': False,
        'role_profile_is_sparse': False,
        'role_family': 'engineering',
        'role_subfamily': 'fullstack',
        'inferred_role_family': 'fullstack',
        'used_title_inference': False,
    }
    role.update(overrides)
    return role


def _base_candidate(**overrides):
    candidate = {
        'title': 'Software Engineer',
        'headline': 'Software Engineer',
        'skills': ['Python', 'JavaScript'],
        'normalized_candidate_skills': ['Python', 'JavaScript'],
        'experience_years': 4,
        'location': 'Bangalore',
        'semantic_similarity': 0.8,
        'interview_stats': {'average_score': 78, 'same_role_average_score': 80},
        'latest_role_id': 12,
        'candidate_primary_family': 'engineering',
        'candidate_secondary_families': ['engineering/software'],
    }
    candidate.update(overrides)
    return candidate


class _VacancyStub:
    def __init__(self, **kwargs):
        self.id = kwargs.get('id', 1)
        self.role = kwargs.get('role', '')
        self.position = kwargs.get('position', '')
        self.description = kwargs.get('description', '')
        self.experience_required = kwargs.get('experience_required', '')
        self.location = kwargs.get('location', '')
        self.job_type = kwargs.get('job_type', '')
        self.status = kwargs.get('status', 'active')
        self.company = kwargs.get('company')
        self.admin = kwargs.get('admin')

    def get_job_type_display(self):
        return self.job_type or ''


def test_python_role_matched_by_python_3_normalization() -> None:
    result = rerank_candidate(
        _base_role(required_skills=['Python'], normalized_required_skills=['Python'], preferred_skills=[], normalized_preferred_skills=[]),
        _base_candidate(skills=['Python 3.x'], normalized_candidate_skills=['Python']),
    )

    assert result['matched_required_skills'] == ['Python']
    assert result['must_have_score'] == 100.0
    assert result['exact_skill_matches'] == ['Python']


def test_python_role_matched_by_django_flask_fastapi_related_evidence() -> None:
    result = rerank_candidate(
        _base_role(required_skills=['Python'], normalized_required_skills=['Python'], preferred_skills=[], normalized_preferred_skills=[]),
        _base_candidate(
            title='Backend Engineer',
            skills=['Django', 'Flask', 'FastAPI'],
            normalized_candidate_skills=['Python', 'Django', 'Flask', 'FastAPI'],
        ),
    )

    assert result['matched_required_skills'] == ['Python']
    assert result['must_have_score'] >= 90.0
    assert result['related_skill_matches'] or result['exact_skill_matches']
    assert result['exact_candidate_skills'] == ['Python', 'Django', 'Flask', 'FastAPI']
    assert 'Pandas' not in result['normalized_required_skills']


def test_salesforce_role_matched_by_apex_and_lightning() -> None:
    result = rerank_candidate(
        _base_role(
            title='Salesforce Developer',
            required_skills=['Salesforce'],
            normalized_required_skills=['Salesforce'],
            preferred_skills=[],
            normalized_preferred_skills=[],
            role_family='engineering',
            role_subfamily='crm_platform',
            inferred_role_family='crm_platform',
        ),
        _base_candidate(
            title='Salesforce Engineer',
            skills=['Apex', 'Lightning'],
            normalized_candidate_skills=['Apex', 'Lightning', 'Salesforce'],
            candidate_primary_family='engineering',
        ),
    )

    assert result['matched_required_skills'] == ['Salesforce']
    assert result['must_have_score'] >= 85.0


def test_sales_role_matched_by_crm_prospecting_and_cold_calling() -> None:
    result = rerank_candidate(
        _base_role(
            title='Sales Executive',
            required_skills=['Lead Generation', 'CRM'],
            normalized_required_skills=['Lead Generation', 'CRM'],
            preferred_skills=['Pipeline Management'],
            normalized_preferred_skills=['Pipeline Management'],
            role_family='sales_bd',
            role_subfamily='business_development',
            inferred_role_family='business_development',
        ),
        _base_candidate(
            title='Business Development Executive',
            skills=['Prospecting', 'Cold Calling', 'Salesforce'],
            normalized_candidate_skills=['Prospecting', 'Cold Calling', 'Salesforce', 'CRM'],
            candidate_primary_family='sales_bd',
        ),
    )

    assert result['must_have_score'] >= 80.0
    assert result['title_fit_score'] >= 80.0


def test_recruiter_role_matched_by_talent_acquisition_and_sourcing() -> None:
    result = rerank_candidate(
        _base_role(
            title='Recruiter',
            required_skills=['Recruitment', 'Sourcing'],
            normalized_required_skills=['Recruitment', 'Sourcing'],
            preferred_skills=['LinkedIn Recruiter'],
            normalized_preferred_skills=['LinkedIn Recruiter'],
            role_family='recruiting_hr',
            role_subfamily='talent_acquisition',
            inferred_role_family='talent_acquisition',
        ),
        _base_candidate(
            title='HR Recruiter',
            skills=['Talent Acquisition', 'Sourcing', 'Boolean Search'],
            normalized_candidate_skills=['Talent Acquisition', 'Recruitment', 'Sourcing', 'Boolean Search'],
            candidate_primary_family='recruiting_hr',
        ),
    )

    assert result['must_have_score'] >= 85.0
    assert 'Adjacent title match' in ' '.join(result['explanations']) or result['title_fit_score'] >= 85.0


def test_customer_success_role_matched_by_renewals_and_onboarding() -> None:
    result = rerank_candidate(
        _base_role(
            title='Customer Success Manager',
            required_skills=['Customer Success', 'Renewals'],
            normalized_required_skills=['Customer Success', 'Renewals'],
            preferred_skills=['Onboarding'],
            normalized_preferred_skills=['Onboarding'],
            role_family='customer_success',
            role_subfamily='success',
            inferred_role_family='success',
        ),
        _base_candidate(
            title='Customer Success Executive',
            skills=['Renewals', 'Onboarding', 'Retention'],
            normalized_candidate_skills=['Renewals', 'Onboarding', 'Retention', 'Customer Success'],
            candidate_primary_family='customer_success',
        ),
    )

    assert result['must_have_score'] >= 80.0
    assert result['ai_band'] in {'good', 'strong'}


def test_product_manager_matched_by_roadmap_prd_and_agile() -> None:
    result = rerank_candidate(
        _base_role(
            title='Product Manager',
            required_skills=['Product Management', 'Roadmapping', 'PRD'],
            normalized_required_skills=['Product Management', 'Roadmapping', 'PRD'],
            preferred_skills=['Agile'],
            normalized_preferred_skills=['Agile'],
            role_family='product_project',
            role_subfamily='product_management',
            inferred_role_family='product_management',
        ),
        _base_candidate(
            title='Associate Product Manager',
            skills=['Roadmapping', 'PRD', 'Agile'],
            normalized_candidate_skills=['Product Management', 'Roadmapping', 'PRD', 'Agile'],
            candidate_primary_family='product_project',
        ),
    )

    assert result['must_have_score'] >= 85.0
    assert result['title_fit_score'] >= 80.0


def test_finance_role_matched_by_accounting_gst_and_reconciliation() -> None:
    result = rerank_candidate(
        _base_role(
            title='Accountant',
            required_skills=['Accounting', 'GST', 'Reconciliation'],
            normalized_required_skills=['Accounting', 'GST', 'Reconciliation'],
            preferred_skills=['Excel'],
            normalized_preferred_skills=['Excel'],
            role_family='finance_accounting',
            role_subfamily='accounting',
            inferred_role_family='accounting',
        ),
        _base_candidate(
            title='Accounts Executive',
            skills=['Accounting', 'GST', 'Reconciliation', 'Excel'],
            normalized_candidate_skills=['Accounting', 'GST', 'Reconciliation', 'Excel'],
            candidate_primary_family='finance_accounting',
        ),
    )

    assert result['must_have_score'] == 100.0
    assert result['preferred_score'] == 100.0


def test_generic_software_engineer_does_not_overmatch_salesforce_developer() -> None:
    role = build_role_profile(_VacancyStub(role='Salesfore Developer', description='', position='1', location='Remote'))
    result = rerank_candidate(
        role,
        _base_candidate(
            title='Software Engineer',
            headline='Software Engineer',
            skills=['Python', 'Django'],
            normalized_candidate_skills=['Python', 'Django'],
            semantic_similarity=0.1,
            candidate_primary_family='engineering',
        ),
    )

    assert result['title_fit_score'] <= 35.0
    assert result['must_have_score'] == 0.0
    assert result['ai_band'] != 'strong'


def test_generic_sales_profile_does_not_overmatch_enterprise_saas_sales() -> None:
    result = rerank_candidate(
        _base_role(
            title='Enterprise Sales Executive',
            required_skills=['Enterprise Sales', 'SaaS Sales', 'Negotiation'],
            normalized_required_skills=['Enterprise Sales', 'SaaS Sales', 'Negotiation'],
            preferred_skills=['CRM'],
            normalized_preferred_skills=['CRM'],
            role_family='sales_bd',
            role_subfamily='business_development',
            inferred_role_family='business_development',
        ),
        _base_candidate(
            title='Sales Executive',
            skills=['Lead Generation', 'Cold Calling'],
            normalized_candidate_skills=['Lead Generation', 'Cold Calling'],
            candidate_primary_family='sales_bd',
            semantic_similarity=0.42,
        ),
    )

    assert result['must_have_score'] < 60.0
    assert result['ai_band'] != 'strong'


def test_adjacent_title_scoring_handles_exact_adjacent_and_generic_cases() -> None:
    exact = rerank_candidate(
        _base_role(title='Product Manager', role_family='product_project', role_subfamily='product_management'),
        _base_candidate(title='Product Manager', headline='Product Manager', candidate_primary_family='product_project'),
    )
    adjacent = rerank_candidate(
        _base_role(title='Product Manager', role_family='product_project', role_subfamily='product_management'),
        _base_candidate(title='Associate Product Manager', headline='Associate Product Manager', candidate_primary_family='product_project'),
    )
    generic = rerank_candidate(
        _base_role(title='Product Manager', role_family='product_project', role_subfamily='product_management'),
        _base_candidate(title='Manager', headline='Manager', candidate_primary_family='operations_admin'),
    )

    assert exact['title_fit_score'] == 100.0
    assert adjacent['title_fit_score'] > generic['title_fit_score']


def test_unknown_skills_do_not_crash_matcher() -> None:
    result = rerank_candidate(
        _base_role(required_skills=['Obscure Skill'], normalized_required_skills=['Obscure Skill'], preferred_skills=[], normalized_preferred_skills=[]),
        _base_candidate(skills=['Unknown Tool'], normalized_candidate_skills=['Unknown Tool']),
    )

    assert result['must_have_score'] == 0.0
    assert result['missing_required_skills'] == ['Obscure Skill']


def test_sparse_role_behaves_safely_with_graph_inference() -> None:
    role = build_role_profile(_VacancyStub(role='Salesfore Developer', description='', position='1', location='Remote'))
    result = rerank_candidate(
        role,
        _base_candidate(
            title='CRM Developer',
            skills=['Apex'],
            normalized_candidate_skills=['Apex', 'Salesforce'],
            location='Remote',
            semantic_similarity=0.2,
            candidate_primary_family='engineering',
        ),
    )

    assert result['role_profile_is_sparse'] is True
    assert result['ranking_confidence'] == 'low'
    assert result['ai_band'] != 'strong'


def test_mixed_exact_and_related_skill_evidence_scores_correctly() -> None:
    result = rerank_candidate(
        _base_role(
            title='Python Fullstack',
            required_skills=['Python', 'React', 'REST API'],
            normalized_required_skills=['Python', 'React', 'REST API'],
            preferred_skills=[],
            normalized_preferred_skills=[],
        ),
        _base_candidate(
            title='Full Stack Developer',
            skills=['Django', 'React', 'FastAPI'],
            normalized_candidate_skills=['Python', 'Django', 'React', 'FastAPI', 'REST API'],
            semantic_similarity=0.84,
        ),
    )

    assert result['must_have_score'] >= 90.0
    assert result['matched_required_skills_count'] == 3
    assert result['graph_boost_applied'] is True or bool(result['related_skill_matches'])


def test_role_debug_fields_do_not_promote_related_nodes_into_required_skills() -> None:
    role = build_role_profile(_VacancyStub(role='Python Fullstack', description='', position='1', location='Remote'))

    assert 'Python' in role['exact_required_skills']
    assert 'Pandas' not in role['exact_required_skills']
    assert 'TensorFlow' not in role['normalized_required_skills']


def test_candidate_debug_fields_keep_related_evidence_separate_from_exact_skills() -> None:
    result = rerank_candidate(
        _base_role(required_skills=['Python'], normalized_required_skills=['Python'], preferred_skills=[], normalized_preferred_skills=[]),
        _base_candidate(
            skills=['Django', 'Flask'],
            normalized_candidate_skills=['Django', 'Flask'],
            candidate_primary_family='engineering',
        ),
    )

    assert result['exact_candidate_skills'] == ['Django', 'Flask']
    assert 'Python' not in result['exact_candidate_skills']
    related_targets = {
        item['skill']
        for related_items in result['candidate_related_skill_evidence'].values()
        for item in related_items
    }
    assert 'Python' in related_targets


def test_strong_python_fullstack_match_gets_semantic_calibration_and_not_watch() -> None:
    result = rerank_candidate(
        _base_role(
            title='Python Fullstack',
            required_skills=['Python', 'Angular', 'REST API'],
            normalized_required_skills=['Python', 'Angular', 'REST API'],
            preferred_skills=['Django', 'Flask'],
            normalized_preferred_skills=['Django', 'Flask'],
            role_family='engineering',
            role_subfamily='fullstack',
            inferred_role_family='fullstack',
        ),
        _base_candidate(
            title='Python Developer',
            headline='Python Developer',
            skills=['Python', 'Django', 'Flask', 'DRF', 'Angular', 'REST API'],
            normalized_candidate_skills=['Python', 'Django', 'Flask', 'DRF', 'Angular', 'REST API'],
            exact_candidate_skills=['Python', 'Django', 'Flask', 'DRF', 'Angular', 'REST API'],
            semantic_similarity=0.10,
            semantic_similarity_raw=0.10,
            candidate_primary_family='engineering',
        ),
    )

    assert result['must_have_score'] == 100.0
    assert result['semantic_similarity_raw'] == 0.1
    assert result['semantic_similarity_calibrated'] >= 0.58
    assert result['semantic_floor_applied'] is True
    assert result['semantic_floor_reason'] != ''
    assert result['ai_band'] in {'good', 'strong'}
    assert result['ranking_confidence'] in {'medium', 'high'}


def test_role_aware_embedding_selection_prioritizes_python_fullstack_skills() -> None:
    from smartInterviewApp.services.ai_talent_pool.candidate_profile_builder import build_role_aware_candidate_embedding_payload

    role = _base_role(
        title='Python Fullstack',
        required_skills=['Python', 'Angular', 'REST API'],
        normalized_required_skills=['Python', 'Angular', 'REST API'],
        preferred_skills=['Django', 'Flask'],
        normalized_preferred_skills=['Django', 'Flask'],
        role_family='engineering',
        role_subfamily='fullstack',
    )
    candidate = _base_candidate(
        title='Python Developer',
        headline='Python Developer',
        summary='Backend and fullstack engineer working across Python, JavaScript, Angular, SQL and APIs.',
        exact_candidate_skills=['Agile', 'Angular', 'Bootstrap', 'CI/CD', 'CSS', 'Django', 'Documentation', 'DRF', 'Flask', 'Git', 'HTML', 'Issue Resolution', 'Python', 'JavaScript', 'REST API', 'SQL', 'MySQL'],
        normalized_candidate_skills=['Agile', 'Angular', 'Bootstrap', 'CI/CD', 'CSS', 'Django', 'Documentation', 'DRF', 'Flask', 'Git', 'HTML', 'Issue Resolution', 'Python', 'JavaScript', 'REST API', 'SQL', 'MySQL'],
        experience_items=[{'role': 'Python Developer', 'company': 'Acme', 'tech_stack': ['Python', 'Django', 'Flask', 'Angular', 'REST API', 'MySQL']}],
        project_items=[],
    )

    payload = build_role_aware_candidate_embedding_payload(candidate, role)

    assert 'Python' in payload['selected_embedding_skills']
    assert 'Angular' in payload['selected_embedding_skills']
    assert 'REST API' in payload['selected_embedding_skills']
    assert 'Documentation' not in payload['selected_embedding_skills'][:8]


def test_exact_required_high_confidence_adjacent_title_gets_minimum_good_band() -> None:
    result = rerank_candidate(
        _base_role(
            title='Python Fullstack',
            required_skills=['Python'],
            normalized_required_skills=['Python'],
            preferred_skills=[],
            normalized_preferred_skills=[],
            role_family='engineering',
            role_subfamily='fullstack',
        ),
        _base_candidate(
            title='Python Developer',
            headline='Python Developer',
            exact_candidate_skills=['Python', 'Django', 'Angular'],
            normalized_candidate_skills=['Python', 'Django', 'Angular'],
            semantic_similarity=0.16,
            semantic_similarity_raw=0.16,
            candidate_primary_family='engineering',
        ),
    )

    assert result['ranking_confidence'] == 'high'
    assert result['must_have_score'] == 100.0
    assert result['pre_calibration_band'] == 'watch'
    assert result['post_calibration_band'] == 'good'
    assert result['band_calibration_applied'] is True


def test_exact_required_low_confidence_can_remain_watch() -> None:
    result = rerank_candidate(
        _base_role(
            title='Python Fullstack',
            required_skills=['Python'],
            normalized_required_skills=['Python'],
            preferred_skills=[],
            normalized_preferred_skills=[],
            role_family='engineering',
            role_subfamily='fullstack',
            role_profile_is_sparse=True,
        ),
        _base_candidate(
            title='Developer',
            headline='Developer',
            exact_candidate_skills=['Python'],
            normalized_candidate_skills=['Python'],
            semantic_similarity=0.05,
            semantic_similarity_raw=0.05,
            candidate_primary_family='engineering',
        ),
    )

    assert result['ranking_confidence'] == 'low'
    assert result['ai_band'] == 'watch'
    assert result['band_calibration_applied'] is False


def test_missing_required_skills_do_not_force_band_uplift() -> None:
    result = rerank_candidate(
        _base_role(
            title='Python Fullstack',
            required_skills=['Python', 'Angular'],
            normalized_required_skills=['Python', 'Angular'],
            preferred_skills=[],
            normalized_preferred_skills=[],
            role_family='engineering',
            role_subfamily='fullstack',
        ),
        _base_candidate(
            title='Python Developer',
            headline='Python Developer',
            exact_candidate_skills=['Python'],
            normalized_candidate_skills=['Python'],
            semantic_similarity=0.2,
            semantic_similarity_raw=0.2,
            candidate_primary_family='engineering',
        ),
    )

    assert result['missing_required_skills_count'] > 0
    assert result['band_calibration_applied'] is False
