from __future__ import annotations

import io
import os
import sys
import types
from datetime import date
from unittest.mock import patch

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartInterview.settings')
django.setup()

from smartInterviewApp.resume_processing import (
    ExperienceCalculator,
    HeuristicResumeExtractor,
    ResumeTextExtractor,
    ResumeProcessingService,
    parse_resume_date,
)


def test_overlapping_full_time_roles_are_not_double_counted() -> None:
    result = ExperienceCalculator.summarize([
        {
            'title': 'Engineer I',
            'company': 'Alpha',
            'employment_type': 'full_time',
            'start_date': '2022-01',
            'end_date': '2022-06',
            'is_current': False,
        },
        {
            'title': 'Engineer II',
            'company': 'Beta',
            'employment_type': 'full_time',
            'start_date': '2022-04',
            'end_date': '2022-11',
            'is_current': False,
        },
    ])

    assert result.professional_months == 11
    assert result.internship_months == 0
    assert result.combined_months == 11


def test_internships_are_counted_separately() -> None:
    result = ExperienceCalculator.summarize([
        {
            'title': 'Software Intern',
            'company': 'Alpha',
            'employment_type': 'internship',
            'start_date': '2021-06',
            'end_date': '2021-08',
            'is_current': False,
        },
        {
            'title': 'Software Engineer',
            'company': 'Beta',
            'employment_type': 'full_time',
            'start_date': '2022-01',
            'end_date': '2022-12',
            'is_current': False,
        },
    ])

    assert result.professional_months == 12
    assert result.internship_months == 3
    assert result.combined_months == 15


def test_current_role_uses_present_correctly() -> None:
    result = ExperienceCalculator.summarize(
        [
            {
                'title': 'Backend Engineer',
                'company': 'CurrentCo',
                'employment_type': 'full_time',
                'start_date': '2024-01',
                'end_date': None,
                'is_current': True,
            }
        ],
        today=date(2024, 3, 15),
    )

    assert result.professional_months == 3


def test_invalid_date_ranges_are_ignored_safely() -> None:
    result = ExperienceCalculator.summarize([
        {
            'title': 'Broken Role',
            'company': 'Oops Inc',
            'employment_type': 'full_time',
            'start_date': '2023-05',
            'end_date': '2023-03',
            'is_current': False,
        }
    ])

    assert result.professional_months == 0
    assert result.combined_months == 0
    assert any('earlier than start date' in note for note in result.notes)


def test_year_only_dates_are_handled_consistently() -> None:
    start = parse_resume_date('2022', boundary='start')
    end = parse_resume_date('2022', boundary='end')
    result = ExperienceCalculator.summarize([
        {
            'title': 'Year Only Role',
            'company': 'Alpha',
            'employment_type': 'full_time',
            'start_date': '2022',
            'end_date': '2022',
            'is_current': False,
        }
    ])

    assert start is not None and start.iso_value() == '2022-01'
    assert end is not None and end.iso_value() == '2022-12'
    assert result.professional_months == 12


def test_current_title_and_company_choose_the_right_role() -> None:
    role = ExperienceCalculator.select_current_role([
        {
            'title': 'Older Role',
            'company': 'LegacyCo',
            'employment_type': 'full_time',
            'start_date': '2021-01',
            'end_date': '2022-12',
            'is_current': False,
        },
        {
            'title': 'Lead Engineer',
            'company': 'NewCo',
            'employment_type': 'full_time',
            'start_date': '2023-01',
            'end_date': None,
            'is_current': True,
        },
    ])

    assert role is not None
    assert role['title'] == 'Lead Engineer'
    assert role['company'] == 'NewCo'


def test_claimed_experience_text_does_not_override_computed_experience() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_payload(
        {
            'headline': 'Backend Developer',
            'summary': 'Python engineer',
            'candidate_type': 'experienced',
            'contact': {'name': 'Test', 'email': '', 'phone': '', 'location': '', 'links': []},
            'technical_expertise': {'languages': ['Python']},
            'skills': ['Python'],
            'experience': [
                {
                    'title': 'Engineer',
                    'company': 'Alpha',
                    'employment_type': 'full_time',
                    'start_date': '2024-01',
                    'end_date': '2024-03',
                    'is_current': False,
                    'duration_text': 'Jan 2024 - Mar 2024',
                    'tech_stack': [],
                    'bullets': [],
                    'notes': [],
                }
            ],
            'projects': [],
            'education': [],
            'certifications': [],
            'achievements': [],
            'languages': [],
            'claimed_experience_text': '8+ years of experience',
            'sections': [],
        },
        raw_text='Candidate claims 8+ years of experience.',
    )

    assert normalized['claimed_experience_text'] == '8+ years of experience'
    assert normalized['total_professional_experience_months'] == 3
    assert normalized['total_internship_experience_months'] == 0
    assert normalized['total_combined_experience_months'] == 3


