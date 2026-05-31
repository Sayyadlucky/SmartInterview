import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from django.db import transaction

from smartInterviewApp.models import (
    ResumeAiFeedback,
    ResumeAiLearningPattern,
    ResumeAiProfessionalReview,
    ResumeAiSuggestion,
)


PROMPT_VERSION = 'resume_ai_professional_review_v1'

ROLE_KEYWORDS = {
    'software_it': {
        'software', 'developer', 'engineer', 'python', 'django', 'java', 'javascript', 'react',
        'node', 'api', 'backend', 'frontend', 'fullstack', 'devops', 'cloud', 'aws', 'docker',
        'kubernetes', 'database', 'sql',
    },
    'data_analytics': {
        'data', 'analyst', 'analytics', 'sql', 'dashboard', 'power bi', 'tableau', 'excel',
        'etl', 'reporting', 'python', 'insights', 'metrics', 'business intelligence',
    },
    'hr_recruitment': {
        'hr', 'recruiter', 'recruitment', 'talent acquisition', 'sourcing', 'screening',
        'interview coordination', 'ats', 'hiring', 'onboarding',
    },
    'sales_marketing': {
        'sales', 'marketing', 'lead generation', 'crm', 'campaign', 'conversion', 'revenue',
        'client', 'account executive', 'business development', 'seo', 'sem',
    },
    'finance_accounting': {
        'finance', 'accounting', 'accounts', 'audit', 'tax', 'gst', 'financial', 'payroll',
        'reconciliation', 'invoice', 'tally',
    },
    'operations_admin': {
        'operations', 'admin', 'administrator', 'coordination', 'vendor', 'supply chain',
        'logistics', 'office', 'process',
    },
    'customer_support': {
        'support', 'customer service', 'customer success', 'helpdesk', 'ticket', 'sla',
        'client support', 'escalation',
    },
    'design_product': {
        'designer', 'design', 'product', 'ux', 'ui', 'figma', 'wireframe', 'prototype',
        'research', 'roadmap',
    },
    'management_leadership': {
        'manager', 'lead', 'leader', 'director', 'head', 'strategy', 'team management',
        'stakeholder', 'program management',
    },
    'fresher_internship': {
        'fresher', 'intern', 'internship', 'graduate', 'entry level', 'trainee',
    },
}

SECTION_LABELS = {
    'basics': 'Profile Basics',
    'experience': 'Experience',
    'projects': 'Projects',
    'education': 'Education',
    'skills': 'Skills',
    'certifications': 'Certifications',
    'achievements': 'Achievements',
    'languages': 'Languages',
    'extras': 'Extras',
    'review': 'Review',
    'finish': 'Finish',
}

ROLE_DEFAULTS = {
    'software_it': 'Software Engineer',
    'data_analytics': 'Data Analyst',
    'hr_recruitment': 'HR Recruiter',
    'sales_marketing': 'Sales Executive',
    'finance_accounting': 'Finance Executive',
    'operations_admin': 'Operations Coordinator',
    'customer_support': 'Customer Support Executive',
    'design_product': 'UI/UX Designer',
    'management_leadership': 'Project Manager',
    'fresher_internship': 'Target Role',
    'general': 'Professional',
}

LOW_PRIORITY_SKILLS = {
    'c',
    'c++',
    'windows',
    'vs code',
    'visual studio code',
    'pycharm',
    'postman',
    'thonny',
    'ms office',
    'microsoft office',
}

SOFTWARE_CORE_SKILLS = {
    'python',
    'django',
    'django rest framework',
    'rest api',
    'rest apis',
    'angular',
    'flask',
    'mysql',
    'postgresql',
    'sql',
    'javascript',
    'typescript',
    'react',
    'node',
}

ROLE_TEMPLATES = {
    'software_it': {
        'headline': '{role} | {top_skills}{experience_suffix}',
        'summary': '{role}{experience_phrase} building web applications with {top_skills}. Experienced in backend development, responsive frontend implementation, production issue resolution, performance improvement, and Agile delivery{domain_phrase}.',
        'bullet': 'Built and maintained {top_skills} solutions for {domain}, improving reliability, maintainability, and user experience.',
        'keywords': ['APIs', 'databases', 'testing', 'deployment', 'Git'],
    },
    'data_analytics': {
        'headline': '{role} | SQL, Dashboards, Reporting, Business Insights',
        'summary': '{role}{experience_phrase} focused on SQL, dashboards, reporting, and turning business metrics into decisions{domain_phrase}.',
        'bullet': 'Built reporting and dashboard workflows using {top_skills}, supporting clearer business decisions and recurring metric tracking.',
        'keywords': ['SQL', 'dashboards', 'ETL', 'reporting', 'business metrics'],
    },
    'hr_recruitment': {
        'headline': '{role} | Sourcing, Screening, ATS',
        'summary': '{role}{experience_phrase} across sourcing, screening, interview coordination, ATS updates, and stakeholder communication{domain_phrase}.',
        'bullet': 'Coordinated sourcing, screening, interview scheduling, and ATS updates, supporting a more organized hiring pipeline.',
        'keywords': ['sourcing', 'screening', 'ATS', 'hiring pipeline', 'stakeholders'],
    },
    'sales_marketing': {
        'headline': '{role} | Lead Generation, CRM, Client Relationship Management',
        'summary': '{role}{experience_phrase} in lead generation, CRM discipline, campaigns, conversion tracking, and client handling{domain_phrase}.',
        'bullet': 'Managed lead follow-ups, CRM updates, and client conversations, supporting pipeline visibility and stronger conversion follow-through.',
        'keywords': ['lead generation', 'CRM', 'conversion', 'campaigns', 'client handling'],
    },
    'finance_accounting': {
        'headline': '{role} | Accounting, Reconciliation, GST, Reporting',
        'summary': '{role}{experience_phrase} in accounting operations, reconciliations, reporting, and compliance-focused documentation{domain_phrase}.',
        'bullet': 'Prepared accounting, reconciliation, and reporting records using {top_skills}, supporting cleaner financial documentation and follow-up.',
        'keywords': ['reconciliation', 'reporting', 'compliance', 'Excel', 'Tally'],
    },
    'operations_admin': {
        'headline': '{role} | Process Support, Vendor Coordination, Documentation',
        'summary': '{role}{experience_phrase} coordinating daily operations, process tracking, documentation, vendor follow-ups, and stakeholder communication{domain_phrase}.',
        'bullet': 'Coordinated documentation, vendor follow-ups, and daily process tracking, improving operational visibility and handoffs.',
        'keywords': ['coordination', 'documentation', 'vendor management', 'process tracking'],
    },
    'customer_support': {
        'headline': '{role} | Ticketing, Escalations, SLA, Client Communication',
        'summary': '{role}{experience_phrase} handling customer queries, tickets, escalations, SLA-focused follow-through, and client communication{domain_phrase}.',
        'bullet': 'Handled customer tickets, follow-ups, and escalations, supporting timely issue resolution and clearer client communication.',
        'keywords': ['ticketing', 'SLA', 'escalations', 'customer communication'],
    },
    'design_product': {
        'headline': '{role} | Figma, Wireframes, Prototypes, User Research',
        'summary': '{role}{experience_phrase} in user research, wireframes, prototypes, design systems, and product collaboration{domain_phrase}.',
        'bullet': 'Created wireframes, prototypes, and UI flows in {top_skills}, supporting clearer product decisions and user experience improvements.',
        'keywords': ['Figma', 'UX research', 'wireframes', 'prototypes', 'design systems'],
    },
    'management_leadership': {
      'headline': '{role} | Team Leadership, Strategy, Delivery',
        'summary': '{role}{experience_phrase} aligning teams, stakeholders, priorities, delivery outcomes, and execution discipline{domain_phrase}.',
        'bullet': 'Led stakeholder coordination, delivery planning, and team follow-through, supporting clearer priorities and execution outcomes.',
        'keywords': ['team leadership', 'stakeholder management', 'delivery', 'strategy'],
    },
    'fresher_internship': {
        'headline': 'Entry-Level {role} | Projects, Coursework, Internship Experience',
        'summary': 'Entry-level {role} candidate with project, coursework, internship, and tool exposure in {top_skills}. Strongest proof should come from practical projects, certifications, or internship work.',
        'bullet': 'Built a project using {top_skills}, demonstrating practical problem solving, documentation, and delivery discipline.',
        'keywords': ['projects', 'internship', 'coursework', 'certifications'],
    },
    'general': {
        'headline': '{role} | {top_skills}',
        'summary': '{role}{experience_phrase} with experience in {top_skills}. Focused on clear execution, documentation, collaboration, and practical outcomes{domain_phrase}.',
        'bullet': 'Used {top_skills} to support daily execution, documentation, collaboration, and measurable follow-through.',
        'keywords': ['communication', 'coordination', 'documentation', 'analysis'],
    },
}

