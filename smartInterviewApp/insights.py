from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db import close_old_connections
from django.utils import timezone

from smartInterviewApp.models import CandidateInsightSnapshot, CandidateResume, Interview, UserProfile
from smartInterviewApp.services.resume_ai import detect_resume_type, detect_role_family, score_resume


CONFIDENCE_VALUES = {'low', 'medium', 'high'}
GENERIC_ROLE_TOKENS = {
    'engineer', 'developer', 'manager', 'executive', 'specialist', 'consultant',
    'lead', 'senior', 'junior', 'associate', 'role', 'job', 'opening',
}
KNOWN_ROLE_REQUIREMENT_TERMS = (
    'Python', 'Django', 'Django REST Framework', 'REST API', 'Flask', 'FastAPI',
    'JavaScript', 'TypeScript', 'React', 'Angular', 'Vue', 'Node', 'Express',
    'SQL', 'MySQL', 'PostgreSQL', 'MongoDB', 'Redis', 'AWS', 'Azure', 'GCP',
    'Docker', 'Kubernetes', 'CI/CD', 'Git', 'Linux', 'HTML', 'CSS',
    'Machine Learning', 'Data Analysis', 'Power BI', 'Tableau', 'Excel',
    'Sourcing', 'Screening', 'ATS', 'Interview Coordination', 'CRM',
    'Client Handling', 'Lead Generation', 'Accounting', 'GST', 'Reporting',
    'Figma', 'Wireframes', 'Product Analytics', 'Stakeholder Management',
)


def _clean_text(value: Any, limit: int | None = None) -> str:
    text = html.unescape(str(value or '')).replace('\xa0', ' ')
    text = re.sub(r'<[^>]*>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.strip(' \t\r\n\'"`<>|:;-–—•·,')
    if limit and len(text) > limit:
        return f'{text[:limit].rstrip()}...'
    return text


def _normalize_text(value: Any) -> str:
    return re.sub(r'[^a-z0-9+#.]+', ' ', str(value or '').lower()).strip()


def _tokenize(value: Any) -> set[str]:
    return {token for token in re.findall(r'[a-z0-9+#.]+', str(value or '').lower()) if len(token) > 1}


def _dedupe_strings(values: list[Any], *, limit: int = 12, item_limit: int = 120) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value, item_limit)
        key = _normalize_text(text)
        if not text or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if len(deduped) >= limit:
            break
    return deduped