def test_bad_source_skills_section_does_not_override_canonical_skills() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_payload(
        {
            'headline': 'Backend Developer',
            'summary': 'Python engineer',
            'objective': '',
            'candidate_type': 'experienced',
            'contact': {'name': 'Test', 'email': '', 'phone': '', 'location': '', 'links': []},
            'technical_expertise': {'languages': ['Python'], 'frameworks': ['Django']},
            'skills': ['Python', 'Django', 'Worked on client responsibilities for the company objective'],
            'experience': [],
            'projects': [],
            'education': [],
            'certifications': [],
            'achievements': [],
            'languages': [],
            'claimed_experience_text': None,
            'sections': [
                {
                    'section_key': 'skills',
                    'title': 'Skills',
                    'section_type': 'skills',
                    'raw_text': 'Worked on client responsibilities to take advantage of the company.',
                    'content': {
                        'text': 'Worked on client responsibilities to take advantage of the company.',
                        'items': [
                            'Worked on client responsibilities to take advantage of the company.',
                            'Professional summary seeking opportunity.',
                        ],
                    },
                    'display_order': 0,
                }
            ],
        },
        raw_text='Python Django REST APIs',
    )

    assert normalized['skills'] == ['Python', 'Django']
    skills_section = next(section for section in normalized['sections'] if section['section_key'] == 'skills')
    assert skills_section['content']['items'] == ['Python', 'Django']


def test_canonical_experience_section_replaces_malformed_source_experience_section() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_payload(
        {
            'headline': 'Engineer',
            'summary': '',
            'objective': '',
            'candidate_type': 'experienced',
            'contact': {'name': 'Test', 'email': '', 'phone': '', 'location': '', 'links': []},
            'technical_expertise': {},
            'skills': ['Python'],
            'experience': [
                {
                    'title': 'Software Engineer',
                    'company': 'Alpha',
                    'employment_type': 'full_time',
                    'start_date': '2022-01',
                    'end_date': '2022-03',
                    'is_current': False,
                    'duration_text': None,
                    'tech_stack': ['Python'],
                    'bullets': ['Built APIs'],
                    'notes': [],
                }
            ],
            'projects': [],
            'education': [],
            'certifications': [],
            'achievements': [],
            'languages': [],
            'claimed_experience_text': None,
            'sections': [
                {
                    'section_key': 'experience',
                    'title': 'Experience',
                    'section_type': 'experience',
                    'raw_text': 'This is malformed prose.',
                    'content': {'text': 'This is malformed prose.', 'items': ['This is malformed prose.']},
                    'display_order': 0,
                }
            ],
        },
        raw_text='Software Engineer Alpha Jan 2022 - Mar 2022',
    )

    experience_section = next(section for section in normalized['sections'] if section['section_key'] == 'experience')
    assert experience_section['content']['items'][0]['title'] == 'Software Engineer'
    assert experience_section['content']['items'][0]['company'] == 'Alpha'


def test_long_prose_fragments_are_rejected_from_skills() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_payload(
        {
            'headline': 'Engineer',
            'summary': 'Professional summary text',
            'objective': 'Seeking a role',
            'candidate_type': 'experienced',
            'contact': {'name': 'Test', 'email': '', 'phone': '', 'location': '', 'links': []},
            'technical_expertise': {},
            'skills': [
                'Python',
                'Collaborated with client teams to develop scalable solutions.',
                'Software Engineer',
                'JavaScript',
            ],
            'experience': [],
            'projects': [],
            'education': [],
            'certifications': [],
            'achievements': [],
            'languages': [],
            'claimed_experience_text': None,
            'sections': [],
        },
        raw_text='Resume raw text',
    )

    assert normalized['skills'] == ['Python', 'JavaScript']