WEAK_PHRASES = [
    'motivated individual',
    'growth-oriented company',
    'organisational success',
    'organizational success',
    'personal development',
    'hardworking',
    'good communication',
    'responsible for',
    'team player',
    'quick learner',
    'self motivated',
    'self-motivated',
    'seeking a position',
    'leverage my skills',
    'contribute to success',
]

ACTION_WORDS = {
    'built', 'created', 'improved', 'reduced', 'increased', 'delivered', 'launched',
    'designed', 'implemented', 'automated', 'analyzed', 'coordinated', 'managed',
    'optimized', 'resolved', 'led', 'supported',
}


def generate_resume_ai_suggestions(candidate, draft_payload: dict, current_step: str | None = None, section_key: str | None = None) -> dict:
    if not getattr(settings, 'RESUME_AI_LOCAL_ENABLED', True):
        return {
            'success': True,
            'provider': 'local',
            'role_family': 'general',
            'resume_type': 'incomplete',
            'score': 0,
            'suggestions': [],
        }

    payload = draft_payload if isinstance(draft_payload, dict) else {}
    role_family = detect_role_family(payload)
    resume_type = detect_resume_type(payload, role_family)
    preferred = normalize_step_key(section_key or current_step or '')
    trusted_patterns = load_trusted_patterns(role_family, preferred)
    context = _context_from_payload(payload, role_family, resume_type)
    suggestions = _build_local_suggestions(payload, context, trusted_patterns, current_step=preferred)
    suggestions = _dedupe_and_rank_suggestions(suggestions, preferred)

    score = score_resume(payload, role_family=role_family, resume_type=resume_type)
    return {
        'success': True,
        'provider': 'local',
        'role_family': role_family,
        'resume_type': resume_type,
        'score': score,
        'suggestions': suggestions[:5],
    }


def detect_role_family(payload: dict) -> str:
    basics = payload.get('basics') or {}
    text_parts = [
        basics.get('headline', ''),
        basics.get('summary', ''),
        ' '.join(payload.get('skills') or []),
    ]
    for section in ('experience', 'projects'):
        for item in payload.get(section) or []:
            if isinstance(item, dict):
                text_parts.extend([
                    item.get('title', ''),
                    item.get('role', ''),
                    item.get('description', ''),
                    ' '.join(item.get('tech_stack') or []),
                ])
    text = _normalize(' '.join(text_parts))
    scores: dict[str, int] = {}
    for family, keywords in ROLE_KEYWORDS.items():
        scores[family] = sum(1 for keyword in keywords if keyword in text)
    family, score = max(scores.items(), key=lambda item: item[1])
    return family if score > 0 else 'general'


def detect_resume_type(payload: dict, role_family: str) -> str:
    basics = payload.get('basics') or {}
    experience = payload.get('experience') or []
    skills = payload.get('skills') or []
    text = _normalize(' '.join([
        basics.get('headline', ''),
        basics.get('summary', ''),
        ' '.join(skills),
    ]))
    if not basics.get('headline') and not basics.get('summary') and not experience and not skills:
        return 'incomplete'
    if any(term in text for term in ('fresher', 'intern', 'graduate', 'entry level', 'trainee')) or not experience:
        return 'fresher'
    if any(term in text for term in ('career switch', 'transitioning', 'switched from')):
        return 'career_switch'
    if role_family in {'software_it', 'data_analytics'}:
        return 'technical'
    if role_family in {'management_leadership'}:
        return 'leadership'
    return 'experienced' if experience else 'non_technical'


def score_resume(payload: dict, role_family: str | None = None, resume_type: str | None = None) -> int:
    role_family = role_family or detect_role_family(payload)
    resume_type = resume_type or detect_resume_type(payload, role_family)
    basics = payload.get('basics') or {}
    skills = payload.get('skills') or []
    experience = payload.get('experience') or []
    projects = payload.get('projects') or []
    education = payload.get('education') or []
    certifications = payload.get('certifications') or []
    achievements = payload.get('achievements') or []
    summary = basics.get('summary') or ''
    headline = basics.get('headline') or ''

    score = 14
    score += 4 if basics.get('name') else 0
    score += 5 if basics.get('email') else 0
    score += 5 if basics.get('phone') else 0
    score += 4 if basics.get('location') else 0
    score += 5 if _has_relevant_profile_link(payload, role_family) else 0

    score += 12 if _is_strong_headline(headline, role_family) else 8 if headline else 0
    if _is_strong_summary(summary, role_family):
        score += 18
    elif len(summary) >= 90:
        score += 12
    elif summary:
        score += 8

    relevant_skill_count = len(_relevant_skills(skills, role_family))
    score += min(14, relevant_skill_count * 2)
    if len(skills) > 28:
        score -= 8
    elif len(skills) > 22:
        score -= 5
    elif len(skills) > 18:
        score -= 3

    proof_score = 0
    if resume_type in {'fresher', 'career_switch'}:
        proof_score += 12 if projects else 0
        proof_score += 8 if education else 0
        proof_score += 6 if certifications else 0
        proof_score += 5 if _has_project_detail(projects) else 0
    else:
        proof_score += min(20, len(experience) * 5) if experience else 0
        proof_score += 8 if _experience_has_action_outcome(experience) else 3 if experience else 0
        proof_score += 5 if education else 0
        proof_score += 4 if projects and role_family in {'software_it', 'data_analytics', 'design_product'} else 0
        proof_score += 5 if achievements else 0
        proof_score += 4 if certifications and role_family in {'software_it', 'data_analytics', 'finance_accounting', 'hr_recruitment'} else 0
    score += min(34, proof_score)

    if _contains_weak_phrase(summary):
        score -= 6
    if experience and not _experience_has_action_outcome(experience):
        score -= 5
    if role_family in {'software_it', 'data_analytics', 'design_product'} and not projects and resume_type in {'fresher', 'technical', 'career_switch'}:
        score -= 4
    if resume_type != 'fresher' and experience and any(not (item.get('company') or item.get('institution')) for item in experience if isinstance(item, dict)):
        score -= 4
    if education and any(not (item.get('institution') and (item.get('duration') or item.get('duration_text') or item.get('start_date'))) for item in education if isinstance(item, dict)):
        score -= 3

    if resume_type == 'incomplete':
        return max(20, min(45, score))
    if resume_type in {'technical', 'experienced', 'leadership'} and experience and education and headline and summary:
        score = max(score, 66)
        if len(experience) >= 3 and len(skills) >= 8:
            score = max(score, 72)
    if score >= 89 and not (_is_strong_summary(summary, role_family) and _experience_has_action_outcome(experience) and (achievements or projects or certifications)):
        score = 88
    return max(20, min(96, int(round(score))))