def _safe_list(value: Any, *, limit: int = 12, item_limit: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_strings(value, limit=limit, item_limit=item_limit)


def _safe_confidence(value: Any, fallback: str = 'low') -> str:
    normalized = _clean_text(value, 20).lower()
    return normalized if normalized in CONFIDENCE_VALUES else fallback


def _clamp_score(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def _iter_nested_strings(value: Any):
    if isinstance(value, str):
        clean = _clean_text(value)
        if clean:
            yield clean
    elif isinstance(value, list):
        for item in value:
            yield from _iter_nested_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_nested_strings(item)


def _resume_payload_for_scoring(user: User, profile: UserProfile, resume: CandidateResume | None) -> dict[str, Any]:
    if not resume or not isinstance(resume.structured_data, dict) or not resume.structured_data:
        return {}

    structured = resume.structured_data
    contact = structured.get('contact') if isinstance(structured.get('contact'), dict) else {}
    links = contact.get('links') if isinstance(contact.get('links'), list) else []
    link_text = ' '.join(str(item) for item in links)
    payload = {
        'basics': {
            'name': contact.get('name') or f'{user.first_name} {user.last_name}'.strip() or user.username,
            'email': contact.get('email') or resume.email or user.email,
            'phone': contact.get('phone') or resume.phone or profile.phone,
            'location': contact.get('location') or resume.location,
            'headline': resume.headline or structured.get('headline', ''),
            'summary': resume.summary or structured.get('summary', ''),
            'website': contact.get('website') or ('portfolio' if 'portfolio' in link_text.lower() else ''),
            'linkedin': contact.get('linkedin') or ('linkedin' if 'linkedin.com' in link_text.lower() else ''),
            'github': contact.get('github') or ('github' if 'github.com' in link_text.lower() else ''),
            'portfolio': contact.get('portfolio') or ('portfolio' if 'portfolio' in link_text.lower() else ''),
        },
        'skills': structured.get('skills') if isinstance(structured.get('skills'), list) else [],
        'experience': structured.get('experience') if isinstance(structured.get('experience'), list) else [],
        'projects': structured.get('projects') if isinstance(structured.get('projects'), list) else [],
        'education': structured.get('education') if isinstance(structured.get('education'), list) else [],
        'certifications': structured.get('certifications') if isinstance(structured.get('certifications'), list) else [],
        'achievements': structured.get('achievements') if isinstance(structured.get('achievements'), list) else [],
    }
    return payload


def _deterministic_resume_score(user: User, profile: UserProfile, resume: CandidateResume | None) -> tuple[int | None, str, str, dict[str, Any]]:
    payload = _resume_payload_for_scoring(user, profile, resume)
    if not payload:
        return None, 'general', 'incomplete', {}
    role_family = detect_role_family(payload)
    resume_type = detect_resume_type(payload, role_family)
    return score_resume(payload, role_family=role_family, resume_type=resume_type), role_family, resume_type, payload


def _extract_resume_skills(resume: CandidateResume | None) -> list[str]:
    if not resume:
        return []
    structured = resume.structured_data if isinstance(resume.structured_data, dict) else {}
    candidates: list[Any] = []
    candidates.extend(structured.get('skills') if isinstance(structured.get('skills'), list) else [])

    technical_expertise = structured.get('technical_expertise')
    if isinstance(technical_expertise, dict):
        for value in technical_expertise.values():
            candidates.extend(list(_iter_nested_strings(value)))

    for section_key in ('experience', 'projects'):
        for item in structured.get(section_key, []) if isinstance(structured.get(section_key), list) else []:
            if not isinstance(item, dict):
                continue
            candidates.extend(item.get('tech_stack') if isinstance(item.get('tech_stack'), list) else [])

    try:
        for section in resume.sections.all():
            section_key = str(section.section_key or '').lower()
            if 'skill' in section_key or 'technical' in section_key or 'expertise' in section_key:
                candidates.extend(_iter_nested_strings(section.content))
                candidates.extend(_iter_nested_strings(section.raw_text))
    except Exception:
        pass

    split_candidates: list[str] = []
    for candidate in candidates:
        for part in re.split(r'[,;|/\n]+', str(candidate or '')):
            split_candidates.append(part)
    return _dedupe_strings(split_candidates, limit=40, item_limit=80)


def _resume_evidence_text(resume: CandidateResume | None) -> str:
    if not resume:
        return ''
    structured = resume.structured_data if isinstance(resume.structured_data, dict) else {}
    parts = [
        resume.headline,
        resume.summary,
        resume.current_title,
        resume.current_company,
        resume.location,
        ' '.join(_extract_resume_skills(resume)),
    ]
    for key in ('experience', 'projects', 'education', 'certifications', 'achievements'):
        values = structured.get(key) if isinstance(structured.get(key), list) else []
        for item in values[:6]:
            parts.extend(list(_iter_nested_strings(item)))
    return ' '.join(_clean_text(part) for part in parts if _clean_text(part))


def _extract_vacancy_requirements(vacancy, candidate_skills: list[str]) -> list[str]:
    if not vacancy:
        return []
    clean_description = _clean_text(vacancy.description)
    vacancy_text = ' '.join([
        vacancy.role or '',
        vacancy.position or '',
        clean_description,
        vacancy.experience_required or '',
        vacancy.location or '',
        vacancy.job_type or '',
    ])
    normalized_vacancy = _normalize_text(vacancy_text)
    candidates: list[str] = []
    for term in KNOWN_ROLE_REQUIREMENT_TERMS:
        if _normalize_text(term) in normalized_vacancy:
            candidates.append(term)
    for skill in candidate_skills:
        if not _is_valid_requirement_fragment(skill):
            continue
        normalized_skill = _normalize_text(skill)
        if len(normalized_skill) >= 3 and normalized_skill in normalized_vacancy:
            candidates.append(skill)
    for fragment in re.split(r'[\n,;|•]+', clean_description):
        clean = _clean_text(fragment, 80)
        if not _is_valid_requirement_fragment(clean):
            continue
        candidates.append(clean)
    return _dedupe_strings(candidates, limit=14, item_limit=90)


def _term_matches(candidate_skill: str, requirement: str) -> bool:
    skill_norm = _normalize_text(candidate_skill)
    requirement_norm = _normalize_text(requirement)
    if not skill_norm or not requirement_norm:
        return False
    if skill_norm == requirement_norm:
        return True
    if len(skill_norm) >= 5 and skill_norm in requirement_norm:
        return True
    if len(requirement_norm) >= 5 and requirement_norm in skill_norm:
        return True
    skill_tokens = _tokenize(skill_norm)
    requirement_tokens = _tokenize(requirement_norm)
    return bool(skill_tokens and requirement_tokens and skill_tokens & requirement_tokens and (skill_tokens <= requirement_tokens or requirement_tokens <= skill_tokens))


def _parse_years(value: Any) -> float | None:
    numbers = re.findall(r'\d+(?:\.\d+)?', str(value or ''))
    if not numbers:
        return None
    try:
        return float(numbers[0])
    except ValueError:
        return None


def _is_valid_requirement_fragment(text: str) -> bool:
    raw = str(text or '').strip()
    raw_lower = raw.lower()
    if '<' in raw or '>' in raw or '&nbsp' in raw_lower:
        return False
    if raw and (raw[0] in {'"', "'", '`', '<', '>', '=', '/', '\\'} or raw[-1] in {'"', "'", '`', '<', '>', '=', '/', '\\'}):
        return False

    cleaned = _clean_text(text)
    if not cleaned:
        return False
    lowered = cleaned.lower().strip(' .:-')
    generic_labels = {
        'skill',
        'skills',
        'experience',
        'required',
        'requirement',
        'requirements',
        'qualification',
        'qualifications',
        'excellent',
        'proficient',
        'knowledge',
        'candidate',
        'job',
        'role',
        'tool',
        'tools',
        'other',
        'test',
    }
    if lowered in generic_labels:
        return False
    if len(cleaned) < 3:
        return False
    if len(cleaned.split()) > 6:
        return False
    punctuation_count = sum(1 for char in cleaned if not char.isalnum() and not char.isspace())
    if punctuation_count >= max(2, len(cleaned) // 2):
        return False
    return True


def _build_role_fit_signal(resume: CandidateResume | None, interview: Interview | None) -> dict[str, Any]:
    vacancy = getattr(interview, 'role', None) if interview else None
    if not vacancy:
        return {
            'score': None,
            'confidence': 'low',
            'summary': 'Role-fit insight needs an assigned vacancy before a match can be calculated.',
            'matched': [],
            'missing': ['Assigned vacancy'],
            'evidence': [],
        }

    candidate_skills = _extract_resume_skills(resume)
    resume_text = _resume_evidence_text(resume)
    if not candidate_skills and not resume_text:
        return {
            'score': None,
            'confidence': 'low',
            'summary': 'Role-fit insight needs a processed resume with skills or experience evidence.',
            'matched': [],
            'missing': _extract_vacancy_requirements(vacancy, [])[:6] or ['Parsed resume skills'],
            'evidence': [_clean_text(f'Assigned vacancy: {vacancy.role}', 120)],
        }

    requirements = _extract_vacancy_requirements(vacancy, candidate_skills)
    matched = [
        requirement for requirement in requirements
        if any(_term_matches(skill, requirement) for skill in candidate_skills)
    ]
    missing = [requirement for requirement in requirements if requirement not in matched]

    resume_tokens = _tokenize(resume_text)
    role_tokens = _tokenize(f'{vacancy.role} {vacancy.position}')
    title_overlap = sorted(role_tokens & resume_tokens)
    if title_overlap and not any('Role/title overlap' in item for item in matched):
        matched.append(f"Role/title overlap: {', '.join(title_overlap[:4])}")

    required_years = _parse_years(vacancy.experience_required)
    candidate_years = float(resume.total_experience_years) if resume and resume.total_experience_years is not None else None
    if required_years is not None:
        if candidate_years is not None and candidate_years >= required_years:
            matched.append(f'Experience requirement: {candidate_years:g}+ years available')
        else:
            missing.append(f'Experience requirement: {vacancy.experience_required}')

    matched = _dedupe_strings(matched, limit=8)
    missing = _dedupe_strings(missing, limit=8)
    requirement_count = max(1, len(requirements) + (1 if required_years is not None else 0))
    match_ratio = min(1, len([item for item in matched if not item.startswith('Role/title overlap')]) / requirement_count)
    title_bonus = min(12, len(title_overlap) * 3)
    score = _clamp_score(22 + (match_ratio * 64) + title_bonus)
    if requirements and not matched:
        score = min(score or 0, 35)

    confidence = 'low'
    if len(requirements) >= 4 and len(candidate_skills) >= 5:
        confidence = 'high' if match_ratio >= 0.45 else 'medium'
    elif len(requirements) >= 2 and candidate_skills:
        confidence = 'medium'

    evidence = []
    if candidate_skills:
        evidence.append(f"Parsed candidate skills: {', '.join(candidate_skills[:8])}")
    if requirements:
        evidence.append(f"Vacancy signals compared: {', '.join(requirements[:8])}")
    if title_overlap:
        evidence.append(f"Resume text overlaps role terms: {', '.join(title_overlap[:5])}")
    if vacancy.experience_required:
        evidence.append(f"Vacancy experience requirement: {vacancy.experience_required}")

    return {
        'score': score,
        'confidence': confidence,
        'summary': _clean_text(
            f"Role fit is based on matched resume skills against the assigned {vacancy.role} vacancy.",
            220,
        ),
        'matched': matched,
        'missing': missing,
        'evidence': _dedupe_strings(evidence, limit=6, item_limit=180),
    }


def score_candidate_vacancy_match(resume: CandidateResume | None, vacancy) -> dict[str, Any]:
    if not vacancy:
        return {
            'match_score': 0,
            'is_recommended': False,
            'match_confidence': 'low',
            'matched_requirements': [],
            'missing_requirements': ['Open vacancy'],
            'match_reason': 'A vacancy is required before matching can be calculated.',
        }

    if not resume or resume.status != CandidateResume.ParseStatus.COMPLETED:
        return {
            'match_score': 0,
            'is_recommended': False,
            'match_confidence': 'low',
            'matched_requirements': [],
            'missing_requirements': ['Completed parsed resume'],
            'match_reason': 'Recommended roles need a completed parsed resume before matching.',
        }

    candidate_skills = _extract_resume_skills(resume)
    resume_text = _resume_evidence_text(resume)
    if not candidate_skills and not resume_text:
        return {
            'match_score': 0,
            'is_recommended': False,
            'match_confidence': 'low',
            'matched_requirements': [],
            'missing_requirements': ['Parsed resume skills or experience evidence'],
            'match_reason': 'No parsed resume skills or experience evidence were available for matching.',
        }

    requirements = _extract_vacancy_requirements(vacancy, candidate_skills)
    matched_skill_requirements = [
        requirement for requirement in requirements
        if any(_term_matches(skill, requirement) for skill in candidate_skills)
    ]
    matched = list(matched_skill_requirements)
    missing = [requirement for requirement in requirements if requirement not in matched_skill_requirements]
    resume_tokens = _tokenize(resume_text)
    role_tokens = _tokenize(f'{vacancy.role} {vacancy.position}') - GENERIC_ROLE_TOKENS
    title_overlap = sorted(role_tokens & resume_tokens)

    required_years = _parse_years(vacancy.experience_required)
    candidate_years = float(resume.total_experience_years) if resume.total_experience_years is not None else None
    if required_years is not None:
        if candidate_years is not None and candidate_years >= required_years:
            matched.append(f'Experience requirement: {candidate_years:g}+ years available')
        else:
            missing.append(f'Experience requirement: {vacancy.experience_required}')

    evidence_matches = _dedupe_strings(matched, limit=8)
    skill_evidence_matches = _dedupe_strings(matched_skill_requirements, limit=8)
    missing = _dedupe_strings(missing, limit=8)
    requirement_count = max(1, len(requirements))
    match_ratio = min(1, len(skill_evidence_matches) / requirement_count)
    title_bonus = min(8, len(title_overlap) * 2) if evidence_matches else 0
    experience_bonus = 6 if any(item.startswith('Experience requirement:') for item in evidence_matches) and skill_evidence_matches else 0
    match_score = _clamp_score(18 + (match_ratio * 70) + title_bonus + experience_bonus) or 0
    if requirements and not skill_evidence_matches:
        match_score = min(match_score, 30)

    confidence = 'low'
    if len(requirements) >= 4 and len(candidate_skills) >= 5:
        confidence = 'high' if match_ratio >= 0.5 else 'medium' if skill_evidence_matches else 'low'
    elif len(requirements) >= 2 and skill_evidence_matches:
        confidence = 'medium'

    is_recommended = match_score >= 50 and bool(skill_evidence_matches) and (bool(title_overlap) or match_ratio >= 0.5)
    if is_recommended:
        reason = f"Matched {len(evidence_matches)} vacancy requirement{'s' if len(evidence_matches) != 1 else ''}: {', '.join(evidence_matches[:3])}."
    elif evidence_matches:
        reason = f"Some overlap found, but the match score is below the recommendation threshold: {', '.join(evidence_matches[:3])}."
    else:
        reason = 'No strong requirement overlap was found between the parsed resume and this vacancy.'

    return {
        'match_score': match_score,
        'is_recommended': is_recommended,
        'match_confidence': confidence,
        'matched_requirements': evidence_matches,
        'missing_requirements': missing,
        'match_reason': _clean_text(reason, 240),
    }


def _build_profile_strength_signal(user: User, profile: UserProfile, resume: CandidateResume | None, resume_score_value: int | None, role_family: str, resume_type: str, resume_payload: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    evidence: list[str] = []
    if not user.email:
        missing.append('Email address')
    else:
        evidence.append('Profile includes email contact.')
    if not profile.phone:
        missing.append('Phone number')
    else:
        evidence.append('Profile includes phone contact.')
    if not resume:
        missing.append('Uploaded resume')
    elif resume.status != CandidateResume.ParseStatus.COMPLETED:
        missing.append('Completed resume parsing')

    basics = resume_payload.get('basics') if isinstance(resume_payload.get('basics'), dict) else {}
    skills = resume_payload.get('skills') if isinstance(resume_payload.get('skills'), list) else []
    experience = resume_payload.get('experience') if isinstance(resume_payload.get('experience'), list) else []
    education = resume_payload.get('education') if isinstance(resume_payload.get('education'), list) else []
    projects = resume_payload.get('projects') if isinstance(resume_payload.get('projects'), list) else []

    if resume_score_value is not None:
        evidence.append(f'Deterministic resume score: {resume_score_value}/100.')
    if basics.get('headline'):
        evidence.append('Resume includes a headline.')
    else:
        missing.append('Resume headline')
    if basics.get('summary'):
        evidence.append('Resume includes a professional summary.')
    else:
        missing.append('Professional summary')
    if skills:
        evidence.append(f'Parsed skills count: {len(skills)}.')
    else:
        missing.append('Parsed skills')
    if experience:
        evidence.append(f'Experience entries: {len(experience)}.')
    elif projects:
        evidence.append(f'Project entries: {len(projects)}.')
    else:
        missing.append('Experience or project evidence')
    if not education:
        missing.append('Education details')

    confidence = 'low'
    if resume_score_value is not None:
        confidence = 'high' if resume_score_value >= 70 and len(missing) <= 2 else 'medium' if resume_score_value >= 45 else 'low'

    summary = 'Profile strength is based on parsed resume completeness, profile contact data, and evidence quality.'
    if resume_score_value is not None:
        summary = f'Profile strength uses a deterministic resume score of {resume_score_value}/100 for a {resume_type.replace("_", " ")} {role_family.replace("_", " ")} profile.'

    return {
        'summary': summary,
        'evidence': _dedupe_strings(evidence, limit=8, item_limit=160),
        'missing_items': _dedupe_strings(missing, limit=10, item_limit=100),
        'confidence': confidence,
    }


def _build_data_quality_flags(profile: UserProfile, resume: CandidateResume | None, interview: Interview | None, role_fit_signal: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if not profile.phone:
        flags.append('missing_profile_phone')
    if not resume:
        flags.append('missing_resume')
    elif resume.status != CandidateResume.ParseStatus.COMPLETED:
        flags.append('resume_not_processed')
    elif not isinstance(resume.structured_data, dict) or not resume.structured_data:
        flags.append('missing_structured_resume_data')
    if not getattr(interview, 'role', None):
        flags.append('missing_assigned_vacancy')
    else:
        vacancy = interview.role
        if len(vacancy.description or '') < 80:
            flags.append('limited_vacancy_description')
        if not vacancy.experience_required:
            flags.append('missing_vacancy_experience_requirement')
    if not role_fit_signal.get('evidence'):
        flags.append('limited_role_fit_evidence')
    return _dedupe_strings(flags, limit=12, item_limit=80)


class CandidateInsightService:
    endpoint = 'https://api.openai.com/v1/responses'

    def __init__(self) -> None:
        self.api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
        self.model = getattr(settings, 'OPENAI_INSIGHTS_MODEL', '').strip() or getattr(settings, 'OPENAI_RESUME_MODEL', 'gpt-4.1-mini').strip()

    def get_snapshot(self, user: User) -> CandidateInsightSnapshot:
        snapshot, _ = CandidateInsightSnapshot.objects.get_or_create(candidate=user)
        return snapshot

    def build_signature(self, user: User, profile: UserProfile, resume: CandidateResume | None, interview: Interview | None) -> str:
        vacancy = interview.role if interview and interview.role else None
        vacancy_payload = {
            'role': vacancy.role if vacancy else '',
            'position': vacancy.position if vacancy else '',
            'description': vacancy.description if vacancy else '',
            'experience_required': vacancy.experience_required if vacancy else '',
            'location': vacancy.location if vacancy else '',
            'job_type': vacancy.job_type if vacancy else '',
            'salary_range': vacancy.salary_range if vacancy else '',
            'status': vacancy.status if vacancy else '',
        }
        vacancy_signature = hashlib.sha256(
            json.dumps(vacancy_payload, sort_keys=True).encode('utf-8')
        ).hexdigest()
        signature_payload = {
            'user_id': user.id,
            'name': f'{user.first_name} {user.last_name}'.strip(),
            'email': user.email,
            'phone': profile.phone or '',
            'gender': profile.gender or '',
            'resume_id': resume.id if resume else None,
            'resume_updated_at': resume.updated_at.isoformat() if resume and resume.updated_at else '',
            'resume_status': resume.status if resume else '',
            'resume_headline': resume.headline if resume else '',
            'role_id': interview.role_id if interview else None,
            'role': interview.role.role if interview and interview.role else '',
            'vacancy_signature': vacancy_signature,
            'interview_count': user.candidate_interviews.count(),
        }
        raw = json.dumps(signature_payload, sort_keys=True).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def mark_stale(self, user: User) -> CandidateInsightSnapshot:
        snapshot = self.get_snapshot(user)
        snapshot.status = CandidateInsightSnapshot.Status.PENDING
        snapshot.error_message = ''
        snapshot.save(update_fields=['status', 'error_message', 'updated_at'])
        return snapshot

    def should_generate(self, snapshot: CandidateInsightSnapshot, signature: str) -> bool:
        return snapshot.status in {
            CandidateInsightSnapshot.Status.NOT_STARTED,
            CandidateInsightSnapshot.Status.PENDING,
            CandidateInsightSnapshot.Status.FAILED,
        } or snapshot.source_signature != signature

    def trigger_generation(self, user: User, profile: UserProfile, resume: CandidateResume | None, interview: Interview | None) -> CandidateInsightSnapshot:
        snapshot = self.get_snapshot(user)
        signature = self.build_signature(user, profile, resume, interview)
        if snapshot.status == CandidateInsightSnapshot.Status.PROCESSING and snapshot.source_signature == signature:
            return snapshot
        if not self.should_generate(snapshot, signature):
            return snapshot

        snapshot.status = CandidateInsightSnapshot.Status.PROCESSING
        snapshot.error_message = ''
        snapshot.source_signature = signature
        snapshot.requested_at = timezone.now()
        snapshot.generated_for_role = interview.role.role if interview and interview.role else ''
        snapshot.generated_for_title = resume.current_title if resume else ''
        snapshot.model_name = self.model
        snapshot.save(update_fields=[
            'status', 'error_message', 'source_signature', 'requested_at',
            'generated_for_role', 'generated_for_title', 'model_name', 'updated_at',
        ])

        worker = threading.Thread(
            target=self._run_generation,
            args=(user.id, signature),
            daemon=True,
            name=f'candidate-insights-{user.id}',
        )
        worker.start()
        return snapshot

    def serialize_snapshot(self, snapshot: CandidateInsightSnapshot | None) -> dict[str, Any]:
        if not snapshot:
            return {
                'status': CandidateInsightSnapshot.Status.NOT_STARTED,
                'loading': False,
                'available': False,
                'error_message': '',
                'executive_summary': '',
                'profile_strength_summary': '',
                'profile_strength_evidence': [],
                'profile_strength_missing_items': [],
                'profile_strength_confidence': '',
                'role_fit_summary': '',
                'role_fit_confidence': '',
                'role_fit_evidence': [],
                'role_fit_matched_requirements': [],
                'role_fit_missing_requirements': [],
                'data_quality_flags': [],
                'resume_score': None,
                'role_fit_score': None,
                'market_demand_score': None,
                'current_skills_impact_score': None,
                'market_demand_label': '',
                'salary_range': '',
                'salary_trend_summary': '',
                'market_demand_summary': '',
                'current_skills_impact_summary': '',
                'top_strengths': [],
                'growth_areas': [],
                'recommended_skills': [],
                'recommended_roles': [],
                'generated_at': '',
                'model_name': '',
            }

        payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
        profile_strength_summary = getattr(snapshot, 'profile_strength_summary', '') or payload.get('profile_strength_summary') or ''
        role_fit_summary = getattr(snapshot, 'role_fit_summary', '') or payload.get('role_fit_summary') or ''

        return {
            'status': snapshot.status,
            'loading': snapshot.status in {CandidateInsightSnapshot.Status.PENDING, CandidateInsightSnapshot.Status.PROCESSING},
            'available': snapshot.status == CandidateInsightSnapshot.Status.COMPLETED,
            'error_message': snapshot.error_message,
            'executive_summary': snapshot.executive_summary or profile_strength_summary,
            'profile_strength_summary': profile_strength_summary,
            'profile_strength_evidence': _safe_list(getattr(snapshot, 'profile_strength_evidence', []) or payload.get('profile_strength_evidence'), limit=10),
            'profile_strength_missing_items': _safe_list(getattr(snapshot, 'profile_strength_missing_items', []) or payload.get('profile_strength_missing_items'), limit=10),
            'profile_strength_confidence': _safe_confidence(getattr(snapshot, 'profile_strength_confidence', '') or payload.get('profile_strength_confidence'), ''),
            'role_fit_summary': role_fit_summary,
            'role_fit_confidence': _safe_confidence(getattr(snapshot, 'role_fit_confidence', '') or payload.get('role_fit_confidence'), ''),
            'role_fit_evidence': _safe_list(getattr(snapshot, 'role_fit_evidence', []) or payload.get('role_fit_evidence'), limit=10),
            'role_fit_matched_requirements': _safe_list(getattr(snapshot, 'role_fit_matched_requirements', []) or payload.get('role_fit_matched_requirements'), limit=10),
            'role_fit_missing_requirements': _safe_list(getattr(snapshot, 'role_fit_missing_requirements', []) or payload.get('role_fit_missing_requirements'), limit=10),
            'data_quality_flags': _safe_list(getattr(snapshot, 'data_quality_flags', []) or payload.get('data_quality_flags'), limit=12),
            'resume_score': snapshot.resume_score,
            'role_fit_score': snapshot.role_fit_score,
            'market_demand_score': snapshot.market_demand_score,
            'current_skills_impact_score': snapshot.current_skills_impact_score,
            'market_demand_label': snapshot.market_demand_label,
            'salary_range': snapshot.salary_range,
            'salary_trend_summary': snapshot.salary_trend_summary,
            'market_demand_summary': snapshot.market_demand_summary,
            'current_skills_impact_summary': snapshot.current_skills_impact_summary,
            'top_strengths': snapshot.top_strengths or [],
            'growth_areas': snapshot.growth_areas or [],
            'recommended_skills': snapshot.recommended_skills or [],
            'recommended_roles': snapshot.recommended_roles or [],
            'generated_at': snapshot.generated_at.isoformat() if snapshot.generated_at else '',
            'model_name': snapshot.model_name,
        }

    def _run_generation(self, user_id: int, signature: str) -> None:
        close_old_connections()
        try:
            user = User.objects.select_related('profile').get(id=user_id)
            profile = user.profile
            resume = CandidateResume.objects.filter(candidate=user, is_active=True).prefetch_related('sections').first()
            interview = Interview.objects.select_related('role').filter(candidate=user).order_by('-date', '-id').first()
            snapshot = self.get_snapshot(user)
            if snapshot.source_signature != signature:
                return

            payload = self._generate_payload(user, profile, resume, interview)
            snapshot.status = CandidateInsightSnapshot.Status.COMPLETED
            snapshot.error_message = ''
            snapshot.profile_strength_summary = payload.get('profile_strength_summary', '')
            snapshot.profile_strength_evidence = _safe_list(payload.get('profile_strength_evidence'), limit=10)
            snapshot.profile_strength_missing_items = _safe_list(payload.get('profile_strength_missing_items'), limit=10)
            snapshot.profile_strength_confidence = _safe_confidence(payload.get('profile_strength_confidence'), 'low')
            snapshot.role_fit_summary = payload.get('role_fit_summary', '')
            snapshot.role_fit_confidence = _safe_confidence(payload.get('role_fit_confidence'), 'low')
            snapshot.role_fit_evidence = _safe_list(payload.get('role_fit_evidence'), limit=10)
            snapshot.role_fit_matched_requirements = _safe_list(payload.get('role_fit_matched_requirements'), limit=10)
            snapshot.role_fit_missing_requirements = _safe_list(payload.get('role_fit_missing_requirements'), limit=10)
            snapshot.data_quality_flags = _safe_list(payload.get('data_quality_flags'), limit=12)
            snapshot.executive_summary = payload.get('executive_summary') or snapshot.profile_strength_summary
            snapshot.resume_score = _clamp_score(payload.get('resume_score'))
            snapshot.role_fit_score = _clamp_score(payload.get('role_fit_score'))
            snapshot.market_demand_score = _clamp_score(payload.get('market_demand_score'))
            snapshot.current_skills_impact_score = _clamp_score(payload.get('current_skills_impact_score'))
            snapshot.market_demand_label = _clean_text(payload.get('market_demand_label'), 80)
            snapshot.salary_range = _clean_text(payload.get('salary_range'), 120)
            snapshot.salary_trend_summary = payload.get('salary_trend_summary', '')
            snapshot.market_demand_summary = payload.get('market_demand_summary', '')
            snapshot.current_skills_impact_summary = payload.get('current_skills_impact_summary', '')
            snapshot.top_strengths = _safe_list(payload.get('top_strengths'), limit=5)
            snapshot.growth_areas = _safe_list(payload.get('growth_areas'), limit=5)
            snapshot.recommended_skills = _safe_list(payload.get('recommended_skills'), limit=8)
            snapshot.recommended_roles = _safe_list(payload.get('recommended_roles'), limit=6)
            snapshot.payload = payload
            snapshot.generated_for_role = interview.role.role if interview and interview.role else ''
            snapshot.generated_for_title = resume.current_title if resume else ''
            snapshot.generated_at = timezone.now()
            snapshot.model_name = self.model
            snapshot.save()
        except Exception as exc:
            try:
                user = User.objects.get(id=user_id)
                snapshot = self.get_snapshot(user)
                if snapshot.source_signature == signature:
                    snapshot.status = CandidateInsightSnapshot.Status.FAILED
                    snapshot.error_message = str(exc)
                    snapshot.generated_at = timezone.now()
                    snapshot.save(update_fields=['status', 'error_message', 'generated_at', 'updated_at'])
            except Exception:
                pass
        finally:
            close_old_connections()

    def _generate_payload(self, user: User, profile: UserProfile, resume: CandidateResume | None, interview: Interview | None) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError('OpenAI insights generation is not configured.')

        resume_sections = []
        if resume:
            for section in resume.sections.all():
                resume_sections.append({
                    'title': section.title,
                    'section_key': section.section_key,
                    'content': section.content,
                })

        vacancy = interview.role if interview and interview.role else None
        deterministic_resume_score, role_family, resume_type, resume_payload = _deterministic_resume_score(user, profile, resume)
        role_fit_signal = _build_role_fit_signal(resume, interview)
        profile_strength_signal = _build_profile_strength_signal(
            user,
            profile,
            resume,
            deterministic_resume_score,
            role_family,
            resume_type,
            resume_payload,
        )
        data_quality_flags = _build_data_quality_flags(profile, resume, interview, role_fit_signal)
        computed_signals = {
            'resume_score': deterministic_resume_score,
            'resume_role_family': role_family,
            'resume_type': resume_type,
            'profile_strength_evidence': profile_strength_signal['evidence'],
            'profile_strength_missing_items': profile_strength_signal['missing_items'],
            'profile_strength_confidence': profile_strength_signal['confidence'],
            'role_fit_score': role_fit_signal['score'],
            'role_fit_confidence': role_fit_signal['confidence'],
            'role_fit_matched_requirements': role_fit_signal['matched'],
            'role_fit_missing_requirements': role_fit_signal['missing'],
            'role_fit_evidence': role_fit_signal['evidence'],
            'data_quality_flags': data_quality_flags,
        }

        prompt_input = {
            'candidate': {
                'name': f'{user.first_name} {user.last_name}'.strip(),
                'email': user.email,
                'phone': profile.phone or '',
                'gender': profile.gender or '',
            },
            'role': {
                'title': vacancy.role if vacancy else '',
                'position': vacancy.position if vacancy else '',
                'description': vacancy.description if vacancy else '',
                'experience_required': vacancy.experience_required if vacancy else '',
                'location': vacancy.location if vacancy else '',
                'job_type': vacancy.job_type if vacancy else '',
                'salary_range': vacancy.salary_range if vacancy else '',
            },
            'resume': {
                'headline': resume.headline if resume else '',
                'summary': resume.summary if resume else '',
                'candidate_type': resume.candidate_type if resume else '',
                'current_title': resume.current_title if resume else '',
                'current_company': resume.current_company if resume else '',
                'total_experience_years': float(resume.total_experience_years) if resume and resume.total_experience_years is not None else None,
                'structured_data': resume.structured_data if resume else {},
                'sections': resume_sections[:12],
            },
            'computed_signals': computed_signals,
            'note': (
                'Generate premium dashboard insights for an AI hiring platform. '
                'Use only the candidate profile and resume data provided. '
                'Do not invent employers, degrees, years, salary, achievements, or skills. '
                'Do not change computed resume_score or role_fit_score; explain those computed values. '
                'Profile Strength must describe resume/profile quality only. '
                'Role Fit must describe the match against the assigned vacancy only. '
                'Skill Impact must describe skills value and gaps based on parsed skills and role evidence. '
                'For market demand and salary trend, provide directional estimates and clearly keep them approximate, not authoritative. '
                'If evidence is weak, set confidence low and explain what data is missing. '
                'Return concise recruiter-friendly insight summaries. Treat executive_summary as the backward-compatible Profile Strength summary, and keep role_fit_summary distinct.'
            ),
        }

        body = json.dumps({
            'model': self.model,
            'input': json.dumps(prompt_input),
            'temperature': 0.4,
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': 'candidate_insights',
                    'strict': True,
                    'schema': self._response_schema(),
                }
            },
        }).encode('utf-8')

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f'OpenAI insights HTTP error {exc.code}: {detail[:400]}') from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f'OpenAI insights network error: {exc.reason}') from exc

        text = self._extract_output_text(payload)
        if not text:
            raise RuntimeError('OpenAI insights response did not contain usable structured output.')
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise RuntimeError('OpenAI insights response did not contain a JSON object.')

        parsed['resume_score'] = deterministic_resume_score if deterministic_resume_score is not None else _clamp_score(parsed.get('resume_score'))
        parsed['role_fit_score'] = role_fit_signal['score']
        parsed['profile_strength_summary'] = _clean_text(parsed.get('profile_strength_summary') or profile_strength_signal['summary'], 900)
        parsed['profile_strength_evidence'] = _safe_list(
            parsed.get('profile_strength_evidence') or profile_strength_signal['evidence'],
            limit=10,
        )
        parsed['profile_strength_missing_items'] = _safe_list(
            parsed.get('profile_strength_missing_items') or profile_strength_signal['missing_items'],
            limit=10,
        )
        parsed['profile_strength_confidence'] = _safe_confidence(
            parsed.get('profile_strength_confidence') or profile_strength_signal['confidence'],
            profile_strength_signal['confidence'],
        )
        parsed['role_fit_summary'] = _clean_text(parsed.get('role_fit_summary') or role_fit_signal['summary'], 900)
        parsed['role_fit_confidence'] = role_fit_signal['confidence']
        parsed['role_fit_evidence'] = _safe_list(role_fit_signal['evidence'], limit=10)
        parsed['role_fit_matched_requirements'] = _safe_list(role_fit_signal['matched'], limit=10)
        parsed['role_fit_missing_requirements'] = _safe_list(role_fit_signal['missing'], limit=10)
        parsed['data_quality_flags'] = _dedupe_strings(
            data_quality_flags + _safe_list(parsed.get('data_quality_flags'), limit=12),
            limit=12,
            item_limit=80,
        )
        parsed['executive_summary'] = _clean_text(parsed['profile_strength_summary'] or parsed.get('executive_summary'), 900)
        parsed['computed_signals'] = computed_signals
        return parsed

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        text = (payload.get('output_text') or '').strip()
        if text:
            return text
        for item in payload.get('output') or []:
            for content in item.get('content', []):
                maybe_text = content.get('text')
                if isinstance(maybe_text, str) and maybe_text.strip():
                    return maybe_text.strip()
        return ''

    def _response_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'executive_summary': {'type': 'string'},
                'profile_strength_summary': {'type': 'string'},
                'profile_strength_evidence': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 10,
                },
                'profile_strength_missing_items': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 10,
                },
                'profile_strength_confidence': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                'role_fit_summary': {'type': 'string'},
                'role_fit_confidence': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                'role_fit_evidence': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 10,
                },
                'role_fit_matched_requirements': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 10,
                },
                'role_fit_missing_requirements': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 10,
                },
                'data_quality_flags': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 12,
                },
                'resume_score': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 100},
                'role_fit_score': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 100},
                'market_demand_score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                'current_skills_impact_score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                'market_demand_label': {'type': 'string'},
                'salary_range': {'type': 'string'},
                'salary_trend_summary': {'type': 'string'},
                'market_demand_summary': {'type': 'string'},
                'current_skills_impact_summary': {'type': 'string'},
                'top_strengths': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 5,
                },
                'growth_areas': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 5,
                },
                'recommended_skills': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 8,
                },
                'recommended_roles': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 6,
                },
            },
            'required': [
                'executive_summary',
                'profile_strength_summary',
                'profile_strength_evidence',
                'profile_strength_missing_items',
                'profile_strength_confidence',
                'role_fit_summary',
                'role_fit_confidence',
                'role_fit_evidence',
                'role_fit_matched_requirements',
                'role_fit_missing_requirements',
                'data_quality_flags',
                'resume_score',
                'role_fit_score',
                'market_demand_score',
                'current_skills_impact_score',
                'market_demand_label',
                'salary_range',
                'salary_trend_summary',
                'market_demand_summary',
                'current_skills_impact_summary',
                'top_strengths',
                'growth_areas',
                'recommended_skills',
                'recommended_roles',
            ],
        }