def test_fallback_source_sections_are_used_only_when_canonical_section_is_missing() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_payload(
        {
            'headline': 'Engineer',
            'summary': '',
            'objective': '',
            'candidate_type': 'fresher',
            'contact': {'name': 'Test', 'email': '', 'phone': '', 'location': '', 'links': []},
            'technical_expertise': {},
            'skills': [],
            'experience': [],
            'projects': [],
            'education': [],
            'certifications': [],
            'achievements': [],
            'languages': [],
            'claimed_experience_text': None,
            'sections': [
                {
                    'section_key': 'links',
                    'title': 'Links',
                    'section_type': 'links',
                    'raw_text': 'https://github.com/test',
                    'content': {'text': 'https://github.com/test', 'items': ['https://github.com/test']},
                    'display_order': 0,
                },
                {
                    'section_key': 'skills',
                    'title': 'Skills',
                    'section_type': 'skills',
                    'raw_text': 'Bad prose should not win.',
                    'content': {'text': 'Bad prose should not win.', 'items': ['Bad prose should not win.']},
                    'display_order': 1,
                },
            ],
        },
        raw_text='Resume raw text',
    )

    section_keys = [section['section_key'] for section in normalized['sections']]
    assert 'links' in section_keys
    assert 'skills' not in section_keys


def test_merged_work_history_heading_stays_in_experience_not_skills() -> None:
    extractor = HeuristicResumeExtractor()

    parsed = extractor.extract(
        'Jane Doe\nWORK HISTORYRole: Software Engineer | Alpha | Jan 2022 - Mar 2023\n'
        'Built APIs\nSKILLS\nPython\nDjango\n'
    )

    assert parsed.data['experience']
    assert parsed.data['experience'][0]['title'] == 'Role: Software Engineer'
    assert parsed.data['skills'] == ['Python', 'Django']


def test_experience_bullet_lines_do_not_become_separate_entries() -> None:
    extractor = HeuristicResumeExtractor()

    entries = extractor._group_experience_entries(
        [
            'Software Engineer | Alpha Pvt Ltd | Jan 2022 - Mar 2023',
            'Developed REST APIs for payments',
            'Collaborated with QA team',
            'Improved application performance',
        ],
        'experience',
    )

    assert len(entries) == 1
    assert entries[0]['title'] == 'Software Engineer'
    assert len(entries[0]['bullets']) == 3


def test_stray_prose_before_first_real_role_does_not_seed_experience_entry() -> None:
    extractor = HeuristicResumeExtractor()

    entries = extractor._group_experience_entries(
        [
            'Quick learner and team player',
            'Seeking an opportunity to grow',
            'Software Engineer | Alpha Pvt Ltd | Jan 2022 - Mar 2023',
            'Developed REST APIs for payments',
            'Implemented deployment automation',
        ],
        'experience',
    )

    assert len(entries) == 1
    assert entries[0]['title'] == 'Software Engineer'
    assert entries[0]['bullets'] == ['Developed REST APIs for payments', 'Implemented deployment automation']


def test_one_real_role_with_many_bullets_stays_one_entry() -> None:
    extractor = HeuristicResumeExtractor()

    parsed = extractor.extract(
        'WORK EXPERIENCE\n'
        'Backend Engineer at Acme LLC | Jan 2022 - Present | Remote\n'
        'Developed APIs\n'
        'Improved reliability\n'
        'Implemented background jobs\n'
    )

    assert len(parsed.data['experience']) == 1
    assert parsed.data['experience'][0]['company'] == 'Acme LLC'
    assert len(parsed.data['experience'][0]['bullets']) == 3


def test_weak_prose_after_role_stays_attached_as_bullets() -> None:
    extractor = HeuristicResumeExtractor()

    entries = extractor._group_experience_entries(
        [
            'Fullstack Developer | Example Inc | Jan 2021 - Jan 2023',
            'Developed internal dashboards',
            'Worked with stakeholders to refine requirements.',
            'Good communication and learning attitude',
        ],
        'experience',
    )

    assert len(entries) == 1
    assert 'Developed internal dashboards' in entries[0]['bullets']
    assert all('learning attitude' not in bullet for bullet in entries[0]['bullets'])


def test_entries_with_no_title_company_date_and_one_line_are_dropped() -> None:
    extractor = HeuristicResumeExtractor()

    entries = extractor._group_experience_entries(
        ['Ability to learn quickly and contribute effectively'],
        'experience',
    )

    assert entries == []