def load_trusted_patterns(role_family: str, section_key: str) -> list[ResumeAiLearningPattern]:
    min_confidence = float(getattr(settings, 'RESUME_AI_MIN_CONFIDENCE_TO_USE', 0.72))
    query = ResumeAiLearningPattern.objects.filter(
        status=ResumeAiLearningPattern.Status.TRUSTED,
        confidence_score__gte=min_confidence,
    ).filter(role_family__in=[role_family, 'general'])
    if section_key:
        query = query.filter(section_key__in=[section_key, 'general'])
    return list(query.order_by('-confidence_score')[:8])


def persist_shown_suggestions(candidate, draft, result: dict, current_step: str | None = None) -> dict:
    id_map = {}
    for suggestion in result.get('suggestions') or []:
        saved = ResumeAiSuggestion.objects.create(
            candidate=candidate,
            draft=draft,
            section_key=suggestion.get('section_key') or current_step or '',
            step_key=current_step or suggestion.get('section_key') or '',
            role_family=result.get('role_family') or 'general',
            resume_type=result.get('resume_type') or 'incomplete',
            suggestion_type=suggestion.get('suggestion_type') or 'ats_readability',
            local_suggestion_title=suggestion.get('title') or 'Resume suggestion',
            local_suggestion_text=suggestion.get('message') or '',
            local_suggestion_payload=suggestion,
            source_context=_sanitize_source_context(suggestion.get('source_context') or {}),
        )
        suggestion['suggestion_id'] = saved.id
        id_map[suggestion.get('client_id') or str(saved.id)] = saved.id
    result['suggestion_ids'] = id_map
    return result


def record_suggestion_feedback(suggestion: ResumeAiSuggestion, candidate, feedback: str, reason: str = '') -> ResumeAiFeedback:
    status_map = {
        ResumeAiFeedback.Feedback.APPLIED: ResumeAiSuggestion.Status.APPLIED,
        ResumeAiFeedback.Feedback.LIKED: ResumeAiSuggestion.Status.APPLIED,
        ResumeAiFeedback.Feedback.IGNORED: ResumeAiSuggestion.Status.IGNORED,
        ResumeAiFeedback.Feedback.NOT_USEFUL: ResumeAiSuggestion.Status.NOT_USEFUL,
        ResumeAiFeedback.Feedback.REQUESTED_PROFESSIONAL_REVIEW: ResumeAiSuggestion.Status.PROFESSIONAL_REQUESTED,
        ResumeAiFeedback.Feedback.APPLIED_PROFESSIONAL_REVIEW: ResumeAiSuggestion.Status.PROFESSIONAL_APPLIED,
    }
    with transaction.atomic():
        suggestion.status = status_map.get(feedback, suggestion.status)
        suggestion.save(update_fields=['status', 'updated_at'])
        event = ResumeAiFeedback.objects.create(
            suggestion=suggestion,
            candidate=candidate,
            feedback=feedback,
            feedback_reason=(reason or '')[:2000],
        )
        _update_learning_from_feedback(suggestion, feedback)
    return event


def request_professional_review(suggestion: ResumeAiSuggestion, candidate, sanitized_payload: dict) -> dict:
    if not getattr(settings, 'RESUME_AI_OPENAI_REVIEW_ENABLED', False):
        return _professional_review_error('professional_review_disabled', 'Professional review is not available right now.')
    if not getattr(settings, 'OPENAI_API_KEY', '').strip():
        return _professional_review_error('openai_api_key_missing', 'Professional review is not available right now.')

    record_suggestion_feedback(
        suggestion,
        candidate,
        ResumeAiFeedback.Feedback.REQUESTED_PROFESSIONAL_REVIEW,
    )
    try:
        professional_payload = call_openai_professional_review(suggestion, sanitized_payload)
        professional_payload = _normalize_professional_payload(professional_payload, suggestion)
        review = ResumeAiProfessionalReview.objects.create(
            suggestion=suggestion,
            candidate=candidate,
            openai_model=getattr(settings, 'RESUME_AI_OPENAI_MODEL', 'gpt-4.1-mini'),
            prompt_version=PROMPT_VERSION,
            professional_title=professional_payload.get('title', ''),
            professional_text=professional_payload.get('message', ''),
            professional_payload=professional_payload,
        )
        learning_pattern = None
        if getattr(settings, 'RESUME_AI_LEARNING_ENABLED', True):
            learning_pattern = extract_learning_pattern_from_professional_review(
                suggestion=suggestion,
                professional_payload=professional_payload,
            )
        return {
            'success': True,
            'provider': 'openai',
            'professional_review_id': review.id,
            'title': professional_payload.get('title', ''),
            'message': professional_payload.get('message', ''),
            'recommended_text': professional_payload.get('recommended_text', ''),
            'apply_target': professional_payload.get('apply_target', ''),
            'apply_mode': professional_payload.get('apply_mode', 'replace'),
            'learning_pattern_created': bool(learning_pattern),
        }
    except Exception as exc:
        ResumeAiProfessionalReview.objects.create(
            suggestion=suggestion,
            candidate=candidate,
            openai_model=getattr(settings, 'RESUME_AI_OPENAI_MODEL', 'gpt-4.1-mini'),
            prompt_version=PROMPT_VERSION,
            error_code='openai_review_failed',
            professional_payload={'error': str(exc)[:400]},
        )
        return _professional_review_error('openai_review_failed', 'Professional review is not available right now.')


def call_openai_professional_review(suggestion: ResumeAiSuggestion, sanitized_payload: dict) -> dict:
    api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
    model = getattr(settings, 'RESUME_AI_OPENAI_MODEL', 'gpt-4.1-mini').strip() or 'gpt-4.1-mini'
    timeout = max(1, int(getattr(settings, 'RESUME_AI_OPENAI_TIMEOUT_SECONDS', 30)))
    prompt = _build_openai_prompt(suggestion, sanitized_payload)
    body = json.dumps({
        'model': model,
        'input': prompt,
        'temperature': 0.2,
        'text': {
            'format': {
                'type': 'json_schema',
                'name': 'resume_professional_review',
                'strict': True,
                'schema': _professional_review_schema(),
            },
        },
    }).encode('utf-8')
    request = urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    payload = None
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            last_error = RuntimeError(f'OpenAI professional review HTTP error {exc.code}: {detail[:300]}')
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 1:
                raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = RuntimeError(f'OpenAI professional review network error: {exc.reason}')
            if attempt == 1:
                raise last_error from exc
        time.sleep(0.5)
    if payload is None:
        raise RuntimeError(str(last_error or 'OpenAI professional review failed.'))
    output_text = _extract_output_text(payload)
    if not output_text:
        raise RuntimeError('OpenAI professional review returned no output.')
    parsed = json.loads(output_text)
    if not isinstance(parsed, dict):
        raise RuntimeError('OpenAI professional review returned invalid JSON.')
    return parsed


