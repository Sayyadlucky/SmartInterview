from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

from django.contrib.auth.models import User

from smartInterviewApp.models import CandidateResume, Interview
from smartInterviewApp.resume_processing import ResumeProcessingService
from .normalization import canonical_display_list_from_tokens, canonicalize_skill_label, extract_exact_display_skills, extract_skill_tokens
from .role_graph import infer_candidate_families
from .skill_graph import best_skill_evidence, build_related_skill_evidence, canonical_skill_name


LOW_PRIORITY_EMBEDDING_SKILLS = {
    'Administrative Support',
    'Compliance',
    'Coordination',
    'Documentation',
    'Issue Resolution',
    'Policy',
    'Risk',
}

EMBEDDING_TEXT_BUILDER_VERSION = 'v3_structured_sections'


def _clean_text(value: Any) -> str:
    return str(value or '').strip()


def _short_text(value: str, *, max_words: int = 28) -> str:
    words = _clean_text(value).split()
    if len(words) <= max_words:
        return ' '.join(words)
    return ' '.join(words[:max_words]).strip() + '...'


def _is_clean_company(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    if len(text.split()) > 6:
        return False
    if any(marker in text.lower() for marker in ['developed', 'created', 'built', 'implemented', 'responsible', 'worked on']):
        return False
    return True


def _token_count(value: str) -> int:
    return len(re.findall(r'[A-Za-z0-9+#./-]+', value or ''))


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _flatten_nested_items(values: Any) -> list[str]:
    if isinstance(values, str):
        return [_clean_text(values)]
    if not isinstance(values, list):
        return []

    output: list[str] = []
    for item in values:
        if isinstance(item, str):
            output.append(_clean_text(item))
            continue
        if not isinstance(item, dict):
            continue
        for key in ('title', 'role', 'company', 'institution', 'issuer', 'label', 'value', 'description', 'duration'):
            if item.get(key):
                output.append(_clean_text(item.get(key)))
        for nested_key in ('details', 'bullets', 'notes', 'tech_stack'):
            nested = item.get(nested_key)
            if isinstance(nested, list):
                output.extend(_clean_text(value) for value in nested)
    return [value for value in output if value]


def _flatten_section_content(content: Any) -> list[str]:
    if isinstance(content, str):
        cleaned = _clean_text(content)
        return [cleaned] if cleaned else []
    if isinstance(content, list):
        output: list[str] = []
        for item in content:
            output.extend(_flatten_section_content(item))
        return output
    if not isinstance(content, dict):
        return []

    output: list[str] = []
    for value in content.values():
        output.extend(_flatten_section_content(value))
    return output


def _resume_section_lines(resume: CandidateResume | None) -> list[str]:
    if not resume:
        return []

    lines: list[str] = []
    for section in resume.sections.all():
        title = _clean_text(section.title)
        raw_text = _clean_text(section.raw_text)
        if title:
            lines.append(title)
        if raw_text:
            lines.append(raw_text)
        lines.extend(_flatten_section_content(section.content))
    return _dedupe_strings(lines)


def _candidate_name(candidate: User) -> str:
    return f'{candidate.first_name} {candidate.last_name}'.strip().title() or candidate.username


def _extract_resume_skills(resume_data: dict[str, Any], *, section_lines: list[str]) -> list[str]:
    technical_expertise = resume_data.get('technical_expertise') or {}
    technical_values: list[str] = []
    if isinstance(technical_expertise, dict):
        for entries in technical_expertise.values():
            if isinstance(entries, list):
                technical_values.extend(_clean_text(value) for value in entries)

    experience_entries = resume_data.get('experience') or []
    project_entries = resume_data.get('projects') or []
    certification_entries = resume_data.get('certifications') or []

    experience_skills: list[str] = []
    for entry in experience_entries:
        if not isinstance(entry, dict):
            continue
        experience_skills.extend(_clean_text(value) for value in (entry.get('tech_stack') or []))

    project_skills: list[str] = []
    for entry in project_entries:
        if not isinstance(entry, dict):
            continue
        project_skills.extend(_clean_text(value) for value in (entry.get('tech_stack') or []))

    certification_values = _flatten_nested_items(certification_entries)

    explicit_skill_inputs = [
        *(_clean_text(skill) for skill in (resume_data.get('skills') or [])),
        *technical_values,
        *experience_skills,
        *project_skills,
        *certification_values,
    ]
    narrative_skill_inputs = [
        _clean_text(resume_data.get('headline')),
        _clean_text(resume_data.get('summary')),
        *experience_lines_from_resume_data(resume_data),
        *project_lines_from_resume_data(resume_data),
        _clean_text(resume_data.get('raw_text_preview')),
        *section_lines,
    ]

    explicit_skills = _dedupe_strings([value for value in [*explicit_skill_inputs, *narrative_skill_inputs] if value])
    extracted_displays: list[str] = []
    for value in explicit_skill_inputs:
        extracted_displays.extend(extract_exact_display_skills(value, allow_ambiguous=True))
    for value in narrative_skill_inputs:
        extracted_displays.extend(extract_exact_display_skills(value, allow_ambiguous=False))

    return _dedupe_strings([*explicit_skills, *extracted_displays])


def experience_lines_from_resume_data(resume_data: dict[str, Any]) -> list[str]:
    return _flatten_nested_items(resume_data.get('experience'))


def project_lines_from_resume_data(resume_data: dict[str, Any]) -> list[str]:
    return _flatten_nested_items(resume_data.get('projects'))


def _recent_role_summaries(experience_items: list[dict[str, Any]]) -> list[str]:
    summaries: list[str] = []
    for entry in experience_items[:3]:
        if not isinstance(entry, dict):
            continue
        role = _clean_text(entry.get('role') or entry.get('title'))
        company = _clean_text(entry.get('company'))
        summary = ''
        if role and _is_clean_company(company):
            summary = f'{role} at {company}'
        elif role:
            summary = role
        elif _is_clean_company(company):
            summary = company
        if summary:
            summaries.append(summary)
    return summaries


def _recent_project_summaries(project_items: list[dict[str, Any]]) -> list[str]:
    summaries: list[str] = []
    for entry in project_items[:2]:
        if not isinstance(entry, dict):
            continue
        title = _clean_text(entry.get('title') or entry.get('label'))
        tech_stack = _dedupe_strings([_clean_text(value) for value in (entry.get('tech_stack') or []) if _clean_text(value)])
        description = _short_text(_clean_text(entry.get('description')), max_words=12)
        parts = []
        if title:
            parts.append(title)
        if tech_stack:
            parts.append(f'with {", ".join(tech_stack[:5])}')
        if description:
            parts.append(description)
        summary = ' '.join(parts).strip()
        if summary:
            summaries.append(summary)
    return summaries


def _recent_tech_stack(candidate_profile: dict[str, Any]) -> list[str]:
    stacks: list[str] = []
    for entry in (candidate_profile.get('experience_items') or [])[:3]:
        if not isinstance(entry, dict):
            continue
        stacks.extend(_clean_text(value) for value in (entry.get('tech_stack') or []))
    for entry in (candidate_profile.get('project_items') or [])[:2]:
        if not isinstance(entry, dict):
            continue
        stacks.extend(_clean_text(value) for value in (entry.get('tech_stack') or []))
    return _dedupe_strings([canonicalize_skill_label(value) for value in stacks if _clean_text(value)])


def _role_relevant_skills(candidate_profile: dict[str, Any], role_profile: dict[str, Any]) -> tuple[list[str], list[str]]:
    exact_candidate_skills = _dedupe_strings(candidate_profile.get('exact_candidate_skills') or candidate_profile.get('normalized_candidate_skills') or [])
    scored_skills: list[tuple[float, str, str]] = []
    for skill in exact_candidate_skills:
        score, reason = _score_embedding_skill(skill, role_profile, candidate_profile)
        scored_skills.append((score, skill, reason))

    scored_skills.sort(key=lambda item: (-item[0], item[1]))
    selected = [skill for score, skill, _reason in scored_skills if score > -0.15][:12]
    if not selected:
        selected = exact_candidate_skills[:12]
    omitted = [skill for skill in exact_candidate_skills if skill not in selected]
    return selected, omitted[:12]


def _build_structured_embedding_text(
    *,
    title: str,
    headline: str,
    summary: str,
    core_skills: list[str],
    recent_roles: list[str],
    recent_stack: list[str],
    location: str,
) -> tuple[str, list[str]]:
    sections_used: list[str] = []
    parts: list[str] = []

    if title:
        parts.append(f'Title: {title}')
        sections_used.append('title')
    if headline and headline.casefold() != title.casefold():
        parts.append(f'Headline: {headline}')
        sections_used.append('headline')
    if summary:
        parts.append(f'Summary: {_short_text(summary, max_words=24)}')
        sections_used.append('summary')
    if core_skills:
        parts.append(f'Core Skills: {", ".join(core_skills[:12])}')
        sections_used.append('core_skills')
    if recent_roles:
        parts.append('Recent Roles:')
        parts.extend(f'- {item}' for item in recent_roles[:3])
        sections_used.append('recent_roles')
    if recent_stack:
        parts.append(f'Recent Stack: {", ".join(recent_stack[:10])}')
        sections_used.append('recent_stack')
    if location:
        parts.append(f'Location: {location}')
        sections_used.append('location')

    return '\n'.join(parts).strip(), sections_used


def _score_embedding_skill(skill: str, role_profile: dict[str, Any], candidate_profile: dict[str, Any]) -> tuple[float, str]:
    canonical_skill = canonical_skill_name(skill) or skill
    role_targets = _dedupe_strings([
        *(role_profile.get('exact_required_skills') or role_profile.get('normalized_required_skills') or []),
        *(role_profile.get('normalized_preferred_skills') or []),
        *(role_profile.get('role_supporting_skill_inference') or []),
    ])

    best = 0.0
    reason = 'candidate_skill'
    for target in role_targets:
        evidence = best_skill_evidence(target, [canonical_skill])
        if float(evidence.get('score') or 0.0) > best:
            best = float(evidence.get('score') or 0.0)
            reason = f"target:{canonicalize_skill_label(target)}:{evidence.get('match_type', 'none')}"

    recent_stack = {canonical_skill_name(value) or value for value in _recent_tech_stack(candidate_profile)}
    if canonical_skill in recent_stack:
        best += 0.08
        reason = f'{reason}:recent_stack'
    if canonical_skill in LOW_PRIORITY_EMBEDDING_SKILLS:
        best -= 0.2
    return best, reason


def build_role_aware_candidate_embedding_payload(candidate_profile: dict[str, Any], role_profile: dict[str, Any]) -> dict[str, Any]:
    selected_embedding_skills, omitted_embedding_skills = _role_relevant_skills(candidate_profile, role_profile)
    recent_roles = _recent_role_summaries(candidate_profile.get('experience_items') or [])
    recent_stack = _recent_tech_stack(candidate_profile)
    recent_stack_selected = [skill for skill in recent_stack if skill in selected_embedding_skills][:8]
    if not recent_stack_selected:
        recent_stack_selected = recent_stack[:8]

    embedding_text, sections_used = _build_structured_embedding_text(
        title=_clean_text(candidate_profile.get('title')),
        headline=_clean_text(candidate_profile.get('headline')),
        summary=_clean_text(candidate_profile.get('summary')),
        core_skills=selected_embedding_skills,
        recent_roles=recent_roles,
        recent_stack=recent_stack_selected,
        location=_clean_text(candidate_profile.get('location')),
    )

    return {
        'embedding_text': embedding_text,
        'embedding_text_token_count': _token_count(embedding_text),
        'selected_embedding_skills': selected_embedding_skills,
        'omitted_embedding_skills': omitted_embedding_skills[:12],
        'embedding_text_builder_version': EMBEDDING_TEXT_BUILDER_VERSION,
        'candidate_embedding_sections_used': sections_used,
    }


def build_candidate_profile(
    *,
    candidate: User,
    resume: CandidateResume | None,
    latest_interview: Interview | None = None,
) -> dict[str, Any]:
    serializer = ResumeProcessingService()
    resume_data = serializer.serialize_resume(resume)
    section_lines = _resume_section_lines(resume)
    skills = _extract_resume_skills(resume_data, section_lines=section_lines)
    experience_lines = experience_lines_from_resume_data(resume_data)
    project_lines = project_lines_from_resume_data(resume_data)
    education_lines = _flatten_nested_items(resume_data.get('education'))
    raw_text_preview = _clean_text(resume_data.get('raw_text_preview'))

    title = _clean_text(resume.current_title if resume else '') or _clean_text(resume_data.get('headline')) or _clean_text(latest_interview.role.role if latest_interview and latest_interview.role else '')
    headline = _clean_text(resume.headline if resume else '') or _clean_text(resume_data.get('headline'))
    summary = _clean_text(resume.summary if resume else '') or _clean_text(resume_data.get('summary'))
    location = _clean_text(resume.location if resume else '') or _clean_text((resume_data.get('contact') or {}).get('location'))
    experience_years_value = resume.total_experience_years if resume and resume.total_experience_years is not None else None
    if experience_years_value is None:
        months = int(resume_data.get('total_professional_experience_months') or 0)
        experience_years_value = (Decimal(months) / Decimal('12')) if months else Decimal('0')

    normalized_skill_tokens: set[str] = set()
    for skill in skills:
        normalized_skill_tokens.update(extract_skill_tokens(skill))
    for value in [summary, headline, raw_text_preview, *experience_lines, *project_lines, *section_lines]:
        normalized_skill_tokens.update(extract_skill_tokens(value))
    normalized_candidate_skills = canonical_display_list_from_tokens(normalized_skill_tokens)
    candidate_related_skill_evidence = build_related_skill_evidence(normalized_candidate_skills)
    family_data = infer_candidate_families(
        title=title,
        skills=normalized_candidate_skills,
        summary=' '.join(filter(None, [headline, summary, raw_text_preview])),
    )

    recent_roles = _recent_role_summaries(resume_data.get('experience') or [])
    recent_stack = _recent_tech_stack({
        'experience_items': resume_data.get('experience') or [],
        'project_items': resume_data.get('projects') or [],
    })
    embedding_text, candidate_embedding_sections_used = _build_structured_embedding_text(
        title=title,
        headline=headline,
        summary=summary,
        core_skills=normalized_candidate_skills[:12],
        recent_roles=recent_roles,
        recent_stack=recent_stack[:10],
        location=location,
    )

    return {
        'candidate_id': candidate.id,
        'user_id': candidate.id,
        'name': _candidate_name(candidate),
        'email': candidate.email,
        'title': title,
        'experience_years': float(experience_years_value or 0),
        'skills': skills,
        'exact_candidate_skills': normalized_candidate_skills,
        'normalized_candidate_skills': normalized_candidate_skills,
        'candidate_related_skill_evidence': candidate_related_skill_evidence,
        'candidate_primary_family': family_data.get('candidate_primary_family', ''),
        'candidate_secondary_families': family_data.get('candidate_secondary_families', []),
        'location': location,
        'current_company': _clean_text(resume.current_company if resume else ''),
        'headline': headline,
        'summary': summary,
        'embedding_text': embedding_text,
        'embedding_text_token_count': _token_count(embedding_text),
        'embedding_text_builder_version': EMBEDDING_TEXT_BUILDER_VERSION,
        'candidate_embedding_sections_used': candidate_embedding_sections_used,
        'raw_text_preview': raw_text_preview,
        'resume_section_lines': section_lines,
        'experience_items': resume_data.get('experience') or [],
        'project_items': resume_data.get('projects') or [],
        'education_items': resume_data.get('education') or [],
        'resume_id': resume.id if resume else None,
        'resume_status': _clean_text(resume.status if resume else ''),
        'latest_role_id': latest_interview.role_id if latest_interview else None,
        'latest_role': _clean_text(latest_interview.role.role if latest_interview and latest_interview.role else ''),
        'latest_interview_id': latest_interview.id if latest_interview else None,
        'latest_interview_date': latest_interview.date.isoformat() if latest_interview and latest_interview.date else '',
        'latest_pipeline_status': _clean_text(latest_interview.status if latest_interview else ''),
        'recruiter_name': (
            f'{latest_interview.recruiter.first_name} {latest_interview.recruiter.last_name}'.strip().title()
            if latest_interview and latest_interview.recruiter else 'Unassigned'
        ),
    }