def test_work_history_role_merge_yields_real_experience_entry() -> None:
    extractor = HeuristicResumeExtractor()

    parsed = extractor.extract(
        'WORK HISTORYRole: Fullstack Developer | Beta Ltd | Jan 2020 - Feb 2022\n'
        'Developed customer-facing modules\n'
    )

    assert len(parsed.data['experience']) == 1
    assert parsed.data['experience'][0]['company'] == 'Beta Ltd'


def test_experience_section_item_provides_stable_title_fallback() -> None:
    service = ResumeProcessingService()

    item = service._experience_section_item(
        {
            'title': None,
            'company': None,
            'location': '',
            'start_date': '2021-01',
            'end_date': '2021-06',
            'duration_text': None,
            'bullets': ['Developed APIs', 'Improved uptime'],
            'notes': [],
            'tech_stack': [],
            'is_current': False,
            'employment_type': 'full_time',
        }
    )

    assert item['title'] == 'Professional Experience'
    assert item['bullets'] == ['Developed APIs', 'Improved uptime']
    assert item['details'] == []


def test_one_line_weak_statement_is_dropped_from_experience() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': None,
            'company': None,
            'employment_type': 'unknown',
            'start_date': None,
            'end_date': None,
            'is_current': False,
            'duration_text': None,
            'tech_stack': [],
            'bullets': ['Worked on Various technologies'],
            'notes': [],
        }
    ])

    assert normalized == []


def test_good_knowledge_of_python_does_not_become_experience_entry() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': None,
            'company': None,
            'employment_type': 'unknown',
            'start_date': None,
            'end_date': None,
            'is_current': False,
            'duration_text': None,
            'tech_stack': ['Good knowledge of Python and Django frameworks'],
            'bullets': ['Good knowledge of Python'],
            'notes': ['Good knowledge of Python'],
        }
    ])

    assert normalized == []


def test_quick_learner_and_team_player_does_not_become_experience_entry() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': None,
            'company': None,
            'employment_type': 'unknown',
            'start_date': None,
            'end_date': None,
            'is_current': False,
            'duration_text': None,
            'tech_stack': [],
            'bullets': ['Quick learner and team player'],
            'notes': [],
        }
    ])

    assert normalized == []


def test_ability_to_learn_quickly_does_not_become_experience_entry() -> None:
    extractor = HeuristicResumeExtractor()

    entries = extractor._group_experience_entries(['Ability to learn quickly'], 'experience')

    assert entries == []


def test_real_dated_role_with_multiple_bullets_survives_normalization() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': 'Backend Engineer',
            'company': 'Acme LLC',
            'employment_type': 'full_time',
            'start_date': '2022-01',
            'end_date': '2022-06',
            'is_current': False,
            'duration_text': None,
            'tech_stack': ['Python', 'Developed APIs for clients.'],
            'bullets': ['Developed APIs', 'Improved reliability', 'Good knowledge of Python'],
            'notes': ['Backend Engineer', 'Acme LLC', 'Backend Engineer'],
        }
    ])

    assert len(normalized) == 1
    assert normalized[0]['tech_stack'] == ['Python']
    assert normalized[0]['bullets'] == ['Developed APIs', 'Improved reliability']


def test_entry_with_dates_and_two_strong_bullets_survives_without_title_or_company() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': None,
            'company': None,
            'employment_type': 'unknown',
            'start_date': '2021-01',
            'end_date': '2021-03',
            'is_current': False,
            'duration_text': None,
            'tech_stack': [],
            'bullets': ['Developed internal APIs', 'Implemented deployment automation'],
            'notes': [],
        }
    ])

    assert len(normalized) == 1
    item = service._experience_section_item(normalized[0])
    assert item is not None
    assert item['title'] == 'Professional Experience'


def test_title_and_date_with_weak_company_and_no_strong_bullets_is_dropped() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': 'Associate',
            'company': 'Worked with clients',
            'employment_type': 'unknown',
            'start_date': '2022-01',
            'end_date': '2022-03',
            'is_current': False,
            'duration_text': None,
            'tech_stack': [],
            'bullets': ['Quick learner and team player'],
            'notes': [],
        }
    ])

    assert normalized == []


def test_client_description_bullet_is_rejected() -> None:
    service = ResumeProcessingService()

    bullets = service._clean_experience_bullets([
        'Client: Bank Of Montreal, a leading North American bank serving millions of customers',
    ])

    assert bullets == []