def extract_learning_pattern_from_professional_review(suggestion: ResumeAiSuggestion, professional_payload: dict) -> ResumeAiLearningPattern | None:
    reusable = professional_payload.get('reusable_pattern') if isinstance(professional_payload, dict) else {}
    if not isinstance(reusable, dict):
        reusable = {}
    pattern_type = _clean_identifier(reusable.get('pattern_type') or _pattern_type_for_suggestion(suggestion.suggestion_type))
    section_key = _clean_identifier(reusable.get('section_key') or suggestion.section_key)
    role_family = _clean_identifier(reusable.get('role_family') or suggestion.role_family or 'general')
    template_text = sanitize_learning_text(reusable.get('template_text') or professional_payload.get('recommended_text') or '')
    keywords = sanitize_learning_keywords(reusable.get('keywords') or reusable.get('keywords_json') or [])
    if not template_text and not keywords:
        return None
    if _contains_private_identifier(template_text):
        return None
    if len(template_text) > 1200:
        template_text = template_text[:1200].rsplit(' ', 1)[0]

    pattern = ResumeAiLearningPattern.objects.create(
        role_family=role_family or 'general',
        resume_type=suggestion.resume_type or 'incomplete',
        section_key=section_key or suggestion.section_key,
        suggestion_type=suggestion.suggestion_type,
        pattern_type=pattern_type or 'section_tip',
        template_text=template_text,
        keywords_json=keywords,
        rule_payload={
            'source': 'openai_professional_review',
            'suggestion_id': suggestion.id,
        },
        source_count=1,
        confidence_score=0.52,
        status=ResumeAiLearningPattern.Status.CANDIDATE,
    )
    _promote_similar_patterns(pattern)
    return pattern


def record_professional_review_feedback(review: ResumeAiProfessionalReview, candidate, feedback: str) -> None:
    applied = feedback == ResumeAiFeedback.Feedback.APPLIED
    with transaction.atomic():
        review.user_applied = applied
        review.save(update_fields=['user_applied'])
        ResumeAiFeedback.objects.create(
            suggestion=review.suggestion,
            candidate=candidate,
            feedback=(
                ResumeAiFeedback.Feedback.APPLIED_PROFESSIONAL_REVIEW
                if applied else ResumeAiFeedback.Feedback.IGNORED
            ),
        )
        review.suggestion.status = (
            ResumeAiSuggestion.Status.PROFESSIONAL_APPLIED
            if applied else ResumeAiSuggestion.Status.IGNORED
        )
        review.suggestion.save(update_fields=['status', 'updated_at'])
        _update_patterns_from_professional_review(review, applied)


