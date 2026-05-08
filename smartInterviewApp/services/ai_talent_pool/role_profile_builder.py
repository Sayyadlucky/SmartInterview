from __future__ import annotations

import html
import re
from typing import Any

from smartInterviewApp.models import Vacancies
from .normalization import canonical_display_list_from_tokens, extract_exact_display_skills, extract_skill_tokens
from .role_graph import infer_role_family, title_display
from .skill_graph import build_related_skill_evidence

COMMON_TERM_CORRECTIONS = {
    'salesfore': 'salesforce',
    'sales force': 'salesforce',
    'javascript': 'javascript',
    'java script': 'javascript',
    'reactjs': 'react',
    'react.js': 'react',
    'nodejs': 'node.js',
    'node js': 'node.js',
    'full stack': 'fullstack',
    'full-stack': 'fullstack',
    'biz dev': 'business development',
}

ROLE_FAMILY_SKILLS = {
    'salesforce': ['Salesforce', 'Apex', 'Lightning', 'SOQL', 'Visualforce', 'CRM'],
    'python_fullstack': ['Python', 'JavaScript', 'React', 'Django', 'REST'],
    'fullstack': ['Python', 'JavaScript', 'React', 'Django', 'REST API'],
    'backend_python': ['Python', 'Django', 'FastAPI', 'PostgreSQL', 'REST'],
    'backend': ['Python', 'Django', 'FastAPI', 'PostgreSQL', 'REST API'],
    'frontend_js': ['JavaScript', 'TypeScript', 'React', 'HTML', 'CSS'],
    'frontend': ['JavaScript', 'TypeScript', 'React', 'HTML', 'CSS'],
    'data_ml': ['Python', 'SQL', 'Machine Learning', 'Pandas', 'NumPy'],
    'ml': ['Python', 'SQL', 'Machine Learning', 'Pandas', 'NumPy'],
    'devops': ['Docker', 'Kubernetes', 'AWS', 'Terraform', 'Linux'],
    'cloud': ['Docker', 'Kubernetes', 'AWS', 'Terraform', 'Linux'],
    'qa': ['Selenium', 'Playwright', 'Cypress', 'pytest', 'QA'],
    'testing': ['Selenium', 'Playwright', 'Cypress', 'Postman', 'QA'],
}

REMOTE_TOKENS = {'remote', 'hybrid', 'wfh', 'work from home', 'anywhere'}
ROLE_EMBEDDING_TEXT_BUILDER_VERSION = 'v3_structured_sections'


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ''))
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _short_text(value: str, *, max_words: int = 40) -> str:
    words = _clean_text(value).split()
    if len(words) <= max_words:
        return ' '.join(words)
    return ' '.join(words[:max_words]).strip() + '...'


def _token_count(value: str) -> int:
    return len(re.findall(r'[A-Za-z0-9+#./-]+', value or ''))


def _build_structured_role_embedding_text(
    *,
    title: str,
    role_family: str,
    role_subfamily: str,
    exact_required_skills: list[str],
    supporting_skills: list[str],
    preferred_skills: list[str],
    description: str,
    experience_required: str,
    location: str,
) -> tuple[str, list[str]]:
    sections_used: list[str] = []
    parts: list[str] = []
    if title:
        parts.append(f'Role: {title}')
        sections_used.append('title')
    if role_family:
        parts.append(f'Role Family: {role_family}')
        sections_used.append('role_family')
    if role_subfamily:
        parts.append(f'Role Subfamily: {role_subfamily}')
        sections_used.append('role_subfamily')
    if exact_required_skills:
        parts.append(f'Exact Required Skills: {", ".join(exact_required_skills[:10])}')
        sections_used.append('exact_required_skills')
    if supporting_skills:
        parts.append(f'Supporting Skills: {", ".join(supporting_skills[:8])}')
        sections_used.append('supporting_skills')
    if preferred_skills:
        parts.append(f'Preferred Skills: {", ".join(preferred_skills[:8])}')
        sections_used.append('preferred_skills')
    if description:
        parts.append(f'Role Summary: {_short_text(description, max_words=28)}')
        sections_used.append('role_summary')
    if experience_required:
        parts.append(f'Experience Required: {experience_required}')
        sections_used.append('experience_required')
    if location:
        parts.append(f'Location: {location}')
        sections_used.append('location')
    return '\n'.join(parts).strip(), sections_used


def _normalize_text(value: str) -> str:
    normalized = _clean_text(value).lower()
    for source, target in COMMON_TERM_CORRECTIONS.items():
        normalized = re.sub(rf'(?<![a-z0-9]){re.escape(source)}(?![a-z0-9])', target, normalized)
    return re.sub(r'\s+', ' ', normalized).strip()


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _extract_candidate_terms(text: str) -> list[str]:
    corrected = _normalize_text(text)
    display_terms = extract_exact_display_skills(corrected, allow_ambiguous=False)
    token_terms = canonical_display_list_from_tokens(extract_skill_tokens(corrected))
    return _dedupe_strings([*display_terms, *token_terms])