def test_global_manufacturer_company_description_bullet_is_rejected() -> None:
    service = ResumeProcessingService()

    bullets = service._clean_experience_bullets([
        'Acme Corp is a global manufacturer serving customers in 30 countries',
    ])

    assert bullets == []


def test_saas_platform_company_description_bullet_is_rejected() -> None:
    service = ResumeProcessingService()

    bullets = service._clean_experience_bullets([
        'XYZ is a SaaS platform focused on e-commerce automation',
    ])

    assert bullets == []


def test_real_work_bullet_for_automation_tools_is_kept() -> None:
    service = ResumeProcessingService()

    bullets = service._clean_experience_bullets([
        'Developed automation tools for internal projects',
    ])

    assert bullets == ['Developed automation tools for internal projects']


def test_real_work_bullet_for_rest_apis_is_kept() -> None:
    service = ResumeProcessingService()

    bullets = service._clean_experience_bullets([
        'Built REST APIs for order processing',
    ])

    assert bullets == ['Built REST APIs for order processing']


def test_credible_title_company_dates_survive_with_minimal_bullets() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': 'Software Engineer',
            'company': 'Acme LLC',
            'employment_type': 'full_time',
            'start_date': '2022-01',
            'end_date': '2022-03',
            'is_current': False,
            'duration_text': None,
            'tech_stack': [],
            'bullets': ['Supported release process'],
            'notes': [],
        }
    ])

    assert len(normalized) == 1
    item = service._experience_section_item(normalized[0])
    assert item is not None
    assert item['title'] == 'Software Engineer'


def test_mixed_bullet_sets_keep_work_bullets_and_drop_company_descriptions() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': 'Software Engineer',
            'company': 'Acme LLC',
            'employment_type': 'full_time',
            'start_date': '2022-01',
            'end_date': '2022-03',
            'is_current': False,
            'duration_text': None,
            'tech_stack': [],
            'bullets': [
                'Acme Corp is a global manufacturer serving customers in 30 countries',
                'Built REST APIs for order processing',
                'XYZ is a SaaS platform focused on e-commerce automation',
                'Developed automation tools for internal projects',
            ],
            'notes': [],
        }
    ])

    assert len(normalized) == 1
    assert normalized[0]['bullets'] == [
        'Built REST APIs for order processing',
        'Developed automation tools for internal projects',
    ]


def test_entry_with_dates_and_only_weak_bullets_fails_without_title_or_company() -> None:
    service = ResumeProcessingService()

    normalized = service._normalize_experience_entries([
        {
            'title': None,
            'company': None,
            'employment_type': 'unknown',
            'start_date': '2021-01',
            'end_date': '2021-03',
            'is_current': False,
            'duration_text': None,
            'tech_stack': [],
            'bullets': ['Good knowledge of Python', 'Quick learner and team player'],
            'notes': [],
        }
    ])

    assert normalized == []


def test_experience_section_item_returns_none_for_weak_entry() -> None:
    service = ResumeProcessingService()

    item = service._experience_section_item(
        {
            'title': None,
            'company': None,
            'location': '',
            'start_date': None,
            'end_date': None,
            'duration_text': None,
            'bullets': ['Good knowledge of Python'],
            'notes': [],
            'tech_stack': [],
            'is_current': False,
            'employment_type': 'unknown',
        }
    )

    assert item is None


def test_experience_section_item_returns_none_for_thin_header_only_entry() -> None:
    service = ResumeProcessingService()

    item = service._experience_section_item(
        {
            'title': 'Associate',
            'company': '',
            'location': '',
            'start_date': '2022-01',
            'end_date': '2022-03',
            'duration_text': None,
            'bullets': [],
            'notes': [],
            'tech_stack': [],
            'is_current': False,
            'employment_type': 'unknown',
        }
    )

    assert item is None