def sanitize_learning_text(value: str) -> str:
    text = str(value or '')
    text = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[email]', text)
    text = re.sub(r'\+?\d[\d\s().-]{7,}\d', '[phone]', text)
    text = re.sub(r'https?://\S+|www\.\S+', '[link]', text, flags=re.I)
    text = re.sub(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b', '[role/project]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def sanitize_learning_keywords(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else []
    keywords = []
    for item in raw[:20]:
        text = sanitize_learning_text(str(item))[:80]
        if text and not _contains_private_identifier(text) and text not in keywords:
            keywords.append(text)
    return keywords


def _build_local_suggestions(payload: dict, context: dict, trusted_patterns: list[ResumeAiLearningPattern], current_step: str = '') -> list[dict]:
    basics = payload.get('basics') or {}
    skills = payload.get('skills') or []
    experience = payload.get('experience') or []
    projects = payload.get('projects') or []
    education = payload.get('education') or []
    certifications = payload.get('certifications') or []
    achievements = payload.get('achievements') or []
    role_family = context['role_family']
    resume_type = context['resume_type']
    role = context['role']
    top_skills = context['top_skills']
    domain = context['domain']
    suggestions = []

    if not basics.get('headline') or not _is_strong_headline(basics.get('headline', ''), role_family):
        headline, learned = _apply_trusted_template(
            trusted_patterns,
            'headline_improvement',
            'headline_template',
            ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['headline'],
            context,
        )
        suggestions.append(_suggestion(
            'headline_improvement',
            'basics',
            'Make your headline searchable',
            'Your headline should quickly name your target role and strongest skills.',
            headline,
            'basics.headline',
            'replace',
            0.86,
            'Headline is missing, too broad, or not aligned to the target role.',
            learned_pattern=learned,
        ))

    summary = basics.get('summary') or ''
    if len(summary) < 140 or not _is_strong_summary(summary, role_family):
        summary_template, learned = _apply_trusted_template(
            trusted_patterns,
            'summary_improvement',
            'summary_template',
            ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['summary'],
            context,
        )
        suggestions.append(_suggestion(
            'summary_improvement',
            'basics',
            'Strengthen your summary',
            'Your summary should connect role, skills, and evidence without making unsupported claims.',
            summary_template,
            'basics.summary',
            'replace',
            0.84,
            'Summary is missing role focus, skill context, or outcome language.',
            learned_pattern=learned,
        ))

    weak_matches = [phrase for phrase in WEAK_PHRASES if phrase in _normalize(summary)]
    if weak_matches:
        suggestions.append(_suggestion(
            'summary_improvement',
            'basics',
            'Replace generic phrases with proof',
            f"Recruiters see phrases like \"{weak_matches[0]}\" often. Replace them with a tool, action, and result you can verify.",
            ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['summary'].format(**context),
            'basics.summary',
            'replace',
            0.82,
            'Weak phrases reduce specificity and ATS readability.',
        ))

    missing_contact = [label for key, label in (('email', 'email'), ('phone', 'phone'), ('location', 'location')) if not basics.get(key)]
    if missing_contact:
        suggestions.append(_suggestion(
            'missing_section',
            'basics',
            'Complete recruiter contact details',
            f"Add your {', '.join(missing_contact)} so hiring teams can contact and location-match you.",
            '',
            '',
            'append',
            0.8,
            'One or more core contact fields are missing.',
        ))

    if role_family in {'software_it', 'data_analytics'} and not (basics.get('github') or basics.get('portfolio') or basics.get('website')):
        suggestions.append(_suggestion(
            'missing_section',
            'basics',
            'Add a technical proof link',
            'A GitHub, portfolio, or project link helps technical recruiters verify your work when available.',
            '',
            '',
            'append',
            0.66,
            'Technical profile is missing GitHub or portfolio evidence.',
        ))
    elif role_family == 'design_product' and not (basics.get('portfolio') or basics.get('website')):
        suggestions.append(_suggestion(
            'missing_section',
            'basics',
            'Add your portfolio link',
            'Design and product resumes are stronger when recruiters can inspect real portfolio work.',
            '',
            '',
            'append',
            0.72,
            'Portfolio proof is important for design/product roles.',
        ))

    if not experience and resume_type not in {'fresher', 'incomplete'}:
        suggestions.append(_suggestion(
            'missing_section',
            'experience',
            'Add your most relevant role',
            'Experience entries help recruiters understand ownership, timeline, tools, and impact.',
            '',
            '',
            'append',
            0.77,
            'Experienced resume has no experience section.',
        ))

    if experience:
        weak_entry = _first_weak_experience_entry(experience)
        if weak_entry is not None:
            bullet = ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['bullet'].format(**context)
            suggestions.append(_suggestion(
                'bullet_strengthening',
                'experience',
                'Make experience bullets more outcome-led',
                'At least one experience entry reads like responsibilities instead of evidence. Use action, scope, and a supported outcome.',
                bullet,
                f'experience.{weak_entry}.details',
                'append',
                0.81,
                'Experience bullets lack clear action, outcome, or measurable evidence.',
            ))
        missing_role_fields = _first_entry_missing_core_fields(experience, ('company', 'duration'))
        if missing_role_fields is not None:
            suggestions.append(_suggestion(
                'ats_readability',
                'experience',
                'Complete role timeline details',
                'Add company and duration details for each important role so recruiters can understand scope and chronology.',
                '',
                '',
                'append',
                0.68,
                'One or more experience entries are missing company or duration details.',
            ))

    if not projects and (resume_type == 'fresher' or role_family in {'software_it', 'data_analytics', 'design_product'}):
        suggestions.append(_suggestion(
            'missing_section',
            'projects',
            'Add a proof project',
            'Projects are especially useful for fresher, technical, data, and design resumes because they show applied skill.',
            '',
            '',
            'append',
            0.79,
            'Project evidence is missing for a resume type where portfolio proof matters.',
        ))
    elif projects:
        weak_project = _first_weak_project_entry(projects)
        if weak_project is not None:
            suggestions.append(_suggestion(
                'bullet_strengthening',
                'projects',
                'Make project proof clearer',
                'Project entries work best when they explain the problem, tools, your role, and the result or user value.',
                f"Built a {role_family.replace('_', ' ')} project using {top_skills}, demonstrating practical problem solving, documentation, and delivery discipline.",
                f'projects.{weak_project}.description',
                'append',
                0.77,
                'Project description is missing tool, problem, or outcome context.',
            ))

    if len(skills) < 5:
        keywords, learned_keyword_pattern = _trusted_keywords(trusted_patterns, 'skills_focus')
        keywords = keywords or ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['keywords']
        suggestions.append(_suggestion(
            'skills_focus',
            'skills',
            'Add focused role keywords',
            'A short, targeted skills list helps ATS and recruiter scanning.',
            ', '.join([keyword for keyword in keywords if keyword not in skills][:6]),
            'skills',
            'append',
            0.76,
            'Skills list has too few searchable role keywords.',
            learned_pattern=learned_keyword_pattern,
        ))
    elif len(skills) > 18:
        suggestions.append(_suggestion(
            'skills_focus',
            'skills',
            'Trim unfocused skills',
            'Keep the skills list focused on the roles you want most. Move weaker or unrelated items out.',
            '',
            '',
            'append',
            0.74,
            'Skills list may be too broad for fast recruiter scanning.',
        ))

    if not education:
        suggestions.append(_suggestion(
            'missing_section',
            'education',
            'Add education details',
            'Education gives recruiters baseline qualification context, especially for fresher and early-career resumes.',
            '',
            '',
            'append',
            0.73,
            'Education section is missing.',
        ))
    elif not (education[0].get('details') or education[0].get('tech_stack') or education[0].get('description')):
        suggestions.append(_suggestion(
            'education_strengthening',
            'education',
            'Add education focus areas',
            'Add relevant coursework, honors, projects, or focus areas only if they strengthen the target role.',
            'Relevant focus areas: [coursework, honors, project, or specialization tied to your target role].',
            'education.0.details',
            'append',
            0.72,
            'Education entry lacks supporting details.',
        ))

    if resume_type != 'fresher' and not achievements and experience:
        suggestions.append(_suggestion(
            'achievements_strengthening',
            'achievements',
            'Add one verified achievement',
            'A concise achievement can surface proof that may be buried inside your experience section.',
            '',
            '',
            'append',
            0.67,
            'Experienced resume has no separate achievement or recognition signal.',
        ))

    if resume_type in {'fresher', 'career_switch'} and not certifications and role_family in {'software_it', 'data_analytics', 'finance_accounting', 'hr_recruitment', 'design_product'}:
        suggestions.append(_suggestion(
            'missing_section',
            'certifications',
            'Add relevant training or certification',
            'For fresher or career-switch resumes, relevant training can support target-role credibility when work history is limited.',
            '',
            '',
            'append',
            0.65,
            'No certification or training proof is present.',
        ))

    return suggestions


def _suggestion(suggestion_type: str, section_key: str, title: str, message: str, recommended_text: str, apply_target: str, apply_mode: str, confidence: float, reason: str, learned_pattern: ResumeAiLearningPattern | None = None) -> dict:
    client_id = f"{suggestion_type}:{section_key}:{abs(hash(title + message)) % 100000}"
    actionable = bool(recommended_text and apply_target)
    return {
        'client_id': client_id,
        'suggestion_type': suggestion_type,
        'section_key': section_key,
        'section_label': SECTION_LABELS.get(section_key, section_key.replace('_', ' ').title()),
        'title': title,
        'message': message,
        'recommended_text': recommended_text,
        'apply_target': apply_target,
        'apply_mode': apply_mode,
        'actionable': actionable,
        'primary_action_label': 'Apply' if actionable else 'View guidance',
        'target_label': _target_label(apply_target, section_key),
        'confidence': confidence,
        'reason': reason,
        'learned_pattern_used': bool(learned_pattern),
        'learned_pattern_id': learned_pattern.id if learned_pattern else None,
        'display_priority': 0,
    }


def _context_from_payload(payload: dict, role_family: str, resume_type: str) -> dict:
    basics = payload.get('basics') or {}
    ranked_skills = rank_top_skills(payload, role_family, limit=5)
    role = _clean_role_from_headline(basics.get('headline') or '', role_family)
    if not role:
        for item in payload.get('experience') or []:
            role = item.get('title') or item.get('role') or ''
            if role:
                break
    if not role:
        role = ROLE_DEFAULTS.get(role_family, 'Professional')
    years = _extract_years(payload)
    domain = _infer_domain(payload)
    default_skills = ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['keywords'][:4]
    top_skills = ', '.join(ranked_skills or default_skills)
    if role_family == 'fresher_internship' and role.lower().startswith('entry-level'):
        role = role.replace('Entry-Level ', '')
    domain_phrase = ''
    if domain:
        domain_phrase = f' for {domain}-domain applications' if role_family in {'software_it', 'data_analytics', 'design_product'} else f' for {domain}-domain workflows'
    return {
        'role_family': role_family,
        'resume_type': resume_type,
        'role': role[:80],
        'top_skills': top_skills,
        'experience_suffix': f' | {years} years experience' if years else '',
        'experience_phrase': f' with {years} years of experience' if years else '',
        'domain': domain,
        'domain_phrase': domain_phrase,
    }


def _first_weak_experience_entry(experience: list[dict]) -> int | None:
    for index, item in enumerate(experience):
        text = _normalize(' '.join([
            item.get('description', ''),
            ' '.join(item.get('details') or []),
        ]))
        if not text:
            return index
        has_action = any(word in text for word in ACTION_WORDS)
        has_metric = bool(re.search(r'\d|%|percent|revenue|cost|time|sla|pipeline|conversion', text))
        if 'responsible for' in text or not (has_action and has_metric):
            return index
    return None


def _clean_role_from_headline(headline: str, role_family: str) -> str:
    role = str(headline or '').strip()
    if not role:
        return ''
    role = re.split(r'\s+\|\s+|\s+·\s+', role, maxsplit=1)[0]
    role = re.sub(r'\bwith\s+[1-9]\d?\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience\b', '', role, flags=re.I)
    role = re.sub(r'\b[1-9]\d?\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience\b', '', role, flags=re.I)
    if role_family == 'software_it':
        role = re.sub(r'\s+in\s+(?:python|django|angular|flask|fullstack|full-stack|backend|frontend).*$','', role, flags=re.I)
    role = re.sub(r'\s*[-–—]\s*(?:python|django|angular|react|java|sales|hr|finance|data|sql).*$','', role, flags=re.I)
    role = re.sub(r'\s+', ' ', role).strip(' -–—|')
    if not role or len(role) > 80:
        return ROLE_DEFAULTS.get(role_family, 'Professional')
    return role


def rank_top_skills(payload: dict, role_family: str, limit: int = 5) -> list[str]:
    candidates = _collect_skill_candidates(payload)
    if not candidates:
        return []

    recent_tech = []
    for item in (payload.get('experience') or [])[:2]:
        if isinstance(item, dict):
            recent_tech.extend(item.get('tech_stack') or [])
            recent_tech.extend(_split_skill_text(item.get('techStackText') or ''))
    recent_text = _normalize(' '.join(str(skill) for skill in recent_tech))
    basics = payload.get('basics') or {}
    profile_text = _normalize(' '.join([
        basics.get('headline', ''),
        basics.get('summary', ''),
    ]))
    role_keywords = ROLE_KEYWORDS.get(role_family, set()) | set(ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['keywords'])
    normalized_role_keywords = {_normalize(keyword) for keyword in role_keywords}

    scored: list[tuple[int, int, str]] = []
    seen = set()
    for position, skill in enumerate(candidates):
        canonical = _canonical_skill(skill)
        normalized = _normalize(canonical)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        score = max(0, 60 - position)
        if _skill_matches_text(normalized, recent_text):
            score += 90
        if _skill_matches_text(normalized, profile_text):
            score += 45
        if normalized in normalized_role_keywords or any(_skill_matches_keyword(normalized, keyword) for keyword in normalized_role_keywords):
            score += 35
        if role_family == 'software_it' and normalized in SOFTWARE_CORE_SKILLS:
            score += 50
        if normalized in LOW_PRIORITY_SKILLS:
            score -= 85
        scored.append((score, -position, canonical))

    scored.sort(key=lambda item: (-item[0], item[1], item[2].lower()))
    return [skill for score, _, skill in scored if score > -10][:limit]


def _collect_skill_candidates(payload: dict) -> list[str]:
    candidates: list[str] = []
    for skill in payload.get('skills') or []:
        candidates.extend(_split_skill_text(skill))
    basics = payload.get('basics') or {}
    candidates.extend(_extract_known_skills_from_text(' '.join([
        basics.get('headline', ''),
        basics.get('summary', ''),
    ])))
    for section in ('experience', 'projects'):
        for item in payload.get(section) or []:
            if not isinstance(item, dict):
                continue
            for skill in item.get('tech_stack') or []:
                candidates.extend(_split_skill_text(skill))
            candidates.extend(_extract_known_skills_from_text(' '.join([
                item.get('title', ''),
                item.get('role', ''),
                item.get('description', ''),
                ' '.join(item.get('details') or []),
            ])))
    return candidates


def _split_skill_text(value: str) -> list[str]:
    text = str(value or '').replace('/', ',')
    return [item.strip() for item in re.split(r'[,;\n]+', text) if item.strip()]


def _extract_known_skills_from_text(text: str) -> list[str]:
    source = _normalize(text)
    known = [
        'Django REST Framework', 'REST API', 'Python', 'Django', 'Flask', 'Angular', 'MySQL',
        'PostgreSQL', 'SQL', 'JavaScript', 'TypeScript', 'React', 'Node', 'AWS', 'Docker',
        'Sourcing', 'Screening', 'ATS', 'Interview Coordination', 'Lead Generation', 'CRM',
        'Client Handling', 'Reconciliation', 'GST', 'Reporting', 'Figma', 'Wireframes',
    ]
    return [skill for skill in known if _normalize(skill) in source]


def _canonical_skill(skill: str) -> str:
    value = str(skill or '').strip()
    normalized = _normalize(value)
    aliases = {
        'python 3.x': 'Python',
        'python3': 'Python',
        'drf': 'Django REST Framework',
        'django rest': 'Django REST Framework',
        'rest': 'REST API',
        'rest api': 'REST API',
        'rest apis': 'REST API',
        'mysql database': 'MySQL',
        'client relationship management': 'Client Handling',
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized in {'c', 'c++'}:
        return value.upper().replace('C++', 'C++')
    return value[:80]


def _skill_matches_text(normalized_skill: str, normalized_text: str) -> bool:
    if not normalized_skill or not normalized_text:
        return False
    if len(normalized_skill) <= 2:
        return normalized_skill in set(re.findall(r'[a-z0-9+#.]+', normalized_text))
    return normalized_skill in normalized_text


def _skill_matches_keyword(normalized_skill: str, normalized_keyword: str) -> bool:
    if not normalized_skill or not normalized_keyword:
        return False
    if len(normalized_skill) <= 2 or len(normalized_keyword) <= 2:
        return normalized_skill == normalized_keyword
    return normalized_skill in normalized_keyword or normalized_keyword in normalized_skill


def _apply_trusted_template(patterns: list[ResumeAiLearningPattern], suggestion_type: str, pattern_type: str, fallback: str, context: dict) -> tuple[str, ResumeAiLearningPattern | None]:
    pattern = next((
        item for item in patterns
        if item.suggestion_type == suggestion_type
        and item.pattern_type == pattern_type
        and item.template_text
    ), None)
    template = pattern.template_text if pattern else fallback
    try:
        return template.format(**context), pattern
    except (KeyError, ValueError):
        return fallback.format(**context), None


def _trusted_keywords(patterns: list[ResumeAiLearningPattern], suggestion_type: str) -> tuple[list[str], ResumeAiLearningPattern | None]:
    keywords = []
    used_pattern = None
    for pattern in patterns:
        if pattern.suggestion_type != suggestion_type or pattern.pattern_type != 'keyword_bank':
            continue
        used_pattern = used_pattern or pattern
        for keyword in pattern.keywords_json or []:
            if keyword not in keywords:
                keywords.append(keyword)
    return keywords[:8], used_pattern


def normalize_step_key(step: str) -> str:
    value = _clean_identifier(step)
    if value in {'summary', 'headline', 'contact', 'links', 'profile'}:
        return 'basics'
    if value in {'certification', 'certifications'}:
        return 'certifications'
    if value in {'achievement', 'achievements'}:
        return 'achievements'
    if value in {'language', 'languages'}:
        return 'languages'
    if value in {'extras'}:
        return 'extras'
    return value


def _dedupe_and_rank_suggestions(suggestions: list[dict], current_step: str) -> list[dict]:
    current_sections = _sections_for_step(current_step)
    rank_by_type = {
        'headline_improvement': 95,
        'summary_improvement': 92,
        'bullet_strengthening': 88,
        'skills_focus': 78,
        'education_strengthening': 72,
        'ats_readability': 70,
        'missing_section': 66,
        'achievements_strengthening': 62,
    }
    best_by_key: dict[tuple, dict] = {}
    for suggestion in suggestions:
        key = (
            suggestion.get('suggestion_type'),
            suggestion.get('section_key'),
            suggestion.get('apply_target') or '',
        )
        section = suggestion.get('section_key') or ''
        current_bonus = 100 if section in current_sections else 0
        actionable_bonus = 8 if suggestion.get('actionable') else 0
        replace_bonus = 4 if suggestion.get('apply_mode') == 'replace' else 0
        type_score = rank_by_type.get(suggestion.get('suggestion_type'), 50)
        priority = current_bonus + type_score + actionable_bonus + replace_bonus + int(float(suggestion.get('confidence') or 0) * 10)
        suggestion['display_priority'] = priority
        current = best_by_key.get(key)
        if not current or priority > current.get('display_priority', 0):
            best_by_key[key] = suggestion
    ranked = list(best_by_key.values())
    ranked.sort(key=lambda item: (-item.get('display_priority', 0), item.get('section_label', ''), item.get('title', '')))
    return ranked[:5]


def _sections_for_step(step: str) -> set[str]:
    if step == 'extras':
        return {'certifications', 'achievements', 'languages'}
    if step in {'review', 'finish'}:
        return {'basics', 'experience', 'projects', 'education', 'skills', 'certifications', 'achievements'}
    return {step} if step else set()


def _target_label(apply_target: str, section_key: str) -> str:
    if apply_target == 'skills':
        return 'Skills'
    labels = {
        'basics.headline': 'Headline',
        'basics.summary': 'Summary',
        'basics.location': 'Location',
        'basics.linkedin': 'LinkedIn',
        'basics.github': 'GitHub',
        'basics.portfolio': 'Portfolio',
    }
    if apply_target in labels:
        return labels[apply_target]
    match = re.match(r'^(experience|projects|education|certifications|achievements|languages)\.(\d+)\.(\w+)$', apply_target or '')
    if match:
        section_label = SECTION_LABELS.get(match.group(1), match.group(1).title())
        return f"{section_label} Entry {int(match.group(2)) + 1} {match.group(3).replace('_', ' ').title()}"
    return SECTION_LABELS.get(section_key, 'Resume Section')


def _is_strong_headline(headline: str, role_family: str) -> bool:
    text = _normalize(headline)
    if len(text) < 24:
        return False
    separators = headline.count('|') + headline.count(',') + headline.count('·')
    return separators >= 1 and any(keyword in text for keyword in ROLE_KEYWORDS.get(role_family, set()) | ROLE_KEYWORDS.get('general', set()))


def _is_strong_summary(summary: str, role_family: str) -> bool:
    text = _normalize(summary)
    if len(text) < 140 or _contains_weak_phrase(summary):
        return False
    has_role_keyword = any(keyword in text for keyword in ROLE_KEYWORDS.get(role_family, set()))
    has_action = any(word in text for word in ACTION_WORDS)
    has_outcome = any(word in text for word in {'improving', 'supporting', 'delivering', 'building', 'maintaining', 'coordinating', 'resolving', 'insights', 'pipeline', 'delivery', 'reliability'})
    return has_role_keyword and (has_action or has_outcome)


def _contains_weak_phrase(text: str) -> bool:
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in WEAK_PHRASES)


def _relevant_skills(skills: list[str], role_family: str) -> list[str]:
    keywords = ROLE_KEYWORDS.get(role_family, set()) | set(ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES['general'])['keywords'])
    normalized_keywords = {_normalize(keyword) for keyword in keywords}
    relevant = []
    for skill in skills:
        normalized = _normalize(skill)
        if normalized and (
            normalized in normalized_keywords
            or any(_skill_matches_keyword(normalized, keyword) for keyword in normalized_keywords)
        ):
            relevant.append(skill)
    return relevant or skills[:4]


def _has_relevant_profile_link(payload: dict, role_family: str) -> bool:
    basics = payload.get('basics') or {}
    if role_family in {'software_it', 'data_analytics'}:
        return bool(basics.get('github') or basics.get('portfolio') or basics.get('website'))
    if role_family == 'design_product':
        return bool(basics.get('portfolio') or basics.get('website'))
    return bool(basics.get('linkedin') or basics.get('website'))


def _experience_has_action_outcome(experience: list[dict]) -> bool:
    return _first_weak_experience_entry(experience) is None if experience else False


def _has_project_detail(projects: list[dict]) -> bool:
    return any(
        isinstance(item, dict) and (item.get('description') or item.get('details') or item.get('tech_stack'))
        for item in projects
    )


def _first_weak_project_entry(projects: list[dict]) -> int | None:
    for index, item in enumerate(projects):
        text = _normalize(' '.join([
            item.get('title', ''),
            item.get('description', ''),
            ' '.join(item.get('details') or []),
            ' '.join(item.get('tech_stack') or []),
        ]))
        if len(text) < 80 or not any(word in text for word in ACTION_WORDS):
            return index
    return None


def _first_entry_missing_core_fields(items: list[dict], fields: tuple[str, ...]) -> int | None:
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for field in fields:
            if field == 'duration':
                if not (item.get('duration') or item.get('duration_text') or item.get('start_date')):
                    return index
            elif not item.get(field):
                return index
    return None


def _extract_years(payload: dict) -> int | None:
    text_parts = []
    basics = payload.get('basics') or {}
    text_parts.extend([basics.get('headline', ''), basics.get('summary', '')])
    for section in ('experience', 'projects'):
        for item in payload.get(section) or []:
            if isinstance(item, dict):
                text_parts.extend([item.get('duration', ''), item.get('duration_text', ''), item.get('description', '')])
    text = _normalize(' '.join(text_parts))
    match = re.search(r'\b([1-9]\d?)\+?\s*(?:years|yrs|year)\b', text)
    if match:
        return min(40, int(match.group(1)))
    return None


def _infer_domain(payload: dict) -> str:
    text = _normalize(' '.join([
        (payload.get('basics') or {}).get('summary', ''),
        ' '.join(
            ' '.join(str(item.get(field, '')) for field in ('company', 'description', 'role', 'title'))
            for item in (payload.get('experience') or [])
            if isinstance(item, dict)
        ),
    ]))
    domain_terms = {
        'finance': {'finance', 'banking', 'loan', 'payment', 'accounting', 'gst'},
        'enterprise': {'enterprise', 'saas', 'b2b', 'erp', 'crm'},
        'healthcare': {'healthcare', 'hospital', 'medical', 'patient'},
        'education': {'education', 'learning', 'school', 'college'},
        'retail': {'retail', 'ecommerce', 'commerce', 'store'},
        'hiring': {'recruitment', 'hiring', 'talent', 'ats'},
    }
    for label, terms in domain_terms.items():
        if any(term in text for term in terms):
            return label
    return ''


def _build_openai_prompt(suggestion: ResumeAiSuggestion, payload: dict) -> str:
    section_key = suggestion.section_key
    relevant = _relevant_payload_for_section(payload, section_key)
    return (
        'You are a professional resume reviewer. Improve only the selected suggestion/section. '
        'Do not invent degrees, employers, years, certifications, metrics, or achievements. '
        'If evidence is missing, use placeholders or advisory wording instead of stating it as fact. '
        'Return strict JSON only with title, message, recommended_text, apply_target, apply_mode, reason, and reusable_pattern.\n\n'
        f'Role family: {suggestion.role_family}\n'
        f'Resume type: {suggestion.resume_type}\n'
        f'Section key: {section_key}\n'
        f'Suggestion type: {suggestion.suggestion_type}\n'
        f'Local suggestion disliked by user: {json.dumps(suggestion.local_suggestion_payload, ensure_ascii=True)[:2000]}\n'
        f'Relevant sanitized resume fields: {json.dumps(relevant, ensure_ascii=True)[:5000]}'
    )


def _relevant_payload_for_section(payload: dict, section_key: str) -> dict:
    basics = payload.get('basics') or {}
    common = {
        'headline': basics.get('headline', ''),
        'summary': basics.get('summary', ''),
        'skills': payload.get('skills') or [],
    }
    if section_key == 'basics':
        common['basics'] = {
            'headline': basics.get('headline', ''),
            'summary': basics.get('summary', ''),
            'location_present': bool(basics.get('location')),
            'email_present': bool(basics.get('email')),
            'phone_present': bool(basics.get('phone')),
        }
    elif section_key in payload:
        common[section_key] = payload.get(section_key) or []
    return common


def _professional_review_schema() -> dict:
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'title': {'type': 'string'},
            'message': {'type': 'string'},
            'recommended_text': {'type': 'string'},
            'apply_target': {'type': 'string'},
            'apply_mode': {'type': 'string', 'enum': ['replace', 'append', 'insert']},
            'reason': {'type': 'string'},
            'reusable_pattern': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'pattern_type': {'type': 'string'},
                    'template_text': {'type': 'string'},
                    'keywords': {'type': 'array', 'items': {'type': 'string'}},
                    'role_family': {'type': 'string'},
                    'section_key': {'type': 'string'},
                },
                'required': ['pattern_type', 'template_text', 'keywords', 'role_family', 'section_key'],
            },
        },
        'required': ['title', 'message', 'recommended_text', 'apply_target', 'apply_mode', 'reason', 'reusable_pattern'],
    }