def _extract_skill_buckets(description: str) -> tuple[list[str], list[str]]:
    text = _clean_text(description)
    lowered = _normalize_text(text)
    must_have: list[str] = []
    preferred: list[str] = []

    bucket_patterns = [
        (r'(?:must have|required|required skills|mandatory skills|requirements?)[:\- ]+([^.;]+)', must_have),
        (r'(?:preferred|nice to have|good to have|bonus skills?)[:\- ]+([^.;]+)', preferred),
    ]

    for pattern, bucket in bucket_patterns:
        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            bucket.extend(_extract_candidate_terms(match.group(1)))

    if not must_have:
        must_have.extend(_extract_candidate_terms(text))

    return _dedupe_strings(must_have), _dedupe_strings(preferred)


def _parse_experience_range(value: str) -> dict[str, float | None]:
    text = _normalize_text(value)
    if not text:
        return {'min_years': None, 'max_years': None, 'label': ''}

    range_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)', text)
    if range_match:
        low, high = float(range_match.group(1)), float(range_match.group(2))
        return {'min_years': min(low, high), 'max_years': max(low, high), 'label': value}

    plus_match = re.search(r'(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)', text)
    if plus_match:
        low = float(plus_match.group(1))
        return {'min_years': low, 'max_years': None, 'label': value}

    single_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:years?|yrs?)', text)
    if single_match:
        number = float(single_match.group(1))
        return {'min_years': number, 'max_years': number + 2, 'label': value}

    return {'min_years': None, 'max_years': None, 'label': value}


def build_role_profile(vacancy: Vacancies) -> dict[str, Any]:
    raw_title = _clean_text(vacancy.role)
    normalized_title = _normalize_text(raw_title)
    title = title_display(normalized_title or raw_title)
    position = _clean_text(vacancy.position)
    description = _clean_text(vacancy.description)
    normalized_description = _normalize_text(description)
    location = _clean_text(vacancy.location)
    experience_required = _clean_text(vacancy.experience_required)
    required_skills, preferred_skills = _extract_skill_buckets(description)
    if raw_title:
        required_skills = _dedupe_strings([*required_skills, *_extract_candidate_terms(raw_title)])

    role_family_data = infer_role_family(title=title or raw_title, skills=required_skills, description=description)
    inferred_role_family = role_family_data.get('inferred_role_family', '')
    inferred_family_skills = ROLE_FAMILY_SKILLS.get(str(role_family_data.get('role_subfamily') or ''), [])[:] or ROLE_FAMILY_SKILLS.get(inferred_role_family, [])[:]
    used_title_inference = bool(role_family_data.get('used_title_inference'))
    normalized_required_skill_labels = canonical_display_list_from_tokens(_normalize_skill_tokens(required_skills))
    normalized_preferred_skill_labels = canonical_display_list_from_tokens(_normalize_skill_tokens(preferred_skills))
    inferred_family_skill_labels = _dedupe_strings(inferred_family_skills)
    role_supporting_skill_inference = [skill for skill in inferred_family_skill_labels if skill not in normalized_required_skill_labels][:6]
    role_related_skill_evidence = build_related_skill_evidence(normalized_required_skill_labels)
    role_adjacent_skill_inference = _dedupe_strings([
        str(item.get('skill', ''))
        for related_items in role_related_skill_evidence.values()
        for item in related_items
        if str(item.get('skill', '')) not in normalized_required_skill_labels and str(item.get('skill', '')) not in role_supporting_skill_inference
    ])[:6]

    role_profile_is_sparse = not bool(description.strip()) and not bool(vacancy.experience_required.strip()) if vacancy.experience_required is not None else not bool(description.strip())
    if not description.strip() and len(required_skills) <= 1 and inferred_role_family:
        role_profile_is_sparse = True

    embedding_text, role_embedding_sections_used = _build_structured_role_embedding_text(
        title=title,
        role_family=str(role_family_data.get('role_family', '')),
        role_subfamily=str(role_family_data.get('role_subfamily', '')),
        exact_required_skills=normalized_required_skill_labels,
        supporting_skills=role_supporting_skill_inference,
        preferred_skills=normalized_preferred_skill_labels,
        description=description,
        experience_required=experience_required,
        location=location,
    )

    company = vacancy.company or getattr(getattr(vacancy, 'admin', None), 'company_profile', None)
    experience_range = _parse_experience_range(experience_required)
    remote_friendly = any(token in location.lower() for token in REMOTE_TOKENS) if location else False

    return {
        'role_id': vacancy.id,
        'title': title,
        'normalized_title': normalized_title,
        'position': position,
        'description': description,
        'required_skills': required_skills,
        'exact_required_skills': normalized_required_skill_labels,
        'normalized_required_skills': normalized_required_skill_labels,
        'preferred_skills': preferred_skills,
        'normalized_preferred_skills': normalized_preferred_skill_labels,
        'role_supporting_skill_inference': role_supporting_skill_inference,
        'role_adjacent_skill_inference': role_adjacent_skill_inference,
        'role_related_skill_evidence': role_related_skill_evidence,
        'experience_required': experience_required,
        'experience_range': experience_range,
        'location': location,
        'job_type': _clean_text(vacancy.get_job_type_display() if vacancy.job_type else ''),
        'status': vacancy.status,
        'status_label': vacancy.status.replace('_', ' ').title(),
        'company_name': _clean_text(getattr(company, 'display_name', '') or getattr(company, 'legal_name', '')),
        'embedding_text': embedding_text,
        'embedding_text_token_count': _token_count(embedding_text),
        'embedding_text_builder_version': ROLE_EMBEDDING_TEXT_BUILDER_VERSION,
        'role_embedding_sections_used': role_embedding_sections_used,
        'remote_friendly': remote_friendly,
        'role_profile_is_sparse': role_profile_is_sparse,
        'role_family': role_family_data.get('role_family', ''),
        'role_subfamily': role_family_data.get('role_subfamily', ''),
        'inferred_role_family': inferred_role_family,
        'used_title_inference': used_title_inference,
    }