def test_weak_header_only_entry_does_not_render_into_experience_section() -> None:
    service = ResumeProcessingService()

    sections = service._build_sections(
        headline='',
        summary='',
        objective='',
        contact={'name': '', 'email': '', 'phone': '', 'location': '', 'links': []},
        technical_expertise={key: [] for key in ('languages', 'frameworks', 'libraries', 'databases', 'tools', 'cloud', 'devops', 'web_technologies', 'testing', 'other')},
        skills=[],
        experience=[
            {
                'title': 'Associate',
                'company': '',
                'location': '',
                'start_date': '2022-01',
                'end_date': '2022-03',
                'duration_text': None,
                'bullets': [],
                'notes': [],
                'tech_stack': [],
                'is_current': False,
                'employment_type': 'unknown',
            }
        ],
        projects=[],
        education=[],
        certifications=[],
        achievements=[],
        languages=[],
        source_sections=[],
    )

    assert all(section['section_key'] != 'experience' for section in sections)


def test_build_sections_excludes_empty_weak_experience_items() -> None:
    service = ResumeProcessingService()

    sections = service._build_sections(
        headline='',
        summary='',
        objective='',
        contact={'name': '', 'email': '', 'phone': '', 'location': '', 'links': []},
        technical_expertise={key: [] for key in ('languages', 'frameworks', 'libraries', 'databases', 'tools', 'cloud', 'devops', 'web_technologies', 'testing', 'other')},
        skills=[],
        experience=[
            {
                'title': None,
                'company': None,
                'location': '',
                'start_date': None,
                'end_date': None,
                'duration_text': None,
                'bullets': ['Ability to learn quickly'],
                'notes': [],
                'tech_stack': [],
                'is_current': False,
                'employment_type': 'unknown',
            }
        ],
        projects=[],
        education=[],
        certifications=[],
        achievements=[],
        languages=[],
        source_sections=[],
    )

    assert all(section['section_key'] != 'experience' for section in sections)


def test_resume_text_extractor_reads_pdf_from_file_like_object() -> None:
    extractor = ResumeTextExtractor()

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakePdfReader:
        def __init__(self, file_obj) -> None:
            assert hasattr(file_obj, 'read')
            assert hasattr(file_obj, 'seek')
            file_obj.seek(0)
            assert file_obj.read().startswith(b'%PDF')
            file_obj.seek(0)
            self.pages = [FakePage('First page'), FakePage('Second page')]
            self.is_encrypted = False

    fake_module = types.ModuleType('pypdf')
    fake_module.PdfReader = FakePdfReader
    original_module = sys.modules.get('pypdf')
    sys.modules['pypdf'] = fake_module
    try:
        text, mime_type = extractor.extract(io.BytesIO(b'%PDF-1.4 fake pdf bytes'), filename='resume.pdf')
    finally:
        if original_module is None:
            sys.modules.pop('pypdf', None)
        else:
            sys.modules['pypdf'] = original_module

    assert text == 'First page\nSecond page'
    assert mime_type == 'application/pdf'


def test_resume_text_extractor_reads_docx_from_file_like_object() -> None:
    extractor = ResumeTextExtractor()

    class FakeParagraph:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeDocument:
        def __init__(self, file_obj) -> None:
            assert hasattr(file_obj, 'read')
            assert hasattr(file_obj, 'seek')
            file_obj.seek(0)
            assert file_obj.read().startswith(b'PK')
            file_obj.seek(0)
            self.paragraphs = [FakeParagraph('Experience summary'), FakeParagraph('Built storage-safe parser')]

    fake_module = types.ModuleType('docx')
    fake_module.Document = FakeDocument
    original_module = sys.modules.get('docx')
    sys.modules['docx'] = fake_module
    try:
        text, mime_type = extractor.extract(io.BytesIO(b'PK\x03\x04 fake docx bytes'), filename='resume.docx')
    finally:
        if original_module is None:
            sys.modules.pop('docx', None)
        else:
            sys.modules['docx'] = original_module

    assert text == 'Experience summary\nBuilt storage-safe parser'
    assert mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def test_resume_processing_health_reports_storage_backend_state() -> None:
    service = ResumeProcessingService()

    with patch('smartInterviewApp.resume_processing.default_storage.exists', return_value=False):
        health = service.health_check()

    assert health['storage_backend']
    assert health['storage_reachable'] is True
    assert health['storage_error'] == ''
    assert 'storage' in health['notes']


def test_resume_processing_health_reports_storage_failures() -> None:
    service = ResumeProcessingService()

    with patch('smartInterviewApp.resume_processing.default_storage.exists', side_effect=RuntimeError('bucket unavailable')):
        health = service.health_check()

    assert health['storage_reachable'] is False
    assert health['storage_error'] == 'bucket unavailable'
    assert health['ready'] is False