def _normalize_professional_payload(payload: dict, suggestion: ResumeAiSuggestion) -> dict:
    allowed_modes = {'replace', 'append', 'insert'}
    normalized = {
        'title': str(payload.get('title') or 'Professional Review')[:180],
        'message': str(payload.get('message') or 'Professional suggestion is ready.')[:2000],
        'recommended_text': str(payload.get('recommended_text') or '')[:4000],
        'apply_target': str(payload.get('apply_target') or suggestion.local_suggestion_payload.get('apply_target') or '')[:120],
        'apply_mode': str(payload.get('apply_mode') or suggestion.local_suggestion_payload.get('apply_mode') or 'replace'),
        'reason': str(payload.get('reason') or '')[:1000],
        'reusable_pattern': payload.get('reusable_pattern') if isinstance(payload.get('reusable_pattern'), dict) else {},
    }
    if normalized['apply_mode'] not in allowed_modes:
        normalized['apply_mode'] = 'replace'
    return normalized


def _extract_output_text(payload: dict) -> str:
    if isinstance(payload.get('output_text'), str):
        return payload['output_text']
    for item in payload.get('output') or []:
        for content in item.get('content') or []:
            if content.get('type') in {'output_text', 'text'} and content.get('text'):
                return content['text']
    return ''


def _professional_review_error(error_code: str, message: str) -> dict:
    return {
        'success': False,
        'error_code': error_code,
        'message': message,
    }