def build_query_profile(*, query: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = filters or {}
    raw_title = _clean_text(query)
    normalized_title = _normalize_text(raw_title)
    title = title_display(normalized_title or raw_title)
    description = _clean_text(query)
    location = _clean_text(filters.get('location'))
    experience_required = ''

    required_skills = _extract_candidate_terms(query)
    preferred_skills: list[str] = []
    role_family_data = infer_role_family(title=title or raw_title, skills=required_skills, description=description)
    inferred_role_family = role_family_data.get('inferred_role_family', '')
    inferred_family_skills = ROLE_FAMILY_SKILLS.get(str(role_family_data.get('role_subfamily') or ''), [])[:] or ROLE_FAMILY_SKILLS.get(inferred_role_family, [])[:]

    normalized_required_skill_labels = canonical_display_list_from_tokens(_normalize_skill_tokens(required_skills))
    normalized_preferred_skill_labels = canonical_display_list_from_tokens(_normalize_skill_tokens(preferred_skills))
    role_supporting_skill_inference = [skill for skill in _dedupe_strings(inferred_family_skills) if skill not in normalized_required_skill_labels][:6]
    role_related_skill_evidence = build_related_skill_evidence(normalized_required_skill_labels)
    role_adjacent_skill_inference = _dedupe_strings([
        str(item.get('skill', ''))
        for related_items in role_related_skill_evidence.values()
        for item in related_items
        if str(item.get('skill', '')) not in normalized_required_skill_labels and str(item.get('skill', '')) not in role_supporting_skill_inference
    ])[:6]

    min_experience = filters.get('min_experience')
    max_experience = filters.get('max_experience')
    experience_range = {
        'min_years': float(min_experience) if min_experience is not None else None,
        'max_years': float(max_experience) if max_experience is not None else None,
        'label': '',
    }
    role_profile_is_sparse = not bool(normalized_required_skill_labels) and not bool(description.strip())
    embedding_text, role_embedding_sections_used = _build_structured_role_embedding_text(
        title=title,
        role_family=str(role_family_data.get('role_family', '')),
        role_subfamily=str(role_family_data.get('role_subfamily', '')),
        exact_required_skills=normalized_required_skill_labels,
        supporting_skills=role_supporting_skill_inference,
        preferred_skills=normalized_preferred_skill_labels,
        description=query,
        experience_required='',
        location=location,
    )

    return {
        'role_id': None,
        'title': title or raw_title,
        'normalized_title': normalized_title,
        'position': '',
        'description': description,
        'required_skills': required_skills,
        'exact_required_skills': normalized_required_skill_labels,
        'normalized_required_skills': normalized_required_skill_labels,
        'preferred_skills': preferred_skills,
        'normalized_preferred_skills': normalized_preferred_skill_labels,
        'role_supporting_skill_inference': role_supporting_skill_inference,
        'role_adjacent_skill_inference': role_adjacent_skill_inference,
        'role_related_skill_evidence': role_related_skill_evidence,
        'experience_required': experience_required,
        'experience_range': experience_range,
        'location': location,
        'job_type': '',
        'status': 'query',
        'status_label': 'Query',
        'company_name': '',
        'embedding_text': embedding_text,
        'embedding_text_token_count': _token_count(embedding_text),
        'embedding_text_builder_version': ROLE_EMBEDDING_TEXT_BUILDER_VERSION,
        'role_embedding_sections_used': role_embedding_sections_used,
        'remote_friendly': False,
        'role_profile_is_sparse': role_profile_is_sparse,
        'role_family': role_family_data.get('role_family', ''),
        'role_subfamily': role_family_data.get('role_subfamily', ''),
        'inferred_role_family': inferred_role_family,
        'used_title_inference': bool(role_family_data.get('used_title_inference')),
    }


def _normalize_skill_tokens(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(extract_skill_tokens(value))
    return tokens