def _sanitize_source_context(value: dict) -> dict:
    sanitized = {}
    for key, item in value.items():
        if key in {'name', 'email', 'phone', 'website', 'linkedin', 'github', 'portfolio'}:
            continue
        if isinstance(item, str):
            sanitized[key] = sanitize_learning_text(item)[:240]
        elif isinstance(item, (int, float, bool)):
            sanitized[key] = item
    return sanitized


def _contains_private_identifier(text: str) -> bool:
    if re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text):
        return True
    if re.search(r'https?://|www\.', text, flags=re.I):
        return True
    if re.search(r'\+?\d[\d\s().-]{7,}\d', text):
        return True
    return False


def _pattern_type_for_suggestion(suggestion_type: str) -> str:
    if suggestion_type == 'summary_improvement':
        return 'summary_template'
    if suggestion_type == 'headline_improvement':
        return 'headline_template'
    if suggestion_type == 'bullet_strengthening':
        return 'bullet_template'
    if suggestion_type == 'skills_focus':
        return 'keyword_bank'
    if suggestion_type == 'ats_readability':
        return 'weak_phrase_rule'
    return 'section_tip'


def _clean_identifier(value: str) -> str:
    return re.sub(r'[^a-z0-9_]+', '_', str(value or '').lower()).strip('_')[:80]


def _promote_similar_patterns(pattern: ResumeAiLearningPattern) -> None:
    min_sources = int(getattr(settings, 'RESUME_AI_MIN_PROMOTION_SOURCE_COUNT', 3))
    similar = ResumeAiLearningPattern.objects.filter(
        role_family=pattern.role_family,
        section_key=pattern.section_key,
        suggestion_type=pattern.suggestion_type,
        pattern_type=pattern.pattern_type,
        status=ResumeAiLearningPattern.Status.CANDIDATE,
    )
    total_sources = sum(item.source_count for item in similar)
    if total_sources < min_sources:
        return
    similar.update(
        status=ResumeAiLearningPattern.Status.TRUSTED,
        confidence_score=0.72,
    )


def _update_learning_from_feedback(suggestion: ResumeAiSuggestion, feedback: str) -> None:
    if not getattr(settings, 'RESUME_AI_LEARNING_ENABLED', True):
        return
    delta_applied = 1 if feedback in {ResumeAiFeedback.Feedback.APPLIED, ResumeAiFeedback.Feedback.LIKED} else 0
    delta_rejected = 1 if feedback in {ResumeAiFeedback.Feedback.IGNORED, ResumeAiFeedback.Feedback.NOT_USEFUL} else 0
    if not (delta_applied or delta_rejected):
        return
    patterns = ResumeAiLearningPattern.objects.filter(
        role_family__in=[suggestion.role_family, 'general'],
        section_key=suggestion.section_key,
        suggestion_type=suggestion.suggestion_type,
    )
    for pattern in patterns:
        pattern.applied_count += delta_applied
        pattern.rejected_count += delta_rejected
        pattern.confidence_score = max(0, min(0.95, pattern.confidence_score + (0.04 * delta_applied) - (0.07 * delta_rejected)))
        if pattern.rejected_count >= 5 and pattern.rejected_count > pattern.applied_count * 2:
            pattern.status = ResumeAiLearningPattern.Status.DISABLED
        pattern.save(update_fields=['applied_count', 'rejected_count', 'confidence_score', 'status', 'updated_at'])


def _update_patterns_from_professional_review(review: ResumeAiProfessionalReview, applied: bool) -> None:
    suggestion = review.suggestion
    reusable = review.professional_payload.get('reusable_pattern') if isinstance(review.professional_payload, dict) else {}
    pattern_type = _clean_identifier((reusable or {}).get('pattern_type') or _pattern_type_for_suggestion(suggestion.suggestion_type))
    patterns = ResumeAiLearningPattern.objects.filter(
        role_family__in=[suggestion.role_family, 'general'],
        section_key=suggestion.section_key,
        suggestion_type=suggestion.suggestion_type,
        pattern_type=pattern_type,
    )
    for pattern in patterns:
        if applied:
            pattern.applied_count += 1
            pattern.confidence_score = min(0.95, pattern.confidence_score + 0.08)
        else:
            pattern.rejected_count += 1
            pattern.confidence_score = max(0, pattern.confidence_score - 0.08)
        if pattern.rejected_count >= 5 and pattern.rejected_count > pattern.applied_count * 2:
            pattern.status = ResumeAiLearningPattern.Status.DISABLED
        pattern.save(update_fields=['applied_count', 'rejected_count', 'confidence_score', 'status', 'updated_at'])
        _promote_similar_patterns(pattern)


def _normalize(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').lower()).strip()
