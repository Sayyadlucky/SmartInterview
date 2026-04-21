import ast
import base64
import csv
import hashlib
import html
import io
import json
import logging
import mimetypes
import os
import random
import re
import string
import secrets
import signal
import subprocess
import tempfile
from urllib.parse import quote
from collections import Counter, defaultdict
from datetime import timedelta, datetime, time
from statistics import median

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core import signing
from django.core import serializers
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import LoginForm, CandidateSignupForm, CandidateLoginForm, CandidateProfileUpdateForm
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from .models import Interview
from .models import UserNotificationPreference, UserProfile, Vacancies
from django.db import DatabaseError, transaction
from django.db.models import Count, Case, When, CharField, Value, Q, F, Max, Min, DateTimeField
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from smartInterviewApp.integrations.providers.exotel import ExotelVoiceProvider
from smartInterviewApp.notifications.channels import send_sms, send_template_message
from smartInterviewApp.notifications.sms_templates import build_sms_message
from smartInterviewApp.emailing import send_candidate_interview_email, send_candidate_welcome_email
from smartInterviewApp.identity_verification import CandidateIdentityVerificationService
from smartInterviewApp.insights import CandidateInsightService
from smartInterviewApp.otp.services import request_email_otp, request_otp, verify_email_otp, verify_otp
from smartInterviewApp.resume_processing import ResumeProcessingService
from smartInterviewApp.services.ai_talent_pool import AiTalentPoolService
from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import RetrievalBackendUnavailable
from smartInterviewApp.services.interview_calls import InterviewCallService
from .models import AutoInterviewEvaluationResult, CandidateIdentityVerification, CandidateInsightSnapshot, CandidatePublicResume, CandidateResume, CandidateResumeBuilderDraft, CandidateSavedVacancy, CandidateVacancyApplication, CompanyProfile, InterviewCallSession
from .templatetags.host_links import build_host_link


SIGNUP_TOKEN_SALT = 'candidate-signup'
SIGNUP_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
PASSWORD_RESET_SESSION_KEY = 'candidate_password_reset'
PASSWORD_RESET_MAX_AGE_SECONDS = 60 * 15
PDF_RENDERER_PYTHON_CANDIDATES = [
    '/Users/sayyadlucky/PycharmProjects/smartvideo/.venv/bin/python',
]
PDF_BROWSER_CANDIDATES = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]
logger = logging.getLogger(__name__)
exotel_voice_provider = ExotelVoiceProvider()
interview_call_service = InterviewCallService()


def normalize_interview_status(value: str) -> str:
    raw = (value or '').strip().lower().replace('-', ' ').replace('_', ' ')
    raw = ' '.join(raw.split()).replace('assesment', 'assessment')
    status_map = {
        'scheduled': 'scheduled',
        'completed': 'completed',
        'cancelled': 'cancelled',
        'shortlisted': 'shortlisted',
        'offer made': 'offer_made',
        'offer accepted': 'offer_accepted',
        'offer declined': 'offer_declined',
        'hired': 'hired',
        'rejected': 'rejected',
        'assessment pending': 'assessment_pending',
        'assessment completed': 'assessment_completed',
        'auto screened': 'auto_screening_scheduled',
        'auto screening': 'auto_screening_scheduled',
        'auto screening scheduled': 'auto_screening_scheduled',
    }
    return status_map.get(raw, raw.replace(' ', '_'))


def normalize_phone(value: str) -> str:
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(digits) == 10:
        return f'91{digits}'
    return digits


def mask_phone_display(value: str) -> str:
    digits = normalize_phone(value)
    if len(digits) <= 4:
        return digits
    return f"{'•' * max(0, len(digits) - 4)}{digits[-4:]}"


def split_name(name: str) -> tuple[str, str]:
    parts = [part for part in (name or '').strip().split() if part]
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


def format_interview_schedule(value) -> tuple[str, str]:
    if not value:
        return '', ''
    localized = timezone.localtime(value)
    return localized.strftime('%d %b %Y'), localized.strftime('%I:%M %p')


def humanize_identifier(value: str) -> str:
    cleaned = (value or '').strip()
    if not cleaned:
        return ''
    cleaned = cleaned.split('@', 1)[0]
    cleaned = re.sub(r'[_\-.]+', ' ', cleaned)
    cleaned = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', cleaned)
    cleaned = re.sub(r'(?<=[A-Za-z])(?=[0-9])', ' ', cleaned)
    cleaned = re.sub(r'(?<=[0-9])(?=[A-Za-z])', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned.title()


def mask_phone_last_four(value: str) -> str:
    digits = normalize_phone(value)
    if not digits:
        return ''
    if len(digits) <= 4:
        return digits
    return f"{'•' * max(0, len(digits) - 4)}{digits[-4:]}"


def build_auto_interview_evaluation_summary(interview: Interview | None) -> dict:
    def trim_text(value, limit: int = 600) -> str:
        text = str(value or '').strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def compact_text_list(values, *, limit: int = 6, item_limit: int = 220) -> list[str]:
        if not isinstance(values, list):
            return []
        items: list[str] = []
        for value in values[:limit]:
            if isinstance(value, dict):
                parts = []
                for key, item_value in list(value.items())[:4]:
                    label = humanize_identifier(str(key))
                    if isinstance(item_value, list):
                        rendered = ', '.join(trim_text(entry, 80) for entry in item_value[:4] if str(entry or '').strip())
                    else:
                        rendered = trim_text(item_value, 120)
                    if rendered:
                        parts.append(f"{label}: {rendered}" if label else rendered)
                text = '; '.join(parts)
            else:
                text = trim_text(value, item_limit)
            if text:
                items.append(text)
        return items

    empty_payload = {
        'available': False,
        'decision': '',
        'recommendation': '',
        'score': None,
        'executive_summary': '',
        'summary_verdict': '',
        'confidence': '',
        'interview_signal_quality': '',
        'strengths': [],
        'concerns': [],
        'gaps': [],
        'notes': [],
        'follow_up_areas': [],
        'hire_recommendation_action': '',
        'hire_recommendation_reason': '',
        'early_exit': False,
        'early_exit_reason': '',
        'updated_at': '',
        'created_at': '',
    }
    if not interview:
        return empty_payload

    try:
        result = (
            AutoInterviewEvaluationResult.objects
            .filter(interview_id=interview.id)
            .only(
                'decision',
                'recommendation',
                'score',
                'executive_summary',
                'summary_verdict',
                'evaluation_payload',
                'early_exit',
                'early_exit_reason',
                'updated_at',
                'created_at',
            )
            .first()
        )
    except DatabaseError:
        return empty_payload

    if not result:
        return empty_payload

    evaluation_payload = result.evaluation_payload if isinstance(result.evaluation_payload, dict) else {}
    hire_recommendation = evaluation_payload.get('hire_recommendation')
    if not isinstance(hire_recommendation, dict):
        hire_recommendation = {}

    score_value = None
    if result.score is not None:
        try:
            score_value = float(result.score)
        except (TypeError, ValueError):
            score_value = None

    recommendation = trim_text(
        result.recommendation
        or hire_recommendation.get('action')
        or evaluation_payload.get('recommendation'),
        120,
    )

    return {
        'available': True,
        'decision': trim_text(result.decision, 60),
        'recommendation': recommendation,
        'score': score_value,
        'executive_summary': trim_text(
            result.executive_summary or evaluation_payload.get('summary') or evaluation_payload.get('overall_summary'),
            1800,
        ),
        'summary_verdict': trim_text(result.summary_verdict or evaluation_payload.get('summary_verdict'), 1200),
        'confidence': trim_text(evaluation_payload.get('confidence'), 80),
        'interview_signal_quality': trim_text(evaluation_payload.get('interview_signal_quality'), 80),
        'strengths': compact_text_list(evaluation_payload.get('strengths') or evaluation_payload.get('top_strengths')),
        'concerns': compact_text_list(evaluation_payload.get('concerns')),
        'gaps': compact_text_list(evaluation_payload.get('gaps') or evaluation_payload.get('weaknesses')),
        'notes': compact_text_list(evaluation_payload.get('notes')),
        'follow_up_areas': compact_text_list(evaluation_payload.get('follow_up_areas')),
        'hire_recommendation_action': trim_text(hire_recommendation.get('action'), 80),
        'hire_recommendation_reason': trim_text(hire_recommendation.get('reason'), 400),
        'early_exit': bool(result.early_exit),
        'early_exit_reason': trim_text(result.early_exit_reason, 160),
        'updated_at': result.updated_at.isoformat() if result.updated_at else '',
        'created_at': result.created_at.isoformat() if result.created_at else '',
    }


def candidate_password_reset_rate_limited(request, action: str, identifier: str, limit: int, window_seconds: int) -> bool:
    ip = (request.META.get('REMOTE_ADDR') or 'unknown').strip()
    digest = hashlib.sha256(f'{action}:{ip}:{identifier}'.encode('utf-8')).hexdigest()
    key = f'candidate-password-reset-rate:{digest}'
    current = cache.get(key, 0)
    if current >= limit:
        return True
    cache.set(key, current + 1, timeout=window_seconds)
    return False


def get_candidate_password_reset_state(request) -> dict | None:
    state = request.session.get(PASSWORD_RESET_SESSION_KEY)
    if not state:
        return None

    expires_at = state.get('expires_at')
    if not expires_at or timezone.now().timestamp() > float(expires_at):
        request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
        request.session.modified = True
        return None
    return state


def set_candidate_password_reset_state(request, state: dict) -> None:
    request.session[PASSWORD_RESET_SESSION_KEY] = state
    request.session.modified = True


def clear_candidate_password_reset_state(request) -> None:
    request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
    request.session.modified = True


def build_signup_context_from_user(user: User, profile: UserProfile | None, interview: Interview | None = None) -> dict:
    return {
        'user_id': user.id,
        'interview_id': interview.id if interview else None,
        'name': f"{user.first_name} {user.last_name}".strip(),
        'email': user.email or '',
        'phone': profile.phone if profile else '',
        'gender': profile.gender if profile else '',
        'role_id': interview.role_id if interview else None,
        'role_name': interview.role.role if interview and interview.role else '',
    }


def build_candidate_username(email: str, phone: str) -> str:
    base = (email.split('@', 1)[0] if email else '') or (phone[-10:] if phone else '') or 'candidate'
    base = re.sub(r'[^a-zA-Z0-9._-]+', '', base).strip('._-') or 'candidate'
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


def tokenize_text(value: str) -> set[str]:
    return {token for token in re.findall(r'[a-z0-9]+', (value or '').lower()) if len(token) > 1}


def clean_job_text(value: str, *, limit: int | None = None) -> str:
    text = html.unescape(str(value or ''))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if limit and len(text) > limit:
        return f"{text[:limit].rstrip()}..."
    return text


def clean_job_description(value: str, *, limit: int | None = None) -> str:
    return clean_job_text(value, limit=limit)


def split_job_description_points(value: str, *, limit: int = 4) -> list[str]:
    raw_text = html.unescape(str(value or '')).replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
    raw_text = raw_text.replace('\r', '\n')
    parts = [
        clean_job_text(piece)
        for piece in re.split(r'[\n;]+', raw_text)
    ]
    points: list[str] = []
    for part in parts:
        if len(part) < 3:
            continue
        if part in points:
            continue
        points.append(part)
        if len(points) >= limit:
            break
    if points:
        return points
    excerpt = clean_job_description(value, limit=180)
    return [excerpt] if excerpt else []


def normalize_posted_since_filter(value: str) -> str:
    allowed = {'1', '3', '7', '15', '30'}
    normalized = (value or '').strip()
    return normalized if normalized in allowed else ''


def vacancy_recruiter_names(vacancy: Vacancies) -> list[str]:
    return [
        f"{member.first_name} {member.last_name}".strip().title() or member.username
        for member in vacancy.recruiter.all()
    ]


def resolve_company_logo_url(company, *, include_external_logo: bool = True, request=None) -> str:
    if not company:
        return ''
    if getattr(company, 'logo', None):
        logo_url = reverse('company-logo-file', args=[company.id])
        if request:
            return request.build_absolute_uri(logo_url)
        return logo_url
    if include_external_logo:
        return company.logo_url or ''
    return ''


def serialize_company_summary(company, *, include_external_logo: bool = True, request=None) -> dict[str, object] | None:
    if not company:
        return None
    return {
        'id': company.id,
        'legal_name': company.legal_name,
        'display_name': company.display_name or company.legal_name,
        'industry': company.industry,
        'website': company.website,
        'logo_url': resolve_company_logo_url(company, include_external_logo=include_external_logo, request=request),
        'city': company.city,
        'state': company.state,
        'country': company.country,
        'headquarters': company.headquarters,
    }


def build_vacancy_card_payload(
    vacancy: Vacancies,
    *,
    application: CandidateVacancyApplication | None = None,
    is_saved: bool = False,
    include_external_company_logo: bool = True,
    request=None,
) -> dict[str, object]:
    recruiter_names = vacancy_recruiter_names(vacancy)
    clean_description = clean_job_description(vacancy.description)
    application_status = application.status if application else ''
    posted_at = vacancy.date or timezone.now()
    company = getattr(vacancy, 'company', None) or getattr(getattr(vacancy, 'admin', None), 'company_profile', None)
    return {
        'id': vacancy.id,
        'role': clean_job_text(vacancy.role),
        'position': clean_job_text(vacancy.position),
        'job_type': clean_job_text(vacancy.get_job_type_display() if vacancy.job_type else ''),
        'location': clean_job_text(vacancy.location),
        'salary_range': clean_job_text(vacancy.salary_range),
        'experience_required': clean_job_text(vacancy.experience_required),
        'status': vacancy.status,
        'status_label': vacancy.status.replace('_', ' ').title(),
        'date': posted_at,
        'date_iso': posted_at.strftime('%Y-%m-%d'),
        'date_display': posted_at.strftime('%b %d, %Y'),
        'description': clean_description,
        'description_preview': clean_job_description(vacancy.description, limit=220),
        'highlights': split_job_description_points(vacancy.description),
        'recruiters': recruiter_names[:3],
        'recruiter_name': recruiter_names[0] if recruiter_names else '',
        'admin_name': (
            f"{vacancy.admin.first_name} {vacancy.admin.last_name}".strip().title() or vacancy.admin.username
            if vacancy.admin else ''
        ),
        'company': serialize_company_summary(company, include_external_logo=include_external_company_logo, request=request),
        'application_status': application_status,
        'application_label': application_status.replace('_', ' ').title() if application_status else 'Apply Now',
        'has_applied': application_status in {
            CandidateVacancyApplication.Status.PENDING_REVIEW,
            CandidateVacancyApplication.Status.APPROVED,
        },
        'can_cancel_application': application_status in {
            CandidateVacancyApplication.Status.PENDING_REVIEW,
            CandidateVacancyApplication.Status.APPROVED,
        },
        'is_hidden_for_candidate': application_status == CandidateVacancyApplication.Status.NOT_INTERESTED,
        'is_saved': is_saved,
    }


def build_public_jobs_context(request) -> dict[str, object]:
    default_jobs_limit = 10
    q = (request.GET.get('q') or '').strip()
    recruiter_filter = (request.GET.get('recruiter') or '').strip()
    posted_since = normalize_posted_since_filter(request.GET.get('posted'))
    sort = (request.GET.get('sort') or 'recent').strip().lower()
    if sort not in {'recent', 'oldest', 'role'}:
        sort = 'recent'

    jobs_qs = (
        Vacancies.objects
        .select_related('admin', 'company')
        .prefetch_related('recruiter')
        .exclude(status__in=['closed', 'canceled', 'hired'])
        .order_by('-date', '-id')
    )

    if posted_since:
        jobs_qs = jobs_qs.filter(date__gte=timezone.now() - timedelta(days=int(posted_since)))

    if q:
        jobs_qs = jobs_qs.filter(
            Q(role__icontains=q)
            | Q(description__icontains=q)
            | Q(position__icontains=q)
            | Q(recruiter__first_name__icontains=q)
            | Q(recruiter__last_name__icontains=q)
            | Q(admin__first_name__icontains=q)
            | Q(admin__last_name__icontains=q)
        ).distinct()

    if recruiter_filter:
        jobs_qs = jobs_qs.filter(
            Q(recruiter__username__iexact=recruiter_filter)
            | Q(recruiter__first_name__iexact=recruiter_filter)
            | Q(recruiter__last_name__iexact=recruiter_filter)
        ).distinct()

    should_limit_default_feed = not q and not recruiter_filter and not posted_since and sort == 'recent'
    if should_limit_default_feed:
        jobs_qs = jobs_qs[:default_jobs_limit]

    application_lookup: dict[int, CandidateVacancyApplication] = {}
    saved_vacancy_ids: set[int] = set()
    profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None
    is_candidate = bool(profile and profile.role == 'candidate')
    if is_candidate:
        application_lookup = {
            application.vacancy_id: application
            for application in CandidateVacancyApplication.objects.filter(candidate=request.user)
        }
        saved_vacancy_ids = set(
            CandidateSavedVacancy.objects.filter(candidate=request.user).values_list('vacancy_id', flat=True)
        )

    job_cards = [
        build_vacancy_card_payload(
            vacancy,
            application=application_lookup.get(vacancy.id),
            is_saved=vacancy.id in saved_vacancy_ids,
            request=request,
        )
        for vacancy in jobs_qs
    ]
    if is_candidate:
        job_cards = [card for card in job_cards if not card['is_hidden_for_candidate']]

    saved_job_cards: list[dict[str, object]] = []
    if is_candidate and saved_vacancy_ids:
        saved_vacancies_qs = (
            Vacancies.objects
            .select_related('admin')
            .prefetch_related('recruiter')
            .filter(id__in=saved_vacancy_ids)
            .exclude(status__in=['closed', 'canceled', 'hired'])
            .order_by('-date', '-id')
        )
        saved_job_cards = [
            build_vacancy_card_payload(
                vacancy,
                application=application_lookup.get(vacancy.id),
                is_saved=True,
                request=request,
            )
            for vacancy in saved_vacancies_qs
            if vacancy.id not in {
                vacancy_id
                for vacancy_id, application in application_lookup.items()
                if application.status == CandidateVacancyApplication.Status.NOT_INTERESTED
            }
        ]

    if sort == 'oldest':
        job_cards.sort(key=lambda item: (item['date'], item['id']))
    elif sort == 'role':
        job_cards.sort(key=lambda item: (str(item['role']).lower(), -item['id']))
    else:
        job_cards.sort(key=lambda item: (item['date'], item['id']), reverse=True)

    recruiter_choices = sorted({
        recruiter.username: f"{recruiter.first_name} {recruiter.last_name}".strip().title() or recruiter.username
        for vacancy in Vacancies.objects.exclude(status__in=['closed', 'canceled', 'hired']).prefetch_related('recruiter')
        for recruiter in vacancy.recruiter.all()
    }.items(), key=lambda item: item[1].lower())

    login_url = reverse('candidate-login')
    if request.get_full_path():
        login_url = f"{login_url}?next={quote(request.get_full_path(), safe='/?:=&')}"

    return {
        'job_cards': job_cards,
        'job_count': len(job_cards),
        'saved_job_cards': saved_job_cards,
        'saved_job_count': len(saved_job_cards),
        'filters': {
            'q': q,
            'recruiter': recruiter_filter,
            'posted': posted_since,
            'sort': sort,
        },
        'recruiter_choices': [{'value': value, 'label': label} for value, label in recruiter_choices],
        'is_candidate_user': is_candidate,
        'is_authenticated': request.user.is_authenticated,
        'candidate_login_url': login_url,
    }


def is_identity_verified(record: CandidateIdentityVerification | None) -> bool:
    if not record:
        return False
    return record.status in {
        CandidateIdentityVerification.Status.XML_VERIFIED,
        CandidateIdentityVerification.Status.DOCUMENT_MATCHED,
    }


def generate_litio_interview_code(length: int = 8) -> str:
    alphabet = '23456789abcdefghjkmnpqrstuvwxyz'
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if not Interview.objects.filter(litio_interview_token=code).exists():
            return code


def is_compact_litio_interview_code(token: str) -> bool:
    value = (token or '').strip().lower()
    return bool(re.fullmatch(r'[23456789abcdefghjkmnpqrstuvwxyz]{6,16}', value))


def ensure_litio_interview_token(interview: Interview) -> str:
    token = (interview.litio_interview_token or '').strip()
    if token and is_compact_litio_interview_code(token):
        return token

    token = generate_litio_interview_code()
    interview.litio_interview_token = token
    interview.save(update_fields=['litio_interview_token'])
    return token


def get_litio_interview_by_token(token: str) -> Interview | None:
    value = (token or '').strip()
    if not value:
        return None
    return (
        Interview.objects.select_related('candidate', 'recruiter', 'interviewer', 'role')
        .filter(litio_interview_token=value)
        .first()
    )


def build_litio_interview_link(request, interview: Interview) -> tuple[str, str]:
    token = ensure_litio_interview_token(interview)
    base_url = getattr(settings, 'LITIO_PUBLIC_BASE_URL', 'https://litio.shortlistii.com').rstrip('/')
    return token, f'{base_url}/i/{token}'


def build_candidate_details(candidate: Interview, request=None) -> dict:
    recruiter_name = (
        f"{candidate.recruiter.first_name} {candidate.recruiter.last_name}".strip().title()
        if candidate.recruiter else ''
    )
    interviewer_name = (
        f"{candidate.interviewer.first_name} {candidate.interviewer.last_name}".strip().title()
        if getattr(candidate, 'interviewer', None) else ''
    )
    interview_token, interview_link = build_litio_interview_link(request, candidate)
    return {
        'id': candidate.id,
        'name': f"{candidate.candidate.first_name} {candidate.candidate.last_name}".strip().title(),
        'email': candidate.candidate.email,
        'phone': candidate.candidate.profile.phone if hasattr(candidate.candidate, 'profile') else '',
        'candidate_id': candidate.candidate_id,
        'recruiter': recruiter_name,
        'recruiter_id': candidate.recruiter_id,
        'interviewer': interviewer_name,
        'interviewer_id': candidate.interviewer_id,
        'interview_type': getattr(candidate, 'interview_type', 'manual'),
        'status': candidate.status,
        'score': candidate.score,
        'recording_url': candidate.recording_url,
        'notes': candidate.notes,
        'date': candidate.date,
        'role': candidate.role.role if candidate.role else '',
        'role_id': candidate.role.id if candidate.role else None,
        'interview_token': interview_token,
        'interview_link': interview_link,
    }


def get_display_name(user: User) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()
    if full_name:
        return full_name.title()
    fallback = humanize_identifier(user.email) or humanize_identifier(user.username)
    if fallback:
        return fallback
    return user.username or user.email or ''


def get_user_role(user: User) -> str:
    return getattr(getattr(user, 'profile', None), 'role', '')


def get_admin_for_user(user: User) -> User | None:
    role = get_user_role(user)
    if role == 'admin':
        return user
    profile = getattr(user, 'profile', None)
    if not profile:
        return None
    if role == 'recruiter':
        return profile.hr
    if role == 'interviewer':
        if profile.hr:
            return profile.hr
        recruiter = profile.recruiter
        recruiter_profile = getattr(recruiter, 'profile', None) if recruiter else None
        return recruiter_profile.hr if recruiter_profile else None
    return profile.hr


def get_accessible_interviews(request_user: User):
    role = get_user_role(request_user)
    base_qs = Interview.objects.select_related('candidate', 'recruiter', 'interviewer', 'role')
    if role == 'admin':
        return base_qs.filter(hr=request_user)
    if role == 'recruiter':
        return base_qs.filter(Q(recruiter=request_user) | Q(interviewer__profile__recruiter=request_user)).distinct()
    if role == 'interviewer':
        return base_qs.filter(interviewer=request_user)
    return base_qs.none()


def get_accessible_interviewer_profiles(request_user: User):
    role = get_user_role(request_user)
    qs = UserProfile.objects.select_related('user', 'recruiter', 'hr').filter(role='interviewer')
    if role == 'admin':
        return qs.filter(
            Q(recruiter__profile__hr=request_user)
            | Q(user__interviewer_interviews__hr=request_user)
        ).distinct()
    if role == 'recruiter':
        return qs.filter(
            Q(recruiter=request_user)
            | Q(user__interviewer_interviews__recruiter=request_user)
        ).distinct()
    return qs.none()


def resolve_application_hiring_started_at(candidate_id: int, vacancy_id: int):
    application_start = (
        CandidateVacancyApplication.objects
        .filter(candidate_id=candidate_id, vacancy_id=vacancy_id)
        .exclude(hiring_started_at__isnull=True)
        .order_by('hiring_started_at')
        .values_list('hiring_started_at', flat=True)
        .first()
    )
    if application_start:
        return application_start

    applied_at = (
        CandidateVacancyApplication.objects
        .filter(candidate_id=candidate_id, vacancy_id=vacancy_id)
        .exclude(applied_at__isnull=True)
        .order_by('applied_at')
        .values_list('applied_at', flat=True)
        .first()
    )
    if applied_at:
        return applied_at

    created_at = (
        CandidateVacancyApplication.objects
        .filter(candidate_id=candidate_id, vacancy_id=vacancy_id)
        .exclude(created_at__isnull=True)
        .order_by('created_at')
        .values_list('created_at', flat=True)
        .first()
    )
    if created_at:
        return created_at

    # `Interview.date` is only a constrained fallback for TTH start because the
    # Interview model does not have a canonical cycle-start timestamp.
    return (
        Interview.objects
        .filter(candidate_id=candidate_id, role_id=vacancy_id)
        .exclude(status__in=['hired', 'completed'])
        .exclude(date__isnull=True)
        .order_by('date')
        .values_list('date', flat=True)
        .first()
    )


def ensure_application_hiring_started_at(application: CandidateVacancyApplication) -> None:
    resolved_start = resolve_application_hiring_started_at(application.candidate_id, application.vacancy_id)
    if not resolved_start:
        return

    current_start = application.hiring_started_at
    if current_start and current_start <= resolved_start:
        return

    application.hiring_started_at = resolved_start
    application.save(update_fields=['hiring_started_at', 'updated_at'])


def ensure_application_pipeline_source(
    application: CandidateVacancyApplication,
    pipeline_source: str | None = None,
) -> None:
    resolved_source = pipeline_source
    if not resolved_source and application.source == 'candidate_dashboard':
        resolved_source = CandidateVacancyApplication.PipelineSource.SELF_APPLIED

    if not resolved_source:
        return
    if application.pipeline_source == resolved_source:
        return
    if application.pipeline_source:
        return

    application.pipeline_source = resolved_source
    application.save(update_fields=['pipeline_source', 'updated_at'])


def ensure_pipeline_application(
    candidate: User,
    vacancy: Vacancies,
    pipeline_source: str | None = None,
) -> CandidateVacancyApplication:
    resolved_source = pipeline_source or ''
    application, _created = CandidateVacancyApplication.objects.get_or_create(
        candidate=candidate,
        vacancy=vacancy,
        defaults={
            'status': CandidateVacancyApplication.Status.APPROVED,
            'pipeline_source': resolved_source,
        },
    )
    if application.status != CandidateVacancyApplication.Status.APPROVED:
        application.status = CandidateVacancyApplication.Status.APPROVED
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'reviewed_at', 'updated_at'])
    ensure_application_pipeline_source(application, pipeline_source)
    ensure_application_hiring_started_at(application)
    return application


@login_required
def workflowEvaluatorOptions(request):
    try:
        current_user = get_object_or_404(User, username=request.user.username)
        evaluator_profiles = get_accessible_interviewer_profiles(current_user).exclude(user__username__iexact='TBD')

        evaluator_list = []
        for profile in evaluator_profiles.order_by('user__first_name', 'user__last_name'):
            evaluator_list.append({
                'id': profile.user_id,
                'user_id': profile.user_id,
                'name': get_display_name(profile.user),
                'email': profile.user.email,
                'phone': profile.phone,
                'recruiter_id': profile.recruiter_id,
                'recruiter_name': get_display_name(profile.recruiter) if profile.recruiter else '',
            })
        return JsonResponse({"Success": True, "Error": None, "EvaluatorData": evaluator_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "EvaluatorData": []})


def resolve_interview_assignment(operator: User, selected_user_id: str) -> tuple[User | None, User | None, User | None]:
    selected_user = None
    if selected_user_id:
        selected_user = User.objects.filter(id=selected_user_id).select_related('profile').first()

    operator_role = get_user_role(operator)
    operator_profile = getattr(operator, 'profile', None)
    admin_user = get_admin_for_user(operator)
    recruiter_user = operator if operator_role == 'recruiter' else None
    interviewer_user = operator if operator_role == 'interviewer' else None

    if selected_user:
        selected_role = get_user_role(selected_user)
        selected_profile = getattr(selected_user, 'profile', None)
        if selected_role == 'recruiter':
            recruiter_user = selected_user
            admin_user = selected_profile.hr or admin_user
            interviewer_user = None
        elif selected_role == 'interviewer':
            interviewer_user = selected_user
            recruiter_user = selected_profile.recruiter or recruiter_user
            admin_user = selected_profile.hr or get_admin_for_user(selected_user) or admin_user

    if interviewer_user and recruiter_user is None:
        interviewer_profile = getattr(interviewer_user, 'profile', None)
        recruiter_user = interviewer_profile.recruiter if interviewer_profile else None

    if admin_user is None and recruiter_user is not None:
        recruiter_profile = getattr(recruiter_user, 'profile', None)
        admin_user = recruiter_profile.hr if recruiter_profile else None

    if admin_user is None and operator_profile:
        admin_user = operator_profile.hr

    return admin_user, recruiter_user, interviewer_user


def get_latest_candidate_interview(user: User) -> Interview | None:
    return (
        Interview.objects
        .select_related('role', 'recruiter')
        .filter(candidate=user)
        .order_by('-date', '-id')
        .first()
    )


def ensure_public_resume(candidate: User) -> CandidatePublicResume:
    public_resume = CandidatePublicResume.objects.filter(candidate=candidate).first()
    if public_resume:
        if not public_resume.short_code:
            public_resume.short_code = generate_public_resume_code()
            public_resume.save(update_fields=['short_code', 'updated_at'])
        return public_resume

    return CandidatePublicResume.objects.create(
        candidate=candidate,
        short_code=generate_public_resume_code(),
        is_active=True,
    )


def generate_public_resume_code(length: int = 8) -> str:
    alphabet = '23456789abcdefghjkmnpqrstuvwxyz'
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if not CandidatePublicResume.objects.filter(short_code=code).exists():
            return code


def extract_resume_section_text(section: dict) -> str:
    content = section.get('content') or {}
    text = (content.get('text') or section.get('raw_text') or '').strip()
    if text:
        return text

    items = content.get('items') or []
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            clean = item.strip()
            if clean:
                lines.append(clean)
            continue
        if not isinstance(item, dict):
            continue
        primary = (
            item.get('title')
            or item.get('degree')
            or item.get('label')
            or item.get('institution')
            or item.get('company')
            or item.get('description')
            or ''
        )
        if primary:
            lines.append(str(primary).strip())
        for key in ('company', 'duration', 'location', 'role', 'institution', 'issuer', 'value'):
            value = str(item.get(key) or '').strip()
            if value and value not in lines:
                lines.append(value)
        for detail in item.get('details') or []:
            clean_detail = str(detail or '').strip()
            if clean_detail:
                lines.append(clean_detail)
    return '\n'.join(lines).strip()


def normalize_public_section_item(item):
    if isinstance(item, str):
        parsed_item = _parse_serialized_section_item(item)
        if isinstance(parsed_item, dict):
            return normalize_public_section_item(parsed_item)
        text = item.strip()
        if not text:
            return ''
        return {
            'title': '',
            'degree': '',
            'label': '',
            'value': text,
            'company': '',
            'institution': '',
            'issuer': '',
            'location': '',
            'role': '',
            'description': text,
            'duration': '',
            'duration_text': '',
            'start_date': '',
            'end_date': '',
            'employment_type': '',
            'is_current': False,
            'tech_stack': [],
            'details': [],
            'notes': [],
        }
    if not isinstance(item, dict):
        return ''

    parsed_description = _parse_serialized_section_item(item.get('description'))
    if isinstance(parsed_description, dict):
        merged_item = dict(parsed_description)
        merged_item.update({key: value for key, value in item.items() if key != 'description'})
        item = merged_item

    details = item.get('details') or item.get('bullets') or []
    if not isinstance(details, list):
        details = [details] if details else []
    notes = item.get('notes') or []
    if not isinstance(notes, list):
        notes = [notes] if notes else []

    start_date = str(item.get('start_date') or '').strip()
    end_date = str(item.get('end_date') or '').strip()
    duration = str(item.get('duration') or item.get('duration_text') or '').strip()
    if not duration and start_date and end_date:
        duration = f'{start_date} - {end_date}'
    elif not duration:
        duration = start_date or end_date

    normalized = {
        'title': str(item.get('title') or '').strip(),
        'degree': str(item.get('degree') or '').strip(),
        'label': str(item.get('label') or '').strip(),
        'value': str(item.get('value') or '').strip(),
        'company': str(item.get('company') or '').strip(),
        'institution': str(item.get('institution') or '').strip(),
        'issuer': str(item.get('issuer') or '').strip(),
        'location': str(item.get('location') or '').strip(),
        'role': str(item.get('role') or '').strip(),
        'description': str(item.get('description') or '').strip(),
        'duration': duration,
        'duration_text': str(item.get('duration_text') or '').strip(),
        'start_date': start_date,
        'end_date': end_date,
        'employment_type': str(item.get('employment_type') or '').strip(),
        'is_current': bool(item.get('is_current')),
        'tech_stack': [str(value).strip() for value in (item.get('tech_stack') or []) if str(value).strip()],
        'details': [str(value).strip() for value in details if str(value).strip()],
        'notes': [str(value).strip() for value in notes if str(value).strip()],
    }
    return normalized


def _parse_serialized_section_item(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text[0] not in '{[':
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except (ValueError, SyntaxError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def build_absolute_file_url(request, file_field) -> str:
    try:
        return request.build_absolute_uri(file_field.url) if file_field else ''
    except Exception:
        return ''


def build_public_resume_context(request, candidate: User) -> dict:
    profile = getattr(candidate, 'profile', None)
    latest_resume = (
        CandidateResume.objects
        .filter(candidate=candidate, is_active=True)
        .prefetch_related('sections')
        .first()
    )
    resume_data = ResumeProcessingService().serialize_resume(latest_resume)
    public_resume = ensure_public_resume(candidate)
    profile_picture_url = build_absolute_file_url(request, getattr(profile, 'profile_picture', None))
    profile_picture_data_url = ''
    if profile and profile.profile_picture:
        try:
            mime_type, _ = mimetypes.guess_type(profile.profile_picture.name or '')
            with profile.profile_picture.open('rb') as image_handle:
                encoded = base64.b64encode(image_handle.read()).decode('ascii')
            profile_picture_data_url = f"data:{mime_type or 'image/jpeg'};base64,{encoded}"
        except Exception:
            profile_picture_data_url = ''
    share_url = request.build_absolute_uri(reverse('public-candidate-resume', args=[public_resume.short_code]))

    sections = []
    for section in resume_data.get('sections') or []:
        section_text = extract_resume_section_text(section)
        raw_items = ((section.get('content') or {}).get('items') or [])
        normalized_items = []
        for item in raw_items:
            normalized_item = normalize_public_section_item(item)
            if normalized_item:
                normalized_items.append(normalized_item)
        sections.append({
            'title': section.get('title') or 'Section',
            'section_key': section.get('section_key') or '',
            'text': section_text,
            'items': normalized_items,
        })

    experience_section = next((section for section in sections if (section.get('section_key') or '').lower() in {'experience', 'work_history'}), None)
    education_section = next((section for section in sections if (section.get('section_key') or '').lower() in {'education', 'academics'}), None)

    return {
        'candidate': {
            'name': f"{candidate.first_name} {candidate.last_name}".strip().title() or candidate.username,
            'email': candidate.email,
            'phone': profile.phone if profile else '',
            'gender': (profile.gender or '').title() if profile and profile.gender else '',
            'profile_picture_url': profile_picture_url,
            'profile_picture_data_url': profile_picture_data_url,
        },
        'resume': {
            'headline': resume_data.get('headline', ''),
            'summary': resume_data.get('summary', ''),
            'skills': resume_data.get('skills') or [],
            'sections': sections,
            'processed_at': resume_data.get('processed_at', ''),
            'source_file': resume_data.get('source_file', ''),
        },
        'highlights': {
            'experience_years': latest_resume.total_experience_years if latest_resume else None,
            'current_title': latest_resume.current_title if latest_resume else '',
            'current_company': latest_resume.current_company if latest_resume else '',
            'experience_preview': experience_section,
            'education_preview': education_section,
        },
        'share': {
            'short_code': public_resume.short_code,
            'share_url': share_url,
            'word_url': request.build_absolute_uri(reverse('public-candidate-resume-word', args=[public_resume.short_code])),
            'pdf_url': request.build_absolute_uri(reverse('public-candidate-resume-pdf', args=[public_resume.short_code])),
        },
    }


def _resume_builder_default_payload(user: User, profile: UserProfile) -> dict:
    return {
        'basics': {
            'name': f"{user.first_name} {user.last_name}".strip().title() or user.username,
            'email': user.email or '',
            'phone': profile.phone or '',
            'location': '',
            'headline': '',
            'summary': '',
            'website': '',
            'linkedin': '',
            'github': '',
            'portfolio': '',
        },
        'skills': [],
        'experience': [],
        'projects': [],
        'education': [],
        'certifications': [],
        'achievements': [],
        'languages': [],
    }


def _resume_builder_preview_payload() -> dict:
    return {
        'basics': {
            'name': 'Aarav Mehta',
            'email': 'aarav.mehta@example.com',
            'phone': '+91 98765 43210',
            'location': 'Pune, India',
            'headline': 'Product Analyst | SaaS | SQL | Stakeholder Reporting',
            'summary': 'Analytical product and operations professional with experience translating business problems into measurable process and reporting improvements. Builds clear dashboards, streamlines workflows, and partners with cross-functional teams to deliver decisions faster.',
            'website': '',
            'linkedin': 'https://linkedin.com/in/aaravmehta',
            'github': '',
            'portfolio': '',
        },
        'skills': ['SQL', 'Excel', 'Power BI', 'Product Analytics', 'Stakeholder Management', 'Process Improvement'],
        'experience': [
            {
                'title': 'Product Analyst',
                'company': 'Northstar SaaS',
                'location': 'Pune',
                'duration': '2023 - Present',
                'role': 'Analytics and Business Operations',
                'description': '',
                'tech_stack': ['SQL', 'Power BI', 'Excel'],
                'details': [
                    'Built weekly reporting that reduced manual status preparation for leadership reviews.',
                    'Tracked funnel drop-offs and surfaced product insights that improved team prioritization.',
                    'Partnered with product and operations teams to define cleaner reporting metrics.',
                ],
            }
        ],
        'projects': [
            {
                'title': 'Customer Retention Dashboard',
                'company': 'Portfolio Project',
                'duration': '2024',
                'role': 'Data and Reporting',
                'description': 'Retention performance dashboard built to surface churn trends, cohort movement, and account health signals.',
                'tech_stack': ['SQL', 'Power BI'],
                'details': [
                    'Mapped account lifecycle metrics into a single review view for weekly reporting.',
                    'Used cohort-based analysis to highlight retention patterns across customer segments.',
                ],
            }
        ],
        'education': [
            {
                'degree': 'B.Tech in Information Technology',
                'institution': 'Pune University',
                'location': 'Pune',
                'duration': '2022',
                'details': ['Coursework focused on data analysis, systems design, and software fundamentals.'],
            }
        ],
        'certifications': [
            {
                'label': 'Google Data Analytics Certificate',
                'issuer': 'Google',
                'duration': '2024',
                'value': 'Credential available on request',
            }
        ],
        'achievements': [
            {
                'label': 'Operations Excellence Recognition',
                'issuer': 'Northstar SaaS',
                'duration': '2024',
                'value': 'Recognized for improving reporting turnaround time',
            }
        ],
        'languages': [
            {
                'label': 'English',
                'value': 'Professional proficiency',
            },
            {
                'label': 'Hindi',
                'value': 'Native proficiency',
            }
        ],
    }


def _resume_builder_clean_text(value, limit: int = 255) -> str:
    return str(value or '').strip()[:limit]


def _resume_builder_clean_list(values, *, limit: int = 12, item_limit: int = 80) -> list[str]:
    if isinstance(values, str):
        source_items = re.split(r'[\n,]+', values)
    elif isinstance(values, list):
        source_items = values
    else:
        source_items = []
    cleaned: list[str] = []
    for value in source_items:
        text = _resume_builder_clean_text(value, item_limit)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _resume_builder_clean_items(values, *, limit: int = 8) -> list[dict]:
    if not isinstance(values, list):
        return []
    cleaned_items: list[dict] = []
    for value in values[:limit]:
        normalized = normalize_public_section_item(value)
        if not normalized:
            continue
        item = {
            'title': _resume_builder_clean_text(normalized.get('title'), 180),
            'degree': _resume_builder_clean_text(normalized.get('degree'), 180),
            'label': _resume_builder_clean_text(normalized.get('label'), 180),
            'value': _resume_builder_clean_text(normalized.get('value'), 220),
            'company': _resume_builder_clean_text(normalized.get('company'), 180),
            'institution': _resume_builder_clean_text(normalized.get('institution'), 180),
            'issuer': _resume_builder_clean_text(normalized.get('issuer'), 180),
            'location': _resume_builder_clean_text(normalized.get('location'), 180),
            'role': _resume_builder_clean_text(normalized.get('role'), 180),
            'description': _resume_builder_clean_text(normalized.get('description'), 1200),
            'duration': _resume_builder_clean_text(normalized.get('duration'), 120),
            'duration_text': _resume_builder_clean_text(normalized.get('duration_text'), 120),
            'start_date': _resume_builder_clean_text(normalized.get('start_date'), 40),
            'end_date': _resume_builder_clean_text(normalized.get('end_date'), 40),
            'employment_type': _resume_builder_clean_text(normalized.get('employment_type'), 80),
            'is_current': bool(normalized.get('is_current')),
            'tech_stack': _resume_builder_clean_list(normalized.get('tech_stack'), limit=12, item_limit=60),
            'details': _resume_builder_clean_list(normalized.get('details'), limit=8, item_limit=240),
            'notes': _resume_builder_clean_list(normalized.get('notes'), limit=6, item_limit=180),
        }
        if any(item.get(key) for key in ('title', 'degree', 'label', 'value', 'company', 'institution', 'issuer', 'location', 'role', 'description', 'duration')) or item['tech_stack'] or item['details'] or item['notes']:
            cleaned_items.append(item)
    return cleaned_items


def _resume_builder_filter_section_items(items: list[dict], *, section_key: str) -> list[dict]:
    if section_key == 'projects':
        return [
            item for item in items
            if any(item.get(key) for key in ('title', 'company', 'description', 'value', 'label'))
        ]
    if section_key == 'education':
        return [
            item for item in items
            if any(item.get(key) for key in ('degree', 'institution', 'description', 'value', 'label'))
        ]
    return items


def _resume_builder_extract_items(resume_data: dict, keys: set[str]) -> list[dict]:
    for section in (resume_data.get('sections') or []):
        section_key = str(section.get('section_key') or '').strip().lower()
        if section_key in keys:
            return _resume_builder_clean_items((section.get('content') or {}).get('items') or section.get('items') or [])
    return []


def _resume_builder_extract_links(contact_links) -> dict[str, str]:
    resolved = {
        'website': '',
        'linkedin': '',
        'github': '',
        'portfolio': '',
    }
    if not isinstance(contact_links, list):
        return resolved
    for entry in contact_links:
        if isinstance(entry, dict):
            label = _resume_builder_clean_text(entry.get('label') or entry.get('title') or entry.get('type') or '', 80).lower()
            value = _resume_builder_clean_text(entry.get('url') or entry.get('value') or entry.get('href') or '', 255)
        else:
            label = str(entry or '').strip().lower()
            value = _resume_builder_clean_text(entry, 255)
        if not value:
            continue
        if 'linkedin' in label or 'linkedin.com' in value.lower():
            resolved['linkedin'] = resolved['linkedin'] or value
        elif 'github' in label or 'github.com' in value.lower():
            resolved['github'] = resolved['github'] or value
        elif 'portfolio' in label or 'behance' in value.lower() or 'dribbble' in value.lower():
            resolved['portfolio'] = resolved['portfolio'] or value
        else:
            resolved['website'] = resolved['website'] or value
    return resolved


def build_resume_builder_payload(user: User, profile: UserProfile) -> dict:
    draft = getattr(user, 'resume_builder_draft', None)
    if draft and isinstance(draft.payload, dict) and draft.payload:
        return sanitize_resume_builder_payload(draft.payload, user=user, profile=profile)

    payload = _resume_builder_default_payload(user, profile)
    latest_resume = (
        CandidateResume.objects
        .filter(candidate=user, is_active=True)
        .prefetch_related('sections')
        .first()
    )
    if not latest_resume:
        return payload

    resume_data = ResumeProcessingService().serialize_resume(latest_resume)
    contact = resume_data.get('contact') or {}
    link_values = _resume_builder_extract_links(contact.get('links') or [])
    payload['basics'].update({
        'name': _resume_builder_clean_text(contact.get('name') or payload['basics']['name'], 180),
        'email': _resume_builder_clean_text(contact.get('email') or resume_data.get('email') or payload['basics']['email'], 180),
        'phone': _resume_builder_clean_text(contact.get('phone') or resume_data.get('phone') or payload['basics']['phone'], 40),
        'location': _resume_builder_clean_text(contact.get('location') or resume_data.get('location') or '', 180),
        'headline': _resume_builder_clean_text(resume_data.get('headline'), 180),
        'summary': _resume_builder_clean_text(resume_data.get('summary') or resume_data.get('objective'), 2000),
        'website': link_values['website'],
        'linkedin': link_values['linkedin'],
        'github': link_values['github'],
        'portfolio': link_values['portfolio'],
    })
    payload['skills'] = _resume_builder_clean_list(resume_data.get('skills'), limit=24, item_limit=80)
    payload['experience'] = _resume_builder_filter_section_items(_resume_builder_clean_items(
        resume_data.get('experience') or _resume_builder_extract_items(resume_data, {'experience', 'work_history', 'professional_experience'}),
        limit=8,
    ), section_key='experience')
    payload['projects'] = _resume_builder_filter_section_items(_resume_builder_clean_items(
        resume_data.get('projects') or _resume_builder_extract_items(resume_data, {'projects', 'project'}),
        limit=6,
    ), section_key='projects')
    payload['education'] = _resume_builder_filter_section_items(_resume_builder_clean_items(
        resume_data.get('education') or _resume_builder_extract_items(resume_data, {'education', 'academics'}),
        limit=5,
    ), section_key='education')
    payload['certifications'] = _resume_builder_filter_section_items(_resume_builder_clean_items(
        resume_data.get('certifications') or _resume_builder_extract_items(resume_data, {'certifications', 'licenses'}),
        limit=6,
    ), section_key='certifications')
    payload['achievements'] = _resume_builder_filter_section_items(_resume_builder_clean_items(
        resume_data.get('achievements') or _resume_builder_extract_items(resume_data, {'achievements', 'awards'}),
        limit=6,
    ), section_key='achievements')
    payload['languages'] = _resume_builder_filter_section_items(_resume_builder_clean_items(
        resume_data.get('languages') or _resume_builder_extract_items(resume_data, {'languages'}),
        limit=6,
    ), section_key='languages')
    return payload


def sanitize_resume_builder_payload(raw_payload, *, user: User, profile: UserProfile) -> dict:
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    defaults = _resume_builder_default_payload(user, profile)
    basics = raw_payload.get('basics') if isinstance(raw_payload.get('basics'), dict) else {}
    defaults['basics'].update({
        'name': _resume_builder_clean_text(basics.get('name') or defaults['basics']['name'], 180),
        'email': _resume_builder_clean_text(basics.get('email') or defaults['basics']['email'], 180),
        'phone': _resume_builder_clean_text(basics.get('phone') or defaults['basics']['phone'], 40),
        'location': _resume_builder_clean_text(basics.get('location'), 180),
        'headline': _resume_builder_clean_text(basics.get('headline'), 180),
        'summary': _resume_builder_clean_text(basics.get('summary'), 2000),
        'website': _resume_builder_clean_text(basics.get('website'), 255),
        'linkedin': _resume_builder_clean_text(basics.get('linkedin'), 255),
        'github': _resume_builder_clean_text(basics.get('github'), 255),
        'portfolio': _resume_builder_clean_text(basics.get('portfolio'), 255),
    })
    defaults['skills'] = _resume_builder_clean_list(raw_payload.get('skills'), limit=24, item_limit=80)
    defaults['experience'] = _resume_builder_filter_section_items(_resume_builder_clean_items(raw_payload.get('experience'), limit=8), section_key='experience')
    defaults['projects'] = _resume_builder_filter_section_items(_resume_builder_clean_items(raw_payload.get('projects'), limit=6), section_key='projects')
    defaults['education'] = _resume_builder_filter_section_items(_resume_builder_clean_items(raw_payload.get('education'), limit=5), section_key='education')
    defaults['certifications'] = _resume_builder_filter_section_items(_resume_builder_clean_items(raw_payload.get('certifications'), limit=6), section_key='certifications')
    defaults['achievements'] = _resume_builder_filter_section_items(_resume_builder_clean_items(raw_payload.get('achievements'), limit=6), section_key='achievements')
    defaults['languages'] = _resume_builder_filter_section_items(_resume_builder_clean_items(raw_payload.get('languages'), limit=6), section_key='languages')
    return defaults


def build_resume_builder_export_context(request, user: User, profile: UserProfile, payload: dict) -> dict:
    basics = payload.get('basics') or {}
    experience_section = payload.get('experience') or []
    education_section = payload.get('education') or []
    sections = [
        {'title': 'Experience', 'section_key': 'experience', 'text': '', 'items': experience_section},
        {'title': 'Projects', 'section_key': 'projects', 'text': '', 'items': payload.get('projects') or []},
        {'title': 'Education', 'section_key': 'education', 'text': '', 'items': education_section},
        {'title': 'Certifications', 'section_key': 'certifications', 'text': '', 'items': payload.get('certifications') or []},
        {'title': 'Achievements', 'section_key': 'achievements', 'text': '', 'items': payload.get('achievements') or []},
        {'title': 'Languages', 'section_key': 'languages', 'text': '', 'items': payload.get('languages') or []},
    ]
    sections = [section for section in sections if section['items']]
    current_title = ''
    current_company = ''
    if experience_section:
        current_title = experience_section[0].get('title') or experience_section[0].get('role') or ''
        current_company = experience_section[0].get('company') or ''

    return {
        'candidate': {
            'name': basics.get('name') or (f"{user.first_name} {user.last_name}".strip().title() or user.username),
            'email': basics.get('email') or user.email,
            'phone': basics.get('phone') or profile.phone or '',
            'gender': (profile.gender or '').title() if profile.gender else '',
            'profile_picture_url': '',
            'profile_picture_data_url': '',
        },
        'resume': {
            'headline': basics.get('headline') or '',
            'summary': basics.get('summary') or '',
            'skills': payload.get('skills') or [],
            'sections': sections,
            'processed_at': timezone.now().isoformat(),
            'source_file': 'Resume Builder',
        },
        'highlights': {
            'experience_years': None,
            'current_title': current_title,
            'current_company': current_company,
            'experience_preview': sections[0] if sections else None,
            'education_preview': next((section for section in sections if section.get('section_key') == 'education'), None),
        },
        'share': {
            'short_code': '',
            'share_url': '',
            'word_url': '',
            'pdf_url': '',
        },
    }


def build_resume_export_lines(public_context: dict) -> list[str]:
    candidate = public_context['candidate']
    resume = public_context['resume']
    highlights = public_context['highlights']

    lines = [candidate['name']]
    contact_line = ' | '.join(part for part in [candidate.get('email', ''), candidate.get('phone', '')] if part)
    if contact_line:
        lines.append(contact_line)
    headline = resume.get('headline') or highlights.get('current_title') or ''
    if headline:
        lines.append(headline)
    if resume.get('summary'):
        lines.extend(['', 'Professional Summary'])
        lines.extend(part.strip() for part in str(resume['summary']).splitlines() if part.strip())
    if resume.get('skills'):
        lines.extend(['', 'Skills', ', '.join(str(skill) for skill in resume['skills'])])

    for section in resume.get('sections') or []:
        section_text = (section.get('text') or '').strip()
        if not section_text:
            continue
        lines.extend(['', section.get('title') or 'Section'])
        lines.extend(part.strip() for part in section_text.splitlines() if part.strip())
    return [str(line).strip() for line in lines]


def build_resume_export_html(public_context: dict, export_mode: str, renderer_hint: str = '', renderer_name: str = '') -> str:
    template_name = 'smartInterview/public_candidate_resume.html'
    if export_mode == 'pdf':
        template_name = 'smartInterview/resume_export_pdf_xhtml.html'
    elif export_mode == 'word':
        template_name = 'smartInterview/public_candidate_resume.html'
    return render_to_string(
        template_name,
        {
            **public_context,
            'export_mode': export_mode,
            'renderer_hint': renderer_hint,
        },
    )


def rtf_escape(value: str) -> str:
    text = str(value or '')
    escaped: list[str] = []
    for char in text:
        code = ord(char)
        if char == '\\':
            escaped.append('\\\\')
        elif char == '{':
            escaped.append('\\{')
        elif char == '}':
            escaped.append('\\}')
        elif char == '\n':
            escaped.append('\\line ')
        elif 32 <= code <= 126:
            escaped.append(char)
        else:
            escaped.append(f'\\u{code}?')
    return ''.join(escaped)


def get_resume_section(public_context: dict, keys: set[str], title_terms: tuple[str, ...] = ()) -> dict | None:
    for section in public_context.get('resume', {}).get('sections') or []:
        section_key = str(section.get('section_key') or '').strip().lower()
        title = str(section.get('title') or '').strip().lower()
        if section_key in keys:
            return section
        if title_terms and any(term in title for term in title_terms):
            return section
    return None


def extract_section_bullets(section: dict | None) -> list[str]:
    if not section:
        return []
    items = section.get('items') or []
    bullets: list[str] = []
    for item in items:
        if isinstance(item, str):
            clean = item.strip()
            if clean:
                bullets.append(clean)
            continue
        if not isinstance(item, dict):
            continue
        primary = (
            item.get('description')
            or item.get('value')
            or item.get('label')
            or item.get('title')
            or item.get('degree')
            or ''
        )
        clean_primary = str(primary).strip()
        if clean_primary:
            bullets.append(clean_primary)
        for detail in item.get('details') or []:
            clean_detail = str(detail or '').strip()
            if clean_detail:
                bullets.append(clean_detail)
    if bullets:
        return bullets
    text = str(section.get('text') or '').strip()
    return [line.strip() for line in text.splitlines() if line.strip()]


def build_work_history_rtf(items: list[dict]) -> list[str]:
    blocks: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        duration = rtf_escape(item.get('duration') or '')
        title = rtf_escape(item.get('title') or item.get('degree') or item.get('label') or 'Experience Entry')
        company = rtf_escape(item.get('company') or '')
        location = rtf_escape(item.get('location') or '')
        role = rtf_escape(item.get('role') or '')
        description = rtf_escape(item.get('description') or '')
        details = [rtf_escape(detail) for detail in (item.get('details') or []) if str(detail).strip()]
        tech_stack = [str(tech).strip() for tech in (item.get('tech_stack') or []) if str(tech).strip()]
        right_lines: list[str] = []
        if description:
            right_lines.append(description)
        if tech_stack:
            right_lines.append(rtf_escape('Tech: ' + ', '.join(tech_stack)))
        right_lines.extend(details[:5])

        blocks.append(r'\pard\sb90\sa0\sl220\slmult1')
        blocks.append(r'\trowd\trgaph120\trleft0\trbrdrt\brdrnone\trbrdrl\brdrnone\trbrdrb\brdrnone\trbrdrr\brdrnone')
        blocks.append(r'\clvertalt\cellx2750\clvertalt\cellx9300')
        left_parts: list[str] = []
        if duration:
            left_parts.append(rf'\b {duration}\b0\line ')
        left_parts.append(rf'\b {title}\b0\line ')
        if company:
            left_parts.append(company + r'\line ')
        if location:
            left_parts.append(location)
        blocks.append(r'\pard\intbl\sl220\slmult1\fs20\cf1 ' + ''.join(left_parts) + r'\cell')
        right_rtf = r''
        if right_lines:
            right_rtf = r'\pard\intbl\sl220\slmult1\fs19\cf1 ' + r'\line '.join(right_lines)
        blocks.append(right_rtf + r'\cell\row')
        blocks.append(r'\pard\sa70\sl200\slmult1\cf3\fs8 ________________________________________________\par')
    return blocks


def build_resume_export_rtf(public_context: dict) -> str:
    candidate = public_context['candidate']
    resume = public_context['resume']
    highlights = public_context['highlights']
    objective_section = get_resume_section(public_context, {'objective', 'career_objective'}, ('career objective', 'objective'))
    summary_section = get_resume_section(public_context, {'professional_summary', 'summary'}, ('professional summary', 'summary'))
    experience_section = get_resume_section(public_context, {'work_history', 'experience', 'professional_experience'}, ('work history', 'experience'))
    parts: list[str] = [
        r'{\rtf1\ansi\deff0',
        r'{\fonttbl{\f0 Calibri;}{\f1 Cambria;}}',
        r'{\colortbl;\red16\green42\blue67;\red31\green85\blue115;\red82\green97\blue113;\red245\green248\blue252;}',
        r'\paperw15840\paperh12240\margl900\margr900\margt720\margb720',
        r'\viewkind4\uc1',
    ]

    name = rtf_escape(candidate.get('name', 'Candidate'))
    title = rtf_escape(highlights.get('current_title') or resume.get('headline') or '')
    contact_parts = [candidate.get('email', ''), candidate.get('phone', '')]
    if candidate.get('gender'):
        contact_parts.append(candidate['gender'])
    contact_line = rtf_escape(' | '.join(part for part in contact_parts if part))

    parts.append(rf'\pard\qc\sa80\sl276\slmult1\f1\fs40\b\cf1 {name}\par')
    if title:
        parts.append(rf'\pard\qc\sa60\sl220\slmult1\f0\fs20\b0\cf3 {title}\par')
    if contact_line:
        parts.append(rf'\pard\qc\sa220\sl220\slmult1\f0\fs18\cf3 {contact_line}\par')

    if objective_section:
        objective_title = rtf_escape(objective_section.get('title') or 'Career Objective')
        objective_text = rtf_escape(extract_resume_section_text(objective_section))
        parts.append(rf'\pard\sa70\sl220\slmult1\cb4\b\fs16\cf1 {objective_title.upper()}\cb0\b0\par')
        if objective_text:
            parts.append(rf'\pard\sb70\sa180\sl236\slmult1\f0\fs20\cf1 {objective_text}\par')

    summary_bullets = extract_section_bullets(summary_section)
    if summary_bullets:
        summary_title = rtf_escape((summary_section or {}).get('title') or 'Professional Summary')
        parts.append(rf'\pard\sa70\sl220\slmult1\cb4\b\fs16\cf1 {summary_title.upper()}\cb0\b0\par')
        for bullet in summary_bullets:
            parts.append(rf'\pard\li320\fi-160\sb35\sa10\sl220\slmult1\f0\fs19\cf1\'95\tab {rtf_escape(bullet)}\par')

    if experience_section and (experience_section.get('items') or []):
        experience_title = rtf_escape(experience_section.get('title') or 'Work History')
        parts.append(rf'\pard\sa70\sl220\slmult1\cb4\b\fs16\cf1 {experience_title.upper()}\cb0\b0\par')
        parts.extend(build_work_history_rtf(experience_section.get('items') or []))

    rendered_keys = {
        str((objective_section or {}).get('section_key') or '').lower(),
        str((summary_section or {}).get('section_key') or '').lower(),
        str((experience_section or {}).get('section_key') or '').lower(),
    }

    for section in resume.get('sections') or []:
        section_key = str(section.get('section_key') or '').lower()
        if section_key in rendered_keys:
            continue
        section_title = rtf_escape(section.get('title') or 'Section')
        items = section.get('items') or []
        text = (section.get('text') or '').strip()
        parts.append(rf'\pard\sa70\sl220\slmult1\cb4\b\fs16\cf1 {section_title.upper()}\cb0\b0\par')

        if items:
            for item in items:
                if isinstance(item, dict):
                    primary = rtf_escape(item.get('title') or item.get('degree') or item.get('label') or item.get('institution') or 'Entry')
                    secondary_parts = []
                    for key in ('company', 'institution', 'issuer', 'value', 'duration', 'location', 'role'):
                        value = str(item.get(key) or '').strip()
                        if value:
                            secondary_parts.append(value)
                    details = [str(detail).strip() for detail in (item.get('details') or []) if str(detail).strip()]
                    if item.get('description'):
                        details.append(str(item.get('description')).strip())
                    parts.append(rf'\pard\sb60\sa20\sl220\slmult1\f0\fs21\b\cf1 {primary}\b0\par')
                    if secondary_parts:
                        parts.append(rf'\pard\sa35\sl220\slmult1\f0\fs18\cf3 {rtf_escape(" | ".join(secondary_parts))}\par')
                    for detail in details:
                        parts.append(rf'\pard\li220\sb15\sa10\sl220\slmult1\f0\fs19\cf1 {rtf_escape(detail)}\par')
                else:
                    clean_item = str(item).strip()
                    if clean_item:
                        parts.append(rf'\pard\sb45\sa15\sl220\slmult1\f0\fs19\cf1 {rtf_escape(clean_item)}\par')
        elif text:
            for line in text.splitlines():
                clean_line = line.strip()
                if clean_line:
                    parts.append(rf'\pard\sb25\sa10\sl220\slmult1\f0\fs19\cf1 {rtf_escape(clean_line)}\par')

    parts.append('}')
    return ''.join(parts)


def render_word_document_from_html(html: str) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        html_path = f'{temp_dir}/resume.html'
        doc_path = f'{temp_dir}/resume.doc'
        with open(html_path, 'w', encoding='utf-8') as handle:
            handle.write(html)
        subprocess.run(
            ['/usr/bin/textutil', '-convert', 'doc', html_path, '-output', doc_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        with open(doc_path, 'rb') as handle:
            return handle.read()


def render_word_document_from_rtf(rtf: str) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        rtf_path = f'{temp_dir}/resume.rtf'
        doc_path = f'{temp_dir}/resume.doc'
        with open(rtf_path, 'w', encoding='utf-8') as handle:
            handle.write(rtf)
        subprocess.run(
            ['/usr/bin/textutil', '-convert', 'doc', rtf_path, '-output', doc_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        with open(doc_path, 'rb') as handle:
            return handle.read()


def render_pdf_from_text(lines: list[str], title: str) -> bytes:
    plain_text = '\n'.join(line for line in lines if line is not None).strip() + '\n'
    with tempfile.TemporaryDirectory() as temp_dir:
        txt_path = f'{temp_dir}/resume.txt'
        pdf_path = f'{temp_dir}/resume.pdf'
        with open(txt_path, 'w', encoding='utf-8') as handle:
            handle.write(plain_text)
        with open(pdf_path, 'wb') as output_handle:
            process = subprocess.run(
                ['/usr/sbin/cupsfilter', '-i', 'text/plain', '-m', 'application/pdf', '-t', title, txt_path],
                check=True,
                stdout=output_handle,
                stderr=subprocess.PIPE,
                timeout=20,
            )
        with open(pdf_path, 'rb') as handle:
            return handle.read()


class ResumeRenderTimeout(Exception):
    pass


class resume_render_deadline:
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        self.previous_handler = None

    def _handle_timeout(self, signum, frame):
        raise ResumeRenderTimeout(f'Resume render exceeded {self.seconds} seconds.')

    def __enter__(self):
        if hasattr(signal, 'SIGALRM'):
            self.previous_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, self._handle_timeout)
            signal.alarm(self.seconds)
        return self

    def __exit__(self, exc_type, exc, tb):
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
            if self.previous_handler is not None:
                signal.signal(signal.SIGALRM, self.previous_handler)
        return False


def get_external_pdf_renderer_python() -> str:
    for candidate in PDF_RENDERER_PYTHON_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return ''


def get_pdf_browser_binary() -> str:
    for candidate in PDF_BROWSER_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return ''


def render_pdf_with_chrome(html: str) -> tuple[bytes, str]:
    browser_binary = get_pdf_browser_binary()
    if not browser_binary:
        raise RuntimeError('No browser PDF renderer is configured.')

    with tempfile.TemporaryDirectory() as temp_dir:
        pdf_path = os.path.join(temp_dir, 'resume.pdf')
        html_path = os.path.join(temp_dir, 'resume.html')
        with open(html_path, 'w', encoding='utf-8') as handle:
            handle.write(html)
        subprocess.run(
            [
                browser_binary,
                '--headless=new',
                '--no-sandbox',
                '--disable-gpu',
                '--no-pdf-header-footer',
                '--print-to-pdf-no-header',
                f'--print-to-pdf={pdf_path}',
                f'file://{html_path}',
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        with open(pdf_path, 'rb') as handle:
            return handle.read(), 'chrome-print'


def render_pdf_with_external_python(html: str) -> tuple[bytes, str]:
    renderer_python = get_external_pdf_renderer_python()
    if not renderer_python:
        raise RuntimeError('No external PDF renderer Python interpreter is configured.')

    script = """
import io
import sys
from xhtml2pdf import pisa

html_path, pdf_path = sys.argv[1], sys.argv[2]
with open(html_path, 'r', encoding='utf-8') as handle:
    html = handle.read()

with open(pdf_path, 'wb') as output:
    result = pisa.CreatePDF(src=html, dest=output)

if result.err:
    raise SystemExit(1)
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        html_path = f'{temp_dir}/resume.html'
        pdf_path = f'{temp_dir}/resume.pdf'
        with open(html_path, 'w', encoding='utf-8') as handle:
            handle.write(html)
        subprocess.run(
            [renderer_python, '-c', script, html_path, pdf_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        with open(pdf_path, 'rb') as handle:
            return handle.read(), 'external-xhtml2pdf'


def render_pdf_from_html(html: str, base_url: str, title: str) -> tuple[bytes, str]:
    try:
        return render_pdf_with_external_python(html)
    except Exception:
        pass

    try:
        with resume_render_deadline(12):
            from xhtml2pdf import pisa  # type: ignore
            output = io.BytesIO()
            result = pisa.CreatePDF(src=html, dest=output)
            if not result.err:
                return output.getvalue(), 'xhtml2pdf'
    except Exception:
        pass

    try:
        with resume_render_deadline(12):
            from weasyprint import HTML  # type: ignore

            return HTML(string=html, base_url=base_url).write_pdf(), 'weasyprint'
    except Exception:
        pass

    raise RuntimeError('No HTML-to-PDF renderer is available in the current Python environment.')


def render_text_pdf(title: str, lines: list[str]) -> bytes:
    safe_lines = []
    for line in lines:
        normalized = str(line or '').replace('\t', ' ').replace('\r', '')
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        if not normalized:
            safe_lines.append('')
            continue
        normalized = normalized.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        normalized = normalized.encode('latin-1', 'replace').decode('latin-1')
        safe_lines.append(normalized)

    safe_title = str(title or 'Resume').replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    safe_title = safe_title.encode('latin-1', 'replace').decode('latin-1')

    page_width = 612
    page_height = 792
    margin_x = 54
    start_y = 744
    line_height = 16
    max_lines_per_page = 42
    chunks = [safe_lines[index:index + max_lines_per_page] for index in range(0, len(safe_lines), max_lines_per_page)] or [[]]

    objects: list[bytes] = []

    def add_object(content: bytes) -> int:
        objects.append(content)
        return len(objects)

    font_obj = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    content_ids: list[int] = []

    for chunk in chunks:
        stream_lines = [b"BT", b"/F1 11 Tf", f"{margin_x} {start_y} Td".encode()]
        for idx, line in enumerate(chunk):
            if idx:
                stream_lines.append(b"T*")
            if line:
                stream_lines.append(f"({line}) Tj".encode('latin-1'))
        stream_lines.append(b"ET")
        stream = b"\n".join(stream_lines)
        content_id = add_object(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
        content_ids.append(content_id)
        page_ids.append(0)

    pages_obj_id = len(objects) + len(chunks) + 1

    for idx, content_id in enumerate(content_ids):
        page_body = (
            f"<< /Type /Page /Parent {pages_obj_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode('latin-1')
        page_ids[idx] = add_object(page_body)

    kids = ' '.join(f'{page_id} 0 R' for page_id in page_ids)
    pages_id = add_object(f"<< /Type /Pages /Kids [ {kids} ] /Count {len(page_ids)} >>".encode('latin-1'))
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode('latin-1'))

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode('latin-1'))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode('latin-1'))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode('latin-1'))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info << /Title ({safe_title}) >> >>\n"
            f"startxref\n{xref_pos}\n%%EOF"
        ).encode('latin-1')
    )
    return bytes(pdf)


def build_candidate_signup_token(user: User, interview: Interview) -> str:
    profile = getattr(user, 'profile', None)
    payload = {
        'user_id': user.id,
        'interview_id': interview.id,
        'name': f"{user.first_name} {user.last_name}".strip(),
        'email': user.email,
        'phone': profile.phone if profile else '',
        'gender': profile.gender if profile else '',
        'role_id': interview.role_id,
        'role_name': interview.role.role if interview.role else '',
    }
    return signing.dumps(payload, salt=SIGNUP_TOKEN_SALT)


def load_candidate_signup_token(token: str) -> dict:
    return signing.loads(token, salt=SIGNUP_TOKEN_SALT, max_age=SIGNUP_TOKEN_MAX_AGE_SECONDS)


def generate_candidate_signup_code(length: int = 8) -> str:
    alphabet = '23456789abcdefghjkmnpqrstuvwxyz'
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if not Interview.objects.filter(candidate_signup_token=code).exists():
            return code


def is_compact_candidate_signup_code(token: str) -> bool:
    value = (token or '').strip().lower()
    return bool(re.fullmatch(r'[23456789abcdefghjkmnpqrstuvwxyz]{6,16}', value))


def ensure_candidate_signup_token(interview: Interview) -> str:
    now = timezone.now()
    token = (interview.candidate_signup_token or '').strip().lower()
    created_at = getattr(interview, 'candidate_signup_token_created_at', None)
    if (
        token
        and is_compact_candidate_signup_code(token)
        and created_at
        and created_at >= now - timedelta(seconds=SIGNUP_TOKEN_MAX_AGE_SECONDS)
    ):
        return token

    token = generate_candidate_signup_code()
    interview.candidate_signup_token = token
    interview.candidate_signup_token_created_at = now
    interview.save(update_fields=['candidate_signup_token', 'candidate_signup_token_created_at'])
    return token


def get_candidate_signup_interview_by_token(token: str) -> Interview | None:
    value = (token or '').strip().lower()
    if not is_compact_candidate_signup_code(value):
        return None

    valid_after = timezone.now() - timedelta(seconds=SIGNUP_TOKEN_MAX_AGE_SECONDS)
    return (
        Interview.objects.select_related('candidate', 'recruiter', 'interviewer', 'role')
        .filter(candidate_signup_token=value, candidate_signup_token_created_at__gte=valid_after)
        .first()
    )


def build_candidate_signup_link(request, interview: Interview) -> tuple[str, str]:
    token = ensure_candidate_signup_token(interview)
    if request is not None:
        base_url = build_host_link(request, 'candidates').rstrip('/')
    else:
        base_url = getattr(settings, 'CANDIDATE_PUBLIC_BASE_URL', 'https://candidates.shortlistii.com').rstrip('/')
    return token, f'{base_url}/s/{token}/'


def send_existing_candidate_sms(
    candidate: User,
    interview: Interview,
    request=None,
    *,
    notification_kind: str = 'scheduled',
    previous_scheduled_at=None,
) -> dict:
    profile = getattr(candidate, 'profile', None)
    phone = normalize_phone(profile.phone if profile else '')
    interview_token, interview_link = build_litio_interview_link(request, interview)
    recruiter_name = f"{interview.recruiter.first_name} {interview.recruiter.last_name}".strip().title() if interview.recruiter else 'our team'
    role_name = interview.role.role if interview.role else 'the role'
    interview_date, interview_time = format_interview_schedule(interview.date)
    message = build_sms_message('candidate_interview_created', {
        'candidate_name': (candidate.first_name or 'Candidate').strip().title(),
        'role_name': role_name,
        'recruiter_name': recruiter_name,
        'interview_date': interview_date,
        'interview_time': interview_time,
    })
    if phone:
        sms_result = send_sms(phone, message, metadata={
            'event_type': 'candidate_interview_created',
            'interview_id': interview.id,
            'msg91_template_id': getattr(settings, 'MSG91_INTERVIEW_TEMPLATE_ID', ''),
            'msg91_flow_variables': {
                'name': (candidate.first_name or 'Candidate').strip().title(),
                'role': role_name,
                'recruiter': recruiter_name,
            },
        })
        whatsapp_result = send_candidate_whatsapp_notification(
            phone=phone,
            template_name=getattr(settings, 'CANDIDATE_EXISTING_WHATSAPP_TEMPLATE', 'candidate_interview_created'),
            parameters=[
                (candidate.first_name or 'Candidate').strip().title(),
                role_name,
                recruiter_name,
            ],
            metadata={'event_type': 'candidate_interview_created', 'interview_id': interview.id},
        )
    else:
        sms_result = type('SmsResult', (), {
            'success': False,
            'error_message': 'Candidate phone number is missing.',
            'provider_message_id': '',
        })()
        whatsapp_result = {
            'sent': False,
            'reason': 'Candidate phone number is missing.',
            'provider_message_id': '',
            'template_name': getattr(settings, 'CANDIDATE_EXISTING_WHATSAPP_TEMPLATE', 'candidate_interview_created'),
        }
    email_result = send_candidate_interview_email(
        request,
        candidate,
        interview,
        interview_link,
        notification_kind=notification_kind,
        previous_scheduled_at=previous_scheduled_at,
    )
    failures: list[str] = []
    if not sms_result.success:
        failures.append(sms_result.error_message or 'SMS delivery failed.')
    if not whatsapp_result['sent']:
        failures.append(whatsapp_result['reason'] or 'WhatsApp delivery failed.')
    if not email_result['sent']:
        failures.append(str(email_result.get('reason') or 'Email delivery failed.'))
    return {
        'sent': sms_result.success or whatsapp_result['sent'] or bool(email_result['sent']),
        'reason': ' '.join(part for part in failures if part).strip(),
        'provider_message_id': sms_result.provider_message_id,
        'channels': {
            'sms': {
                'sent': sms_result.success,
                'reason': '' if sms_result.success else (sms_result.error_message or 'SMS delivery failed.'),
                'provider_message_id': sms_result.provider_message_id,
            },
            'whatsapp': whatsapp_result,
            'email': email_result,
        },
        'message': message,
        'interview_token': interview_token,
        'interview_link': interview_link,
    }


def send_candidate_interview_email_only(
    request,
    interview: Interview,
    *,
    notification_kind: str = 'scheduled',
    previous_scheduled_at=None,
) -> dict:
    interview_token, interview_link = build_litio_interview_link(request, interview)
    email_result = send_candidate_interview_email(
        request,
        interview.candidate,
        interview,
        interview_link,
        notification_kind=notification_kind,
        previous_scheduled_at=previous_scheduled_at,
    )
    return {
        'sent': bool(email_result.get('sent')),
        'reason': '' if email_result.get('sent') else str(email_result.get('reason') or 'Email delivery failed.'),
        'channels': {
            'email': email_result,
        },
        'interview_token': interview_token,
        'interview_link': interview_link,
    }


def send_new_candidate_signup_sms(request, candidate: User, interview: Interview) -> dict:
    profile = getattr(candidate, 'profile', None)
    phone = normalize_phone(profile.phone if profile else '')
    if not phone:
        return {'sent': False, 'reason': 'Candidate phone number is missing.'}

    signup_token, signup_url = build_candidate_signup_link(request, interview)
    role_name = interview.role.role if interview.role else 'the role'
    message = build_sms_message('candidate_signup_invite', {
        'candidate_name': (candidate.first_name or 'Candidate').strip().title(),
        'role_name': role_name,
        'signup_url': signup_url,
    })
    sms_result = send_sms(phone, message, metadata={
        'event_type': 'candidate_signup_invite',
        'interview_id': interview.id,
        'msg91_template_id': getattr(settings, 'MSG91_CANDIDATE_SIGNUP_TEMPLATE_ID', ''),
        'msg91_flow_variables': {
            'name': (candidate.first_name or 'Candidate').strip().title(),
            'role': role_name,
            'url': signup_url,
        },
    })
    whatsapp_result = send_candidate_whatsapp_notification(
        phone=phone,
        template_name=getattr(settings, 'CANDIDATE_SIGNUP_WHATSAPP_TEMPLATE', 'candidate_signup_invite'),
        parameters=[(candidate.first_name or 'Candidate').strip().title(), role_name, signup_url],
        metadata={'event_type': 'candidate_signup_invite', 'interview_id': interview.id},
    )
    return {
        'sent': sms_result.success or whatsapp_result['sent'],
        'reason': build_notification_reason(
            sms_success=sms_result.success,
            sms_error=sms_result.error_message,
            whatsapp_success=whatsapp_result['sent'],
            whatsapp_error=whatsapp_result['reason'],
        ),
        'provider_message_id': sms_result.provider_message_id,
        'channels': {
            'sms': {
                'sent': sms_result.success,
                'reason': '' if sms_result.success else (sms_result.error_message or 'SMS delivery failed.'),
                'provider_message_id': sms_result.provider_message_id,
            },
            'whatsapp': whatsapp_result,
        },
        'signup_token': signup_token,
        'signup_url': signup_url,
        'message': message,
    }


def build_notification_reason(sms_success: bool, sms_error: str, whatsapp_success: bool, whatsapp_error: str) -> str:
    failures: list[str] = []
    if not sms_success:
        failures.append(sms_error or 'SMS delivery failed.')
    if not whatsapp_success:
        failures.append(whatsapp_error or 'WhatsApp delivery failed.')
    return ' '.join(part for part in failures if part).strip()


def send_candidate_whatsapp_notification(phone: str, template_name: str, parameters: list[str], metadata: dict | None = None) -> dict:
    components = [{
        'type': 'body',
        'parameters': [
            {'type': 'text', 'text': str(value or '').strip()}
            for value in parameters
        ],
    }]
    result = send_template_message(
        to=phone,
        template_name=template_name,
        language_code=getattr(settings, 'DEFAULT_WHATSAPP_LANGUAGE_CODE', 'en'),
        components=components,
        metadata=metadata or {},
    )
    return {
        'sent': result.success,
        'reason': '' if result.success else (result.error_message or 'WhatsApp delivery failed.'),
        'provider_message_id': result.provider_message_id,
        'template_name': template_name,
    }


def notify_recruiters_for_candidate_application(candidate: User, vacancy: Vacancies) -> dict:
    candidate_name = f"{candidate.first_name} {candidate.last_name}".strip() or candidate.username
    candidate_profile = getattr(candidate, 'profile', None)
    candidate_phone = candidate_profile.phone if candidate_profile else ''
    recruiters = list(vacancy.recruiter.select_related('profile').all())
    notifications: list[dict] = []
    delivered = False

    for recruiter in recruiters:
        recruiter_profile = getattr(recruiter, 'profile', None)
        phone = normalize_phone(recruiter_profile.phone if recruiter_profile else '')
        if not phone:
            notifications.append({
                'recruiter_id': recruiter.id,
                'name': f"{recruiter.first_name} {recruiter.last_name}".strip().title() or recruiter.username,
                'sent': False,
                'reason': 'Recruiter phone number is missing.',
            })
            continue

        message = build_sms_message('candidate_vacancy_application', {
            'candidate_name': candidate_name,
            'vacancy_role': vacancy.role,
        })
        sms_result = send_sms(phone, message, metadata={
            'event_type': 'candidate_vacancy_application',
            'candidate_id': candidate.id,
            'vacancy_id': vacancy.id,
        })
        whatsapp_result = send_candidate_whatsapp_notification(
            phone=phone,
            template_name=getattr(settings, 'CANDIDATE_EXISTING_WHATSAPP_TEMPLATE', 'candidate_interview_created'),
            parameters=[f"{recruiter.first_name or 'Recruiter'}", candidate_name, vacancy.role],
            metadata={
                'event_type': 'candidate_vacancy_application',
                'candidate_id': candidate.id,
                'vacancy_id': vacancy.id,
            },
        )
        sent = sms_result.success or whatsapp_result['sent']
        delivered = delivered or sent
        notifications.append({
            'recruiter_id': recruiter.id,
            'name': f"{recruiter.first_name} {recruiter.last_name}".strip().title() or recruiter.username,
            'sent': sent,
            'sms_sent': sms_result.success,
            'whatsapp_sent': whatsapp_result['sent'],
            'reason': build_notification_reason(
                sms_success=sms_result.success,
                sms_error=sms_result.error_message,
                whatsapp_success=whatsapp_result['sent'],
                whatsapp_error=whatsapp_result['reason'],
            ),
        })

    return {
        'sent': delivered,
        'recruiters': notifications,
        'count': len(notifications),
        'candidate': candidate_name,
        'candidate_phone': candidate_phone,
        'vacancy': vacancy.role,
    }


@csrf_exempt
@login_required
def addUser(request):
    try:
        with transaction.atomic():
            email = request.POST.get('email','')
            name = request.POST.get('name','')
            phone = request.POST.get('phone','')
            role = request.POST.get('profile','')
            gender = request.POST.get('gender','')
            password = request.POST.get('password', '')
            user_type = request.POST.get('role','')
            recruiter = request.POST.get('recruiter','')
            operator = get_object_or_404(User, username=request.user.username)
            normalized_user_type = (user_type or '').strip().lower()
            role_obj = Vacancies.objects.get(id=role) if normalized_user_type not in {'recruiter', 'interviewer'} and role else None
            if normalized_user_type == 'recruiter' and len((password or '').strip()) < 8:
                return JsonResponse({"Success": False, "Error": "Recruiter password must be at least 8 characters."})
            admin_user, assigned_recruiter, assigned_interviewer = resolve_interview_assignment(operator, recruiter)
            admin_company = getattr(admin_user, 'company_profile', None) if admin_user else None
            admin_company_url = ''
            if admin_company:
                admin_company_url = admin_company.website or ''
            elif getattr(getattr(admin_user, 'profile', None), 'company_url', ''):
                admin_company_url = admin_user.profile.company_url
            if normalized_user_type == 'interviewer' and assigned_recruiter is None:
                return JsonResponse({"Success": False, "Error": "Please select a valid HR for the interviewer."})
            if normalized_user_type not in {'recruiter', 'interviewer'} and admin_user is None:
                return JsonResponse({"Success": False, "Error": "Unable to resolve the admin assignment for this candidate."})
            if email:
                first_name, last_name = split_name(name)
                obj, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "username": generate_username(name),
                        "email": email,
                        "first_name": first_name,
                        "last_name": last_name,
                    },
                )
                if created:
                    if normalized_user_type == 'recruiter':
                        obj.set_password(password.strip())
                    else:
                        obj.set_unusable_password()
                    obj.save()
                    # Create or update UserProfile with the given role
                    profile, created_profile = UserProfile.objects.get_or_create(
                        user=obj,
                        defaults={
                            'gender': gender,
                            'role': normalized_user_type,
                            'phone': phone,
                            'hr': admin_user
                        }
                    )
                    if not created_profile:
                        profile.role = normalized_user_type
                        profile.gender = gender or profile.gender
                        profile.phone = phone or profile.phone
                        profile.hr = admin_user
                    if normalized_user_type == 'interviewer':
                        profile.recruiter = assigned_recruiter if get_user_role(assigned_recruiter) == 'recruiter' else None
                    else:
                        profile.recruiter = None
                    if normalized_user_type == 'recruiter':
                        profile.company = admin_company
                        profile.company_url = admin_company_url or profile.company_url
                    profile.save()
                    if normalized_user_type not in {'recruiter', 'interviewer'}:
                        ensure_pipeline_application(
                            obj,
                            role_obj,
                            CandidateVacancyApplication.PipelineSource.REFERRAL,
                        )
                        candidate = Interview.objects.create(
                            candidate=obj,
                            recruiter=assigned_recruiter,
                            interviewer=assigned_interviewer,
                            hr=admin_user,
                            status='assessment_pending',
                            role=role_obj,
                        )
                        candidate.save()
                        candidate_details = build_candidate_details(candidate, request=request)
                        notification_result = send_new_candidate_signup_sms(request, obj, candidate)
                    if normalized_user_type in {'recruiter', 'interviewer'}:
                        recruiter_details = {}
                        recruiter_details['id'] = profile.id
                        recruiter_details['name'] = get_display_name(profile.user)
                        recruiter_details['email'] = profile.user.email
                        recruiter_details['role'] = profile.role
                        recruiter_details['phone'] = profile.phone
                        recruiter_details['gender'] = profile.gender
                        recruiter_details['hr_id'] = profile.hr_id
                        recruiter_details['recruiter_id'] = profile.recruiter_id
                        return JsonResponse({"Success": True, "Error": None, "RecruiterData": recruiter_details})
                else:
                    if not obj.first_name or not obj.last_name:
                        obj.first_name = first_name or obj.first_name
                        obj.last_name = last_name or obj.last_name
                        obj.save(update_fields=['first_name', 'last_name'])
                    if normalized_user_type == 'recruiter' and password.strip():
                        obj.set_password(password.strip())
                        obj.save(update_fields=['password'])
                    profile, created_profile = UserProfile.objects.get_or_create(
                        user=obj,
                        defaults={
                            'gender': gender,
                            'role': normalized_user_type,
                            'phone': phone,
                            'hr': admin_user
                        }
                    )
                    if not created_profile:
                        profile.role = normalized_user_type
                        profile.gender = gender or profile.gender
                        profile.phone = phone or profile.phone
                        profile.hr = admin_user
                    if normalized_user_type == 'interviewer':
                        profile.recruiter = assigned_recruiter if get_user_role(assigned_recruiter) == 'recruiter' else None
                    elif normalized_user_type != 'interviewer':
                        profile.recruiter = None
                    if normalized_user_type == 'recruiter':
                        profile.company = admin_company
                        profile.company_url = admin_company_url or profile.company_url
                    profile.save()
                    if normalized_user_type in {'recruiter', 'interviewer'}:
                        recruiter_details = {}
                        recruiter_details['id'] = profile.id
                        recruiter_details['name'] = get_display_name(profile.user)
                        recruiter_details['email'] = profile.user.email
                        recruiter_details['role'] = profile.role
                        recruiter_details['phone'] = profile.phone
                        recruiter_details['gender'] = profile.gender
                        recruiter_details['hr_id'] = profile.hr_id
                        recruiter_details['recruiter_id'] = profile.recruiter_id
                        return JsonResponse({"Success": True, "Error": None, "RecruiterData": recruiter_details})
                    if normalized_user_type not in {'recruiter', 'interviewer'}:
                        ensure_pipeline_application(
                            obj,
                            role_obj,
                            CandidateVacancyApplication.PipelineSource.DIRECT,
                        )
                        candidate = Interview.objects.create(
                            candidate=obj,
                            recruiter=assigned_recruiter,
                            interviewer=assigned_interviewer,
                            hr=admin_user,
                            status='assessment_pending',
                            role=role_obj,
                        )
                        candidate.save()
                        candidate_details = build_candidate_details(candidate, request=request)
                        notification_result = send_existing_candidate_sms(obj, candidate, request=request)
            else:
                    return JsonResponse({"Success":False, "Error":'Add user failed'})
            return JsonResponse({
                "Success": True,
                "Error": None,
                "CandidateDetails": candidate_details,
                "Notification": notification_result if normalized_user_type not in {'recruiter', 'interviewer'} else None,
                "CandidateExists": not created if normalized_user_type not in {'recruiter', 'interviewer'} else False,
                "SignupRequired": created if normalized_user_type not in {'recruiter', 'interviewer'} else False,
            })
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})


@csrf_exempt
@login_required
def updateRecruiterDetails(request):
    try:
        if request.method != 'POST':
            return JsonResponse({"Success": False, "Error": "Invalid request method."}, status=405)

        operator = get_object_or_404(User, username=request.user.username)
        operator_role = get_user_role(operator)

        recruiter_id = (request.POST.get('recruiter_id') or '').strip()
        if not recruiter_id.isdigit():
            return JsonResponse({"Success": False, "Error": "A valid profile identifier is required."}, status=400)

        profile_type = (request.POST.get('profile_type') or 'recruiter').strip().lower()
        target_role = 'recruiter' if profile_type == 'recruiter' else 'interviewer'
        target_label = 'Recruiter' if target_role == 'recruiter' else 'Evaluator'

        target_profile = None
        target_lookup = int(recruiter_id)
        if target_role == 'recruiter':
            if operator_role != 'admin':
                return JsonResponse({"Success": False, "Error": "Only admins can update recruiter details."}, status=403)

            target_profile = get_object_or_404(
                UserProfile.objects.select_related('user'),
                user_id=target_lookup,
                role='recruiter',
                hr=operator,
            )
        else:
            accessible_profiles = get_accessible_interviewer_profiles(operator)
            target_profile = accessible_profiles.select_related('user').filter(
                Q(id=target_lookup) | Q(user_id=target_lookup)
            ).first()
            if not target_profile:
                if operator_role == 'admin':
                    error_message = "Evaluator not found in your accessible scope."
                elif operator_role == 'recruiter':
                    error_message = "You can only update evaluators assigned to your account."
                else:
                    error_message = "You are not allowed to update evaluator details."
                return JsonResponse({"Success": False, "Error": error_message}, status=403)

        target_user = target_profile.user

        name = (request.POST.get('name') or '').strip()
        email = (request.POST.get('email') or '').strip().lower()
        phone = (request.POST.get('phone') or '').strip()
        gender = (request.POST.get('gender') or '').strip().lower()
        assignment_field_present = 'assigned_recruiter_id' in request.POST
        assigned_recruiter_id = (request.POST.get('assigned_recruiter_id') or '').strip()

        if not name:
            return JsonResponse({"Success": False, "Error": f"{target_label} name is required."}, status=400)
        if not email:
            return JsonResponse({"Success": False, "Error": f"{target_label} email is required."}, status=400)

        allowed_genders = {choice[0] for choice in UserProfile.Gender_CHOICES}
        if gender and gender not in allowed_genders:
            return JsonResponse({"Success": False, "Error": "Please select a valid gender."}, status=400)

        if User.objects.exclude(id=target_user.id).filter(email__iexact=email).exists():
            return JsonResponse({"Success": False, "Error": "Another user already uses this email address."}, status=400)

        first_name, last_name = split_name(name)
        user_update_fields = []
        if target_user.first_name != first_name:
            target_user.first_name = first_name
            user_update_fields.append('first_name')
        if target_user.last_name != last_name:
            target_user.last_name = last_name
            user_update_fields.append('last_name')
        if target_user.email != email:
            target_user.email = email
            user_update_fields.append('email')
        if user_update_fields:
            target_user.save(update_fields=user_update_fields)

        profile_update_fields = []
        if target_role == 'interviewer' and assignment_field_present:
            assigned_recruiter = None
            if assigned_recruiter_id:
                if not assigned_recruiter_id.isdigit():
                    return JsonResponse({"Success": False, "Error": "Please select a valid recruiter."}, status=400)

                if operator_role == 'admin':
                    assigned_recruiter = User.objects.filter(
                        id=int(assigned_recruiter_id),
                        profile__role='recruiter',
                        profile__hr=operator,
                    ).first()
                elif operator_role == 'recruiter':
                    if int(assigned_recruiter_id) != operator.id:
                        return JsonResponse({"Success": False, "Error": "You can only assign evaluators to your own recruiter account."}, status=403)
                    assigned_recruiter = operator

                if not assigned_recruiter:
                    return JsonResponse({"Success": False, "Error": "Selected recruiter is not available in your scope."}, status=400)

            if target_profile.recruiter_id != (assigned_recruiter.id if assigned_recruiter else None):
                target_profile.recruiter = assigned_recruiter
                profile_update_fields.append('recruiter')

        normalized_phone = phone or ''
        if target_profile.phone != normalized_phone:
            target_profile.phone = normalized_phone
            profile_update_fields.append('phone')
        normalized_gender = gender or target_profile.gender or 'other'
        if target_profile.gender != normalized_gender:
            target_profile.gender = normalized_gender
            profile_update_fields.append('gender')

        admin_user = get_admin_for_user(operator)
        admin_company = getattr(admin_user, 'company_profile', None) if admin_user else None
        admin_company_url = ''
        if admin_company:
            admin_company_url = admin_company.website or ''
            if target_profile.company_id != admin_company.id:
                target_profile.company = admin_company
                profile_update_fields.append('company')
        fallback_company_url = getattr(getattr(admin_user, 'profile', None), 'company_url', '') or ''
        resolved_company_url = admin_company_url or fallback_company_url or target_profile.company_url or ''
        if target_profile.company_url != resolved_company_url:
            target_profile.company_url = resolved_company_url
            profile_update_fields.append('company_url')
        if admin_user and target_profile.hr_id != admin_user.id:
            target_profile.hr = admin_user
            profile_update_fields.append('hr')

        if profile_update_fields:
            target_profile.save(update_fields=profile_update_fields)

        recruiter_details = {
            'id': target_user.id,
            'user_id': target_user.id,
            'profile_id': target_profile.id,
            'name': get_display_name(target_user),
            'email': target_user.email,
            'role': target_profile.role,
            'phone': target_profile.phone,
            'gender': target_profile.gender,
            'company_url': target_profile.company_url or '',
            'recruiter_id': target_profile.recruiter_id,
            'recruiter_name': get_display_name(target_profile.recruiter) if target_profile.recruiter_id else '',
        }
        return JsonResponse({"Success": True, "Error": None, "RecruiterData": recruiter_details})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e)})


@login_required
def lookupUserByPhone(request):
    try:
        phone = (request.GET.get('phone') or '').strip()
        normalized = ''.join(ch for ch in phone if ch.isdigit())

        if not normalized:
            return JsonResponse({"Success": False, "Error": "Phone is required.", "Data": {"found": False}})

        query = Q(phone=phone) | Q(phone=normalized)
        if len(normalized) >= 10:
            query = query | Q(phone__endswith=normalized[-10:])

        profile = (
            UserProfile.objects
            .select_related('user')
            .filter(query)
            .first()
        )

        if not profile:
            return JsonResponse({"Success": True, "Error": None, "Data": {"found": False}})

        full_name = f"{profile.user.first_name} {profile.user.last_name}".strip()
        return JsonResponse({
            "Success": True,
            "Error": None,
            "Data": {
                "found": True,
                "user": {
                    "id": profile.user.id,
                    "name": full_name,
                    "email": profile.user.email or '',
                    "phone": profile.phone or '',
                    "gender": profile.gender or '',
                    "role": profile.role or '',
                }
            }
        })
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "Data": {"found": False}})


def candidateSignup(request, token: str = ''):
    token = (token or request.GET.get('token') or request.POST.get('token') or '').strip()
    signup_context = None
    token_error = ''
    interview = None
    user = None
    profile = None
    initial_step = 1

    if token:
        if is_compact_candidate_signup_code(token):
            interview = get_candidate_signup_interview_by_token(token)
            if not interview:
                token_error = 'This signup link is invalid or has expired. You can still sign up by filling the form manually.'
            else:
                user = interview.candidate
                profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': 'candidate'})
                signup_context = build_signup_context_from_user(user, profile, interview)
        else:
            try:
                signup_context = load_candidate_signup_token(token)
            except signing.BadSignature:
                token_error = 'This signup link is invalid or has expired. You can still sign up by filling the form manually.'
            else:
                user = get_object_or_404(User, id=signup_context['user_id'])
                profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': 'candidate'})
                interview = Interview.objects.filter(id=signup_context.get('interview_id')).first()

    if request.method == 'POST':
        manual_mode = signup_context is None
        form = CandidateSignupForm(request.POST, request.FILES, user=user, manual_mode=manual_mode)
        if form.is_valid():
            with transaction.atomic():
                if manual_mode:
                    user = User.objects.create_user(
                        username=build_candidate_username(
                            form.cleaned_data['email'],
                            form.cleaned_data['phone'],
                        ),
                        email=form.cleaned_data['email'],
                        password=form.cleaned_data['password'],
                        first_name=(form.cleaned_data['first_name'] or '').strip(),
                        last_name=(form.cleaned_data['last_name'] or '').strip(),
                    )
                    profile = UserProfile.objects.create(
                        user=user,
                        role='candidate',
                        gender=form.cleaned_data['gender'] or 'other',
                        phone=form.cleaned_data['phone'],
                        profile_picture=form.cleaned_data['profile_picture'],
                        resume=form.cleaned_data['resume'],
                    )
                    signup_context = build_signup_context_from_user(user, profile)
                else:
                    user.set_password(form.cleaned_data['password'])
                    user.save(update_fields=['password'])
                    profile.gender = signup_context.get('gender') or profile.gender or 'other'
                    profile.phone = signup_context.get('phone') or profile.phone
                    profile.role = 'candidate'
                    if form.cleaned_data.get('profile_picture'):
                        profile.profile_picture = form.cleaned_data['profile_picture']
                    if form.cleaned_data.get('resume'):
                        profile.resume = form.cleaned_data['resume']
                    profile.save()

            if profile.resume:
                ResumeProcessingService().process_profile_resume(user, profile, interview=interview)
            send_candidate_welcome_email(request, user, profile, interview=interview)
            return render(request, 'smartInterview/candidate_signup.html', {
                'form': None,
                'initial_step': 1,
                'token_error': token_error,
                'signup_context': signup_context,
                'signup_success': True,
            })
        if any(form.errors.get(field_name) for field_name in ('password', 'confirm_password', 'profile_picture', 'resume')):
            initial_step = 2
    else:
        form = CandidateSignupForm(user=user, manual_mode=signup_context is None)

    return render(request, 'smartInterview/candidate_signup.html', {
        'form': form,
        'initial_step': initial_step,
        'token': token,
        'token_error': token_error,
        'signup_context': signup_context,
        'signup_success': False,
    })


def candidateLogin(request):
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if next_url and not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = ''

    if request.user.is_authenticated:
        role = getattr(getattr(request.user, 'profile', None), 'role', '')
        if role == 'candidate':
            return redirect(next_url or 'candidate-dashboard')
        return redirect('/dashboard')

    if request.method == 'POST':
        post_data = request.POST.copy()
        identifier = (post_data.get('username') or '').strip()
        if '@' in identifier:
            matched_user = User.objects.filter(email__iexact=identifier).first()
            if matched_user:
                post_data['username'] = matched_user.username
        form = CandidateLoginForm(request, data=post_data)
        if form.is_valid():
            user = form.get_user()
            if getattr(getattr(user, 'profile', None), 'role', '') != 'candidate':
                form.add_error(None, 'This portal is available for candidate accounts only.')
            else:
                login(request, user)
                return redirect(next_url or 'candidate-dashboard')
    else:
        form = CandidateLoginForm()

    return render(request, 'smartInterview/candidate_login.html', {'form': form, 'next': next_url})


def candidatePasswordResetStart(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Method not allowed.'}, status=405)

    email = (request.POST.get('email') or '').strip().lower()
    if not email:
        return JsonResponse({'Success': False, 'Error': 'Enter your registered email address.'})

    if candidate_password_reset_rate_limited(request, 'start', email, limit=5, window_seconds=60 * 10):
        return JsonResponse({'Success': False, 'Error': 'Too many reset attempts. Please try again shortly.'}, status=429)

    candidate = (
        User.objects.select_related('profile')
        .filter(email__iexact=email, profile__role='candidate')
        .first()
    )
    phone = normalize_phone(getattr(getattr(candidate, 'profile', None), 'phone', ''))
    if not candidate or not phone:
        clear_candidate_password_reset_state(request)
        return JsonResponse({'Success': False, 'Error': 'We could not verify those account details.'})

    state = {
        'user_id': candidate.id,
        'email': email,
        'phone': phone,
        'masked_phone': mask_phone_last_four(phone),
        'contact_verified': False,
        'otp_verified': False,
        'expires_at': timezone.now().timestamp() + PASSWORD_RESET_MAX_AGE_SECONDS,
    }
    set_candidate_password_reset_state(request, state)
    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'masked_phone': state['masked_phone'],
            'last_four': phone[-4:],
        }
    })


def candidatePasswordResetVerifyPhone(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Method not allowed.'}, status=405)

    state = get_candidate_password_reset_state(request)
    if not state:
        return JsonResponse({'Success': False, 'Error': 'Your reset session has expired. Start again.'})

    phone = normalize_phone(request.POST.get('phone') or '')
    if len(phone) < 10:
        return JsonResponse({'Success': False, 'Error': 'Enter your registered mobile number.'})

    if candidate_password_reset_rate_limited(request, 'phone', state.get('email', ''), limit=5, window_seconds=60 * 10):
        return JsonResponse({'Success': False, 'Error': 'Too many verification attempts. Please try again shortly.'}, status=429)

    expected = state.get('phone', '')
    if not expected or phone[-10:] != expected[-10:]:
        return JsonResponse({'Success': False, 'Error': 'Mobile number does not match our records.'})

    user = User.objects.filter(id=state.get('user_id'), profile__role='candidate').first()
    if not user:
        clear_candidate_password_reset_state(request)
        return JsonResponse({'Success': False, 'Error': 'We could not verify those account details.'})

    otp_result = request_otp(
        phone=expected,
        purpose='password_reset',
        user=user,
        metadata={'source': 'candidate_password_reset'},
    )
    if not otp_result.get('success'):
        return JsonResponse({'Success': False, 'Error': otp_result.get('message') or 'Unable to send OTP right now.'})

    state['contact_verified'] = True
    state['otp_verified'] = False
    state['expires_at'] = timezone.now().timestamp() + PASSWORD_RESET_MAX_AGE_SECONDS
    set_candidate_password_reset_state(request, state)
    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'masked_phone': state['masked_phone'],
            'message': 'OTP sent to your registered mobile number.',
        }
    })


def candidatePasswordResetVerifyOtp(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Method not allowed.'}, status=405)

    state = get_candidate_password_reset_state(request)
    if not state or not state.get('contact_verified'):
        return JsonResponse({'Success': False, 'Error': 'Complete mobile verification first.'})

    otp = (request.POST.get('otp') or '').strip()
    if not otp:
        return JsonResponse({'Success': False, 'Error': 'Enter the OTP sent to your mobile number.'})

    if candidate_password_reset_rate_limited(request, 'otp', state.get('email', ''), limit=10, window_seconds=60 * 10):
        return JsonResponse({'Success': False, 'Error': 'Too many OTP attempts. Please try again shortly.'}, status=429)

    otp_result = verify_otp(phone=state['phone'], otp=otp, purpose='password_reset')
    if not otp_result.get('success'):
        return JsonResponse({'Success': False, 'Error': otp_result.get('message') or 'Invalid OTP.'})

    state['otp_verified'] = True
    state['expires_at'] = timezone.now().timestamp() + PASSWORD_RESET_MAX_AGE_SECONDS
    set_candidate_password_reset_state(request, state)
    return JsonResponse({'Success': True, 'Error': None, 'Data': {'message': 'OTP verified successfully.'}})


def candidatePasswordResetComplete(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Method not allowed.'}, status=405)

    state = get_candidate_password_reset_state(request)
    if not state or not state.get('otp_verified'):
        return JsonResponse({'Success': False, 'Error': 'Verify the OTP before setting a new password.'})

    password = request.POST.get('password') or ''
    confirm_password = request.POST.get('confirm_password') or ''
    if not password or not confirm_password:
        return JsonResponse({'Success': False, 'Error': 'Enter and confirm your new password.'})
    if password != confirm_password:
        return JsonResponse({'Success': False, 'Error': 'Passwords do not match.'})

    if candidate_password_reset_rate_limited(request, 'complete', state.get('email', ''), limit=5, window_seconds=60 * 10):
        return JsonResponse({'Success': False, 'Error': 'Too many password reset attempts. Please try again shortly.'}, status=429)

    user = User.objects.filter(id=state.get('user_id'), profile__role='candidate').first()
    if not user:
        clear_candidate_password_reset_state(request)
        return JsonResponse({'Success': False, 'Error': 'We could not verify those account details.'})

    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return JsonResponse({'Success': False, 'Error': ' '.join(exc.messages)})

    user.set_password(password)
    user.save(update_fields=['password'])
    clear_candidate_password_reset_state(request)
    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'message': 'Password updated successfully. Use your new password to sign in.',
        }
    })


@login_required(login_url='candidate-login')
def candidateDashboard(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        logout(request)
        return redirect('candidate-login')

    profile_saved = request.GET.get('updated') == '1'
    profile_error = ''
    form = CandidateProfileUpdateForm(user=request.user, profile=profile)

    if request.method == 'POST':
        form = CandidateProfileUpdateForm(request.POST, request.FILES, user=request.user, profile=profile)
        if form.is_valid():
            prefs, _ = UserNotificationPreference.objects.get_or_create(user=request.user)
            identity_record = CandidateIdentityVerification.objects.filter(candidate=request.user).first()
            old_email = (request.user.email or '').strip().lower()
            new_email = (form.cleaned_data['email'] or '').strip().lower()
            old_phone = ''.join(ch for ch in (profile.phone or '') if ch.isdigit())
            new_phone = ''.join(ch for ch in (form.cleaned_data['phone'] or '') if ch.isdigit())
            old_name = f"{request.user.first_name} {request.user.last_name}".strip()
            new_first_name = form.cleaned_data['first_name'].strip()
            new_last_name = form.cleaned_data['last_name'].strip()
            new_name = f"{new_first_name} {new_last_name}".strip()
            old_gender = (profile.gender or '').strip().lower()
            new_gender = (form.cleaned_data['gender'] or '').strip().lower()

            request.user.first_name = new_first_name
            request.user.last_name = new_last_name
            request.user.email = new_email
            request.user.username = request.user.username or request.user.email
            request.user.save(update_fields=['first_name', 'last_name', 'email', 'username'])

            profile.phone = new_phone
            profile.gender = new_gender

            if form.cleaned_data.get('profile_picture'):
                profile.profile_picture = form.cleaned_data['profile_picture']

            resume_uploaded = bool(form.cleaned_data.get('resume'))
            if resume_uploaded:
                profile.resume = form.cleaned_data['resume']

            profile.save()

            updated_pref_fields: list[str] = []
            if old_email != new_email:
                prefs.email_verified_at = None
                updated_pref_fields.append('email_verified_at')
            if old_phone != new_phone:
                prefs.phone_verified_at = None
                updated_pref_fields.append('phone_verified_at')
            if updated_pref_fields:
                prefs.save(update_fields=updated_pref_fields + ['updated_at'])

            if identity_record and (old_name != new_name or old_gender != new_gender):
                identity_record.status = CandidateIdentityVerification.Status.NOT_STARTED
                identity_record.comparison = {}
                identity_record.processed_at = None
                identity_record.error_message = 'Identity verification was reset because profile identity fields changed.'
                identity_record.save(update_fields=['status', 'comparison', 'processed_at', 'error_message', 'updated_at'])

            CandidateInsightService().mark_stale(request.user)

            if resume_uploaded:
                latest_interview = get_latest_candidate_interview(request.user)
                ResumeProcessingService().process_profile_resume(request.user, profile, interview=latest_interview)

            return redirect(f"{reverse('candidate-dashboard')}?updated=1")
        profile_error = 'Please correct the highlighted profile fields.'

    return render(request, 'smartInterview/candidate_dashboard.html', build_candidate_dashboard_context(
        request=request,
        user=request.user,
        profile=profile,
        form=form,
        profile_saved=profile_saved,
        profile_error=profile_error,
    ))


def candidateResumeBuilder(request):
    profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None
    is_candidate = bool(request.user.is_authenticated and profile and profile.role == 'candidate')

    if request.method == 'POST' and not is_candidate:
        return JsonResponse({
            'Success': False,
            'Error': 'Please sign in as a candidate to save your resume.',
            'redirect_url': reverse('candidate-login'),
        }, status=403)

    if not is_candidate:
        builder_payload = _resume_builder_preview_payload()
        return render(request, 'smartInterview/resume_builder.html', {
            'candidate': {
                'name': 'Your Name',
                'email': '',
                'profile_picture_url': '',
                'resume_builder_url': reverse('candidate-resume-builder'),
            },
            'resume_builder_payload': builder_payload,
            'resume_builder_updated_at': '',
            'builder_requires_signup': True,
            'builder_login_url': reverse('candidate-login'),
            'builder_signup_url': reverse('candidate-signup'),
            'builder_back_url': reverse('home'),
        })

    draft, _ = CandidateResumeBuilderDraft.objects.get_or_create(candidate=request.user)

    if request.method == 'POST':
        payload_text = request.POST.get('payload', '')
        try:
            raw_payload = json.loads(payload_text or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'Success': False, 'Error': 'Invalid resume builder payload.'}, status=400)

        sanitized_payload = sanitize_resume_builder_payload(raw_payload, user=request.user, profile=profile)
        draft.payload = sanitized_payload
        draft.save(update_fields=['payload', 'updated_at'])
        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'payload': sanitized_payload,
                'updated_at': draft.updated_at.isoformat(),
            },
        })

    builder_payload = build_resume_builder_payload(request.user, profile)
    if not draft.payload:
        draft.payload = builder_payload
        draft.save(update_fields=['payload', 'updated_at'])
    else:
        builder_payload = sanitize_resume_builder_payload(draft.payload, user=request.user, profile=profile)

    return render(request, 'smartInterview/resume_builder.html', {
        'candidate': {
            'name': f"{request.user.first_name} {request.user.last_name}".strip().title() or request.user.username,
            'email': request.user.email or '',
            'profile_picture_url': request.build_absolute_uri(reverse('candidate-secure-profile-picture')) if profile.profile_picture else '',
            'resume_builder_url': reverse('candidate-resume-builder'),
        },
        'resume_builder_payload': builder_payload,
        'resume_builder_updated_at': draft.updated_at.isoformat() if draft.updated_at else '',
        'builder_requires_signup': False,
        'builder_login_url': reverse('candidate-login'),
        'builder_signup_url': reverse('candidate-signup'),
        'builder_back_url': reverse('candidate-dashboard'),
    })


@login_required(login_url='candidate-login')
def candidateResumeBuilderWord(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        raise Http404('Candidate profile not found.')

    payload = build_resume_builder_payload(request.user, profile)
    context = build_resume_builder_export_context(request, request.user, profile, payload)
    try:
        document_rtf = build_resume_export_rtf(context)
        document_bytes = render_word_document_from_rtf(document_rtf)
    except Exception:
        fallback_html = build_resume_export_html(context, '')
        document_bytes = render_word_document_from_html(fallback_html)
    filename = f"{context['candidate']['name'].replace(' ', '_').lower() or 'candidate'}_builder_resume.doc"
    response = HttpResponse(document_bytes, content_type='application/msword')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required(login_url='candidate-login')
def candidateResumeBuilderPdf(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        raise Http404('Candidate profile not found.')

    payload = build_resume_builder_payload(request.user, profile)
    context = build_resume_builder_export_context(request, request.user, profile, payload)
    title = f"{context['candidate']['name']} Resume".strip()
    chrome_html = render_to_string(
        'smartInterview/public_candidate_resume.html',
        {
            **context,
            'export_mode': 'pdf',
            'print_mode': True,
        },
    )
    renderer = 'fallback-text'
    try:
        pdf_bytes, renderer = render_pdf_with_chrome(chrome_html)
    except Exception:
        lines = build_resume_export_lines(context)
        lines.extend(['', 'Renderer hint: fallback-text'])
        pdf_bytes = render_pdf_from_text(lines, title)
    filename = f"{context['candidate']['name'].replace(' ', '_').lower() or 'candidate'}_builder_resume.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Resume-PDF-Renderer'] = renderer
    return response


@login_required(login_url='candidate-login')
def candidateSecureResume(request):
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist as exc:
        raise Http404('Candidate profile not found.') from exc

    if profile.role != 'candidate' or not profile.resume:
        raise Http404('Resume not found.')

    resume_field = profile.resume
    resume_name = os.path.basename(resume_field.name or '') or f'{request.user.username}-resume'
    mime_type, _ = mimetypes.guess_type(resume_name)

    try:
        response = FileResponse(resume_field.open('rb'), content_type=mime_type or 'application/octet-stream')
    except FileNotFoundError as exc:
        raise Http404('Resume file not found.') from exc

    response['Content-Disposition'] = f'inline; filename="{resume_name}"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required(login_url='candidate-login')
def candidateSecureProfilePicture(request):
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist as exc:
        raise Http404('Candidate profile not found.') from exc

    if profile.role != 'candidate' or not profile.profile_picture:
        raise Http404('Profile picture not found.')

    picture_field = profile.profile_picture
    picture_name = os.path.basename(picture_field.name or '') or f'{request.user.username}-profile-picture'
    mime_type, _ = mimetypes.guess_type(picture_name)

    try:
        response = FileResponse(picture_field.open('rb'), content_type=mime_type or 'image/jpeg')
    except FileNotFoundError as exc:
        raise Http404('Profile picture file not found.') from exc

    response['Content-Disposition'] = f'inline; filename="{picture_name}"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def companyLogoFile(request, company_id: int):
    company = get_object_or_404(CompanyProfile, id=company_id)
    if not company.logo:
        raise Http404('Company logo not found.')

    logo_field = company.logo
    logo_name = os.path.basename(logo_field.name or '') or f'company-{company.id}-logo'
    mime_type, _ = mimetypes.guess_type(logo_name)

    try:
        response = FileResponse(logo_field.open('rb'), content_type=mime_type or 'image/jpeg')
    except FileNotFoundError as exc:
        raise Http404('Company logo file not found.') from exc

    response['Content-Disposition'] = f'inline; filename="{logo_name}"'
    response['Cache-Control'] = 'public, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def publicCandidateResume(request, short_code: str):
    public_resume = get_object_or_404(
        CandidatePublicResume.objects.select_related('candidate__profile'),
        short_code=short_code,
        is_active=True,
    )
    public_resume.view_count += 1
    public_resume.last_viewed_at = timezone.now()
    public_resume.save(update_fields=['view_count', 'last_viewed_at', 'updated_at'])

    context = build_public_resume_context(request, public_resume.candidate)
    context['export_mode'] = ''
    context['print_mode'] = request.GET.get('print') == '1'
    return render(request, 'smartInterview/public_candidate_resume.html', context)


def publicJobsPortal(request):
    return render(request, 'smartInterview/jobs_portal.html', build_public_jobs_context(request))


def publicCandidateResumeWord(request, short_code: str):
    public_resume = get_object_or_404(
        CandidatePublicResume.objects.select_related('candidate__profile'),
        short_code=short_code,
        is_active=True,
    )
    CandidatePublicResume.objects.filter(id=public_resume.id).update(download_count=F('download_count') + 1)
    context = build_public_resume_context(request, public_resume.candidate)
    try:
        document_rtf = build_resume_export_rtf(context)
        document_bytes = render_word_document_from_rtf(document_rtf)
    except Exception:
        fallback_html = build_resume_export_html(context, '')
        document_bytes = render_word_document_from_html(fallback_html)
    filename = f"{context['candidate']['name'].replace(' ', '_').lower() or 'candidate'}_resume.doc"
    response = HttpResponse(document_bytes, content_type='application/msword')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def publicCandidateResumePdf(request, short_code: str):
    public_resume = get_object_or_404(
        CandidatePublicResume.objects.select_related('candidate__profile'),
        short_code=short_code,
        is_active=True,
    )
    CandidatePublicResume.objects.filter(id=public_resume.id).update(download_count=F('download_count') + 1)
    context = build_public_resume_context(request, public_resume.candidate)
    title = f"{context['candidate']['name']} Resume".strip()
    chrome_context = {
        **context,
        'candidate': {
            **context['candidate'],
            'profile_picture_url': '',
        },
        'share': {
            **context['share'],
            'share_url': '',
            'pdf_url': '',
            'word_url': '',
        },
    }
    chrome_html = render_to_string(
        'smartInterview/public_candidate_resume.html',
        {
            **chrome_context,
            'export_mode': 'pdf',
            'print_mode': True,
        },
    )
    renderer = 'fallback-text'
    try:
        pdf_bytes, renderer = render_pdf_with_chrome(chrome_html)
    except Exception:
        lines = build_resume_export_lines(context)
        lines.extend(['', 'Renderer hint: fallback-text'])
        pdf_bytes = render_pdf_from_text(lines, title)
    filename = f"{context['candidate']['name'].replace(' ', '_').lower() or 'candidate'}_resume.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Resume-PDF-Renderer'] = renderer
    return response


@csrf_exempt
@login_required(login_url='candidate-login')
def applyToVacancy(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}})

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        return JsonResponse({'Success': False, 'Error': 'Candidate access required.', 'Data': {}})

    vacancy_id = (request.POST.get('vacancy_id') or '').strip()
    if not vacancy_id.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid vacancy is required.', 'Data': {}})

    vacancy = get_object_or_404(Vacancies.objects.prefetch_related('recruiter'), id=int(vacancy_id))
    if vacancy.status in {'closed', 'canceled', 'hired'}:
        return JsonResponse({'Success': False, 'Error': 'This vacancy is no longer open for applications.', 'Data': {}})

    application = CandidateVacancyApplication.objects.filter(candidate=request.user, vacancy=vacancy).first()
    created = application is None
    if application and application.status not in {
        CandidateVacancyApplication.Status.WITHDRAWN,
        CandidateVacancyApplication.Status.REJECTED,
        CandidateVacancyApplication.Status.NOT_INTERESTED,
    }:
        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'created': False,
                'status': application.status,
                'status_label': application.status.replace('_', ' ').title(),
                'message': 'You have already applied for this job. Recruiters will review your profile and update the next step.',
            }
        })
    if not application:
        application = CandidateVacancyApplication.objects.create(
            candidate=request.user,
            vacancy=vacancy,
            status=CandidateVacancyApplication.Status.PENDING_REVIEW,
            pipeline_source=CandidateVacancyApplication.PipelineSource.SELF_APPLIED,
        )
        ensure_application_hiring_started_at(application)
    else:
        application.status = CandidateVacancyApplication.Status.PENDING_REVIEW
        application.reviewed_at = None
        application.save(update_fields=['status', 'reviewed_at', 'updated_at'])
        ensure_application_pipeline_source(application, CandidateVacancyApplication.PipelineSource.SELF_APPLIED)
        ensure_application_hiring_started_at(application)

    notification_result = notify_recruiters_for_candidate_application(request.user, vacancy)
    application.recruiter_notification = notification_result
    application.save(update_fields=['recruiter_notification', 'updated_at'])

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'created': True,
            'status': application.status,
            'status_label': application.status.replace('_', ' ').title(),
            'message': 'Application submitted. Recruiters have been notified and your profile is now pending review.',
            'notification': notification_result,
        }
    })


@csrf_exempt
@login_required(login_url='candidate-login')
def markVacancyNotInterested(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}})

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        return JsonResponse({'Success': False, 'Error': 'Candidate access required.', 'Data': {}})

    vacancy_id = (request.POST.get('vacancy_id') or '').strip()
    if not vacancy_id.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid vacancy is required.', 'Data': {}})

    vacancy = get_object_or_404(Vacancies, id=int(vacancy_id))
    application, _ = CandidateVacancyApplication.objects.get_or_create(
        candidate=request.user,
        vacancy=vacancy,
        defaults={
            'status': CandidateVacancyApplication.Status.NOT_INTERESTED,
            'pipeline_source': CandidateVacancyApplication.PipelineSource.SELF_APPLIED,
        },
    )
    ensure_application_pipeline_source(application, CandidateVacancyApplication.PipelineSource.SELF_APPLIED)
    ensure_application_hiring_started_at(application)
    if application.status != CandidateVacancyApplication.Status.NOT_INTERESTED:
        application.status = CandidateVacancyApplication.Status.NOT_INTERESTED
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'reviewed_at', 'updated_at'])

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'status': application.status,
            'status_label': application.status.replace('_', ' ').title(),
            'message': 'This posting has been hidden from your dashboard.',
            'vacancy_id': vacancy.id,
        }
    })


@csrf_exempt
@login_required(login_url='candidate-login')
def cancelVacancyApplication(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}})

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        return JsonResponse({'Success': False, 'Error': 'Candidate access required.', 'Data': {}})

    vacancy_id = (request.POST.get('vacancy_id') or '').strip()
    if not vacancy_id.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid vacancy is required.', 'Data': {}})

    application = CandidateVacancyApplication.objects.filter(
        candidate=request.user,
        vacancy_id=int(vacancy_id),
    ).first()
    if not application or application.status == CandidateVacancyApplication.Status.WITHDRAWN:
        return JsonResponse({'Success': False, 'Error': 'No active application found for this vacancy.', 'Data': {}})

    application.status = CandidateVacancyApplication.Status.WITHDRAWN
    application.reviewed_at = timezone.now()
    application.save(update_fields=['status', 'reviewed_at', 'updated_at'])

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'status': application.status,
            'status_label': application.status.replace('_', ' ').title(),
            'message': 'Application cancelled successfully. You can apply again later if needed.',
        }
    })


@csrf_exempt
@login_required(login_url='candidate-login')
def saveVacancy(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}})

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        return JsonResponse({'Success': False, 'Error': 'Candidate access required.', 'Data': {}})

    vacancy_id = (request.POST.get('vacancy_id') or '').strip()
    if not vacancy_id.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid vacancy is required.', 'Data': {}})

    vacancy = get_object_or_404(Vacancies, id=int(vacancy_id))
    saved_posting, created = CandidateSavedVacancy.objects.get_or_create(candidate=request.user, vacancy=vacancy)

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'created': created,
            'saved': True,
            'message': 'Posting saved. You can revisit it from your saved section.',
            'vacancy_id': vacancy.id,
        }
    })


@csrf_exempt
@login_required(login_url='candidate-login')
def unsaveVacancy(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}})

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'candidate':
        return JsonResponse({'Success': False, 'Error': 'Candidate access required.', 'Data': {}})

    vacancy_id = (request.POST.get('vacancy_id') or '').strip()
    if not vacancy_id.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid vacancy is required.', 'Data': {}})

    CandidateSavedVacancy.objects.filter(candidate=request.user, vacancy_id=int(vacancy_id)).delete()

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'saved': False,
            'message': 'Posting removed from saved jobs.',
            'vacancy_id': int(vacancy_id),
        }
    })


@login_required
def recruiterApplicationFeed(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in {'recruiter', 'interviewer', 'admin'}:
        return JsonResponse({'Success': False, 'Error': 'Recruiter, interviewer, or admin access required.', 'Data': {}})

    applications_qs = (
        CandidateVacancyApplication.objects
        .select_related('candidate', 'candidate__profile', 'vacancy', 'vacancy__admin')
        .prefetch_related('vacancy__recruiter')
        .filter(status=CandidateVacancyApplication.Status.PENDING_REVIEW)
        .order_by('-applied_at', '-id')
    )
    if profile.role == 'recruiter':
        applications_qs = applications_qs.filter(vacancy__recruiter=request.user)
    elif profile.role == 'interviewer':
        assigned_hr = profile.recruiter
        if assigned_hr:
            applications_qs = applications_qs.filter(vacancy__recruiter=assigned_hr)
        else:
            applications_qs = applications_qs.none()
    else:
        applications_qs = applications_qs.filter(vacancy__admin=request.user)

    applications_qs = applications_qs.distinct()
    applications = []
    for application in applications_qs[:12]:
        candidate = application.candidate
        candidate_profile = getattr(candidate, 'profile', None)
        public_resume = ensure_public_resume(candidate)
        applications.append({
            'id': application.id,
            'candidate_id': candidate.id,
            'candidate_name': get_display_name(candidate),
            'candidate_email': candidate.email,
            'candidate_phone': candidate_profile.phone if candidate_profile else '',
            'vacancy_id': application.vacancy_id,
            'vacancy_role': application.vacancy.role,
            'status': application.status,
            'status_label': application.status.replace('_', ' ').title(),
            'applied_at': application.applied_at.isoformat() if application.applied_at else '',
            'source': application.source,
            'public_profile_url': request.build_absolute_uri(reverse('public-candidate-resume', args=[public_resume.short_code])),
        })

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'count': applications_qs.count(),
            'applications': applications,
            'generated_at': timezone.now().isoformat(),
        }
    })


def build_candidate_export_document_html(
    *,
    rows: list[dict[str, str]],
    status_label: str,
    search_label: str,
    generated_at: str,
) -> str:
    def esc(value: str) -> str:
        return html.escape(str(value or ''))

    row_markup = ''.join(
        f"""
        <tr class="{'row-even' if index % 2 == 0 else 'row-odd'}">
          <td>{esc(row.get('candidateName', ''))}</td>
          <td>{esc(row.get('email', ''))}</td>
          <td>{esc(row.get('role', ''))}</td>
          <td>{esc(row.get('roleId', ''))}</td>
          <td>{esc(row.get('recruiter', ''))}</td>
          <td>{esc(row.get('interviewer', ''))}</td>
          <td>{esc(row.get('status', ''))}</td>
          <td>{esc(row.get('score', ''))}</td>
          <td>{esc(row.get('date', ''))}</td>
          <td>{esc(row.get('notes', ''))}</td>
        </tr>
        """
        for index, row in enumerate(rows)
    )
    executive_summary = (
        f"This report presents {len(rows)} candidate record{'s' if len(rows) != 1 else ''} "
        "from the current dashboard view. It is prepared for recruiter review, hiring coordination, "
        "and stakeholder sharing."
    )
    scope_summary = f"Applied filters: status = {status_label}; search = {search_label}."
    return f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Candidate Data Export</title>
        <style>
          body {{ font-family: Arial, Helvetica, sans-serif; margin: 32px; color: #1d2a36; background: #ffffff; }}
          .header {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 22px; padding-bottom: 18px; border-bottom: 2px solid #dce7f2; }}
          .brand-site {{ font-size: 13px; color: #4d6780; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }}
          .brand h1 {{ margin: 0; font-size: 26px; color: #123b69; }}
          .brand p {{ margin: 6px 0 0; color: #58718a; font-size: 13px; }}
          .meta {{ display: grid; gap: 8px; min-width: 260px; }}
          .meta-card {{ border: 1px solid #d7e3ef; border-radius: 10px; padding: 10px 12px; background: #f8fbff; }}
          .meta-card span {{ display: block; font-size: 11px; text-transform: uppercase; color: #6d8297; letter-spacing: 0.06em; }}
          .meta-card strong {{ display: block; margin-top: 4px; font-size: 14px; color: #12263a; }}
          .summary-panel {{ margin-bottom: 18px; border: 1px solid #d7e3ef; border-radius: 14px; background: linear-gradient(180deg, #f9fbfe, #f4f8fc); padding: 16px 18px; }}
          .summary-panel h2 {{ margin: 0 0 8px; font-size: 16px; color: #123b69; }}
          .summary-panel p {{ margin: 0 0 6px; color: #4d6780; font-size: 13px; line-height: 1.6; }}
          .summary-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }}
          .summary-tile {{ border: 1px solid #d7e3ef; border-radius: 12px; padding: 12px 14px; background: #ffffff; }}
          .summary-tile span {{ display: block; font-size: 11px; color: #6d8297; text-transform: uppercase; letter-spacing: 0.06em; }}
          .summary-tile strong {{ display: block; margin-top: 5px; color: #12263a; font-size: 18px; }}
          table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
          thead th {{ background: #123b69; color: #ffffff; padding: 10px 8px; text-align: left; }}
          tbody td {{ border-bottom: 1px solid #dfe7ef; padding: 9px 8px; vertical-align: top; }}
          .row-even {{ background: #f8fbff; }}
          .row-odd {{ background: #ffffff; }}
          .footer {{ margin-top: 18px; font-size: 11px; color: #6d8297; border-top: 1px solid #dce7f2; padding-top: 12px; }}
        </style>
      </head>
      <body>
        <div class="header">
          <div class="brand">
            <div class="brand-site">shortlistii.com</div>
            <h1>Candidate Data Export</h1>
            <p>Corporate candidate report prepared for hiring reviews, recruiter coordination, and leadership sharing.</p>
          </div>
          <div class="meta">
            <div class="meta-card"><span>Generated At</span><strong>{esc(generated_at)}</strong></div>
            <div class="meta-card"><span>Status Filter</span><strong>{esc(status_label)}</strong></div>
            <div class="meta-card"><span>Search Filter</span><strong>{esc(search_label)}</strong></div>
          </div>
        </div>
        <div class="summary-panel">
          <h2>Report Overview</h2>
          <p>{esc(executive_summary)}</p>
          <p>{esc(scope_summary)}</p>
        </div>
        <div class="summary-grid">
          <div class="summary-tile"><span>Total Candidates</span><strong>{len(rows)}</strong></div>
          <div class="summary-tile"><span>Export Format</span><strong>PDF</strong></div>
          <div class="summary-tile"><span>Prepared For</span><strong>Recruitment Operations</strong></div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Candidate Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Role ID</th>
              <th>Recruiter</th>
              <th>Evaluator</th>
              <th>Status</th>
              <th>Score</th>
              <th>Interview Date</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>{row_markup}</tbody>
        </table>
        <div class="footer">Generated by shortlistii.com • Candidate Data Export Report • {esc(generated_at)}</div>
      </body>
    </html>
    """


@csrf_exempt
@login_required
def exportCandidateDataPdf(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'Success': False, 'Error': 'Invalid request payload.', 'Data': None}, status=400)

    rows = payload.get('rows') or []
    if not isinstance(rows, list) or not rows:
        return JsonResponse({'Success': False, 'Error': 'No candidate rows were provided.', 'Data': None}, status=400)

    generated_at = timezone.localtime(timezone.now()).strftime('%b %d, %Y, %I:%M %p')
    status_label = str(payload.get('statusLabel') or 'All Candidates')
    search_label = str(payload.get('searchLabel') or 'No search applied')
    html_document = build_candidate_export_document_html(
        rows=rows,
        status_label=status_label,
        search_label=search_label,
        generated_at=generated_at,
    )
    pdf_bytes, _renderer = render_pdf_from_html(html_document, request.build_absolute_uri('/'), 'Candidate Data Export')
    filename = f"candidate_data_{timezone.localtime(timezone.now()).strftime('%Y-%m-%d_%H-%M-%S')}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@csrf_exempt
@login_required
def reviewRecruiterApplication(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}}, status=405)

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in {'recruiter', 'interviewer', 'admin'}:
        return JsonResponse({'Success': False, 'Error': 'Recruiter, interviewer, or admin access required.', 'Data': {}}, status=403)

    application_id = (request.POST.get('application_id') or '').strip()
    action = (request.POST.get('action') or '').strip().lower()
    if not application_id.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid application is required.', 'Data': {}}, status=400)
    if action not in {'accept', 'reject'}:
        return JsonResponse({'Success': False, 'Error': 'Action must be accept or reject.', 'Data': {}}, status=400)

    applications_qs = (
        CandidateVacancyApplication.objects
        .select_related('candidate', 'candidate__profile', 'vacancy', 'vacancy__admin')
        .prefetch_related('vacancy__recruiter')
        .filter(id=int(application_id), status=CandidateVacancyApplication.Status.PENDING_REVIEW)
    )

    if profile.role == 'recruiter':
        applications_qs = applications_qs.filter(vacancy__recruiter=request.user)
    elif profile.role == 'interviewer':
        assigned_hr = profile.recruiter
        if assigned_hr:
            applications_qs = applications_qs.filter(vacancy__recruiter=assigned_hr)
        else:
            applications_qs = applications_qs.none()
    else:
        applications_qs = applications_qs.filter(vacancy__admin=request.user)

    application = applications_qs.distinct().first()
    if not application:
        return JsonResponse({'Success': False, 'Error': 'Pending request not found.', 'Data': {}}, status=404)

    candidate = application.candidate
    vacancy = application.vacancy

    with transaction.atomic():
        if action == 'accept':
            application.status = CandidateVacancyApplication.Status.APPROVED
            application.reviewed_at = timezone.now()
            application.save(update_fields=['status', 'reviewed_at', 'updated_at'])
            ensure_application_hiring_started_at(application)

            assigned_recruiter = None
            if profile.role == 'recruiter':
                assigned_recruiter = request.user
            elif profile.role == 'interviewer':
                assigned_recruiter = profile.recruiter
            else:
                assigned_recruiter = vacancy.recruiter.first()

            interview = (
                Interview.objects
                .filter(candidate=candidate, role=vacancy)
                .order_by('-id')
                .first()
            )
            if interview:
                changed_fields = []
                if not interview.recruiter and assigned_recruiter:
                    interview.recruiter = assigned_recruiter
                    changed_fields.append('recruiter')
                if not interview.hr and vacancy.admin:
                    interview.hr = vacancy.admin
                    changed_fields.append('hr')
                if interview.status in {'rejected', 'cancelled'}:
                    interview.status = 'assessment_pending'
                    changed_fields.append('status')
                if changed_fields:
                    interview.save(update_fields=changed_fields)
            else:
                Interview.objects.create(
                    candidate=candidate,
                    recruiter=assigned_recruiter,
                    interviewer=None,
                    hr=vacancy.admin,
                    status='assessment_pending',
                    role=vacancy,
                )
            status_label = 'Accepted'
            message = 'Request accepted and candidate added to the hiring pipeline.'
        else:
            application.status = CandidateVacancyApplication.Status.REJECTED
            application.reviewed_at = timezone.now()
            application.save(update_fields=['status', 'reviewed_at', 'updated_at'])
            status_label = 'Rejected'
            message = 'Request rejected successfully.'

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'application_id': application.id,
            'status': application.status,
            'status_label': status_label,
            'message': message,
            'candidate_id': candidate.id,
            'vacancy_id': vacancy.id,
        }
    })


def build_candidate_dashboard_context(
    request,
    user: User,
    profile: UserProfile,
    form: CandidateProfileUpdateForm,
    profile_saved: bool,
    profile_error: str,
) -> dict:
    interviews = list(
        Interview.objects
        .select_related('role', 'recruiter', 'hr')
        .filter(candidate=user)
        .order_by('-date', '-id')
    )
    latest_resume = (
        CandidateResume.objects
        .filter(candidate=user, is_active=True)
        .prefetch_related('sections')
        .first()
    )
    resume_data = ResumeProcessingService().serialize_resume(latest_resume)
    latest_interview = get_latest_candidate_interview(user)
    insight_service = CandidateInsightService()
    insight_snapshot = CandidateInsightSnapshot.objects.filter(candidate=user).first()
    insight_signature = insight_service.build_signature(user, profile, latest_resume, latest_interview)
    insight_stale = not insight_snapshot or insight_snapshot.source_signature != insight_signature
    insights = insight_service.serialize_snapshot(insight_snapshot)
    insights['stale'] = insight_stale

    prefs, _ = UserNotificationPreference.objects.get_or_create(user=user)
    identity_record = CandidateIdentityVerification.objects.filter(candidate=user).first()
    identity_verified = is_identity_verified(identity_record)

    total_roles = len(interviews)
    active_statuses = {'assessment_pending', 'assessment_completed', 'scheduled', 'shortlisted', 'auto_screening_scheduled'}
    active_roles = sum(1 for item in interviews if item.status in active_statuses)
    completed_scores = [float(item.score) for item in interviews if item.score is not None]
    average_score = round(sum(completed_scores) / len(completed_scores), 1) if completed_scores else None
    next_interview = next((item for item in sorted(interviews, key=lambda x: x.date or timezone.now()) if item.date and item.date >= timezone.now()), None)

    profile_checks = [
        bool(prefs.phone_verified_at),
        bool(prefs.email_verified_at),
        identity_verified,
        bool(profile.profile_picture),
        bool(profile.resume),
        resume_data.get('status') == 'completed',
    ]
    profile_completion = int((sum(profile_checks) / len(profile_checks)) * 100) if profile_checks else 0
    missing_profile_uploads = []
    if not profile.profile_picture:
        missing_profile_uploads.append('profile photo')
    if not profile.resume:
        missing_profile_uploads.append('resume')

    profile_checklist = [
        {'key': 'phone', 'label': 'Phone verified', 'done': bool(prefs.phone_verified_at), 'interactive': True},
        {'key': 'email', 'label': 'Email verified', 'done': bool(prefs.email_verified_at), 'interactive': True},
        {'key': 'identity', 'label': 'Aadhaar verified', 'done': identity_verified, 'interactive': True},
        {'key': 'photo', 'label': 'Profile photo uploaded', 'done': bool(profile.profile_picture), 'interactive': False},
        {'key': 'resume_uploaded', 'label': 'Resume uploaded', 'done': bool(profile.resume), 'interactive': False},
        {'key': 'resume', 'label': 'Resume processed', 'done': resume_data.get('status') == 'completed', 'interactive': False},
    ]

    status_counts: dict[str, int] = defaultdict(int)
    for item in interviews:
        status_counts[normalize_interview_status(item.status)] += 1

    stage_breakdown = [{
        'label': key.replace('_', ' ').title(),
        'count': value,
        'share': int((value / total_roles) * 100) if total_roles else 0,
    } for key, value in sorted(status_counts.items(), key=lambda entry: (-entry[1], entry[0]))]

    timeline = [{
        'role': item.role.role if item.role else 'Role pending',
        'status': normalize_interview_status(item.status),
        'date': item.date,
        'recruiter': f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title() if item.recruiter else 'Not assigned',
        'score': item.score,
    } for item in interviews[:8]]

    resume_skills = (resume_data.get('skills') or [])[:10]
    profile_picture_url = request.build_absolute_uri(reverse('candidate-secure-profile-picture')) if profile.profile_picture else ''
    resume_file_url = request.build_absolute_uri(reverse('candidate-secure-resume')) if profile.resume else ''
    resume_sections = []
    career_objective = ''
    for section in (resume_data.get('sections') or []):
        if section.get('section_key') == 'objective' and not career_objective:
            career_objective = ((section.get('content') or {}).get('text') or section.get('raw_text') or '').strip()
        if section.get('section_key') in {'summary', 'objective', 'skills'}:
            continue
        raw_items = (section.get('content') or {}).get('items') or []
        normalized_items = []
        for item in raw_items:
            normalized_item = normalize_public_section_item(item)
            if normalized_item:
                normalized_items.append(normalized_item)
        resume_sections.append({
            'title': section.get('title') or 'Section',
            'text': (section.get('content') or {}).get('text') or section.get('raw_text') or '',
            'items': normalized_items,
        })

    current_recruiter = next((item['recruiter'] for item in timeline if item.get('recruiter')), 'Not assigned')
    readiness_label = 'Ready for recruiter review'
    if profile_completion < 70:
        readiness_label = 'Profile needs attention'
    elif resume_data.get('status') != 'completed':
        readiness_label = 'Resume processing in progress'
    elif active_roles:
        readiness_label = 'Active in hiring pipeline'

    candidate_initials = ''.join(part[:1].upper() for part in (f"{user.first_name} {user.last_name}".strip().split()[:2])) or (user.username[:2].upper() if user.username else 'NA')
    public_resume = ensure_public_resume(user)
    public_resume_url = request.build_absolute_uri(reverse('public-candidate-resume', args=[public_resume.short_code]))
    admin_scope = profile.hr
    if not admin_scope and latest_interview and latest_interview.hr_id:
        admin_scope = latest_interview.hr

    recent_job_postings_qs = (
        Vacancies.objects
        .select_related('company')
        .prefetch_related('recruiter')
        .exclude(status__in=['closed', 'canceled', 'hired'])
        .order_by('-date', '-id')
    )
    if admin_scope:
        recent_job_postings_qs = recent_job_postings_qs.filter(admin=admin_scope)

    existing_applications = {
        application.vacancy_id: application
        for application in CandidateVacancyApplication.objects.filter(candidate=user)
    }

    recommended_role_tokens = [
        tokenize_text(role_name)
        for role_name in (insights.get('recommended_roles') or [])
        if role_name
    ]
    candidate_role_tokens = tokenize_text(
        ' '.join(filter(None, [
            resume_data.get('headline', ''),
            latest_resume.current_title if latest_resume else '',
            latest_resume.current_company if latest_resume else '',
            latest_interview.role.role if latest_interview and latest_interview.role else '',
        ]))
    )
    candidate_skill_tokens = tokenize_text(' '.join(resume_skills))
    candidate_identity_tokens = candidate_role_tokens | candidate_skill_tokens
    has_ai_role_recommendations = bool(recommended_role_tokens)

    ranked_job_postings = []
    for vacancy in recent_job_postings_qs[:12]:
        recruiter_names = [
            f"{member.first_name} {member.last_name}".strip().title() or member.username
            for member in vacancy.recruiter.all()[:3]
        ]
        vacancy_tokens = tokenize_text(f'{vacancy.role} {vacancy.description}')
        role_tokens = tokenize_text(vacancy.role)
        title_overlap = role_tokens & candidate_role_tokens
        skill_overlap = vacancy_tokens & candidate_skill_tokens
        identity_overlap = role_tokens & candidate_identity_tokens
        score = 0
        if title_overlap:
            score += min(55, 28 + (len(title_overlap) * 9))
        if skill_overlap:
            score += min(30, len(skill_overlap) * 6)
        matching_recommendation = next(
            (index for index, tokens in enumerate(recommended_role_tokens) if tokens and role_tokens & tokens),
            None,
        )
        if matching_recommendation is not None:
            score += max(18, 30 - (matching_recommendation * 6))

        strong_match = bool(title_overlap) or matching_recommendation is not None
        if has_ai_role_recommendations:
            is_relevant = matching_recommendation is not None or (bool(title_overlap) and bool(skill_overlap))
        else:
            is_relevant = (bool(title_overlap) and bool(skill_overlap)) or len(identity_overlap) >= 2
        if score < 40:
            is_relevant = False

        ranked_job_postings.append({
            'id': vacancy.id,
            'role': vacancy.role,
            'position': vacancy.position,
            'job_type': vacancy.get_job_type_display() if vacancy.job_type else '',
            'location': vacancy.location,
            'salary_range': vacancy.salary_range,
            'experience_required': vacancy.experience_required,
            'status': vacancy.status,
            'date': vacancy.date,
            'description': (vacancy.description or '').strip(),
            'recruiters': recruiter_names,
            'company': serialize_company_summary(vacancy.company),
            'match_score': min(score, 100),
            'is_recommended': strong_match,
            'is_relevant': is_relevant,
            'application_status': existing_applications[vacancy.id].status if vacancy.id in existing_applications else '',
        })

    ranked_job_postings.sort(
        key=lambda posting: (
            not posting['is_relevant'],
            -posting['match_score'],
            -((posting['date'] or timezone.now()).timestamp()),
        ),
    )
    ranked_job_postings = [posting for posting in ranked_job_postings if posting['is_relevant']]
    for index, posting in enumerate(ranked_job_postings, start=1):
        posting['modal_id'] = f'vacancyModal{index}'
        posting['has_applied'] = posting['application_status'] in {
            CandidateVacancyApplication.Status.PENDING_REVIEW,
            CandidateVacancyApplication.Status.APPROVED,
        }
        posting['can_cancel_application'] = posting['application_status'] in {
            CandidateVacancyApplication.Status.PENDING_REVIEW,
            CandidateVacancyApplication.Status.APPROVED,
        }
        posting['is_hidden_for_candidate'] = posting['application_status'] == CandidateVacancyApplication.Status.NOT_INTERESTED
        posting['application_label'] = posting['application_status'].replace('_', ' ').title() if posting['application_status'] else 'Apply Now'

    ranked_job_postings = [posting for posting in ranked_job_postings if not posting['is_hidden_for_candidate']]

    visible_job_postings = ranked_job_postings[:4]
    overflow_job_postings = ranked_job_postings[4:]

    return {
        'form': form,
        'profile_saved': profile_saved,
        'profile_error': profile_error,
        'candidate': {
            'name': f"{user.first_name} {user.last_name}".strip().title() or user.username,
            'email': user.email,
            'phone': profile.phone or '',
            'gender': profile.gender or 'other',
            'profile_picture_url': profile_picture_url,
            'resume_file_url': resume_file_url,
            'initials': candidate_initials,
            'public_resume_url': public_resume_url,
            'public_resume_word_url': request.build_absolute_uri(reverse('public-candidate-resume-word', args=[public_resume.short_code])),
            'public_resume_pdf_url': request.build_absolute_uri(reverse('public-candidate-resume-pdf', args=[public_resume.short_code])),
        },
        'verification': {
            'phone_verified': bool(prefs.phone_verified_at),
            'email_verified': bool(prefs.email_verified_at),
            'phone_verified_at': prefs.phone_verified_at,
            'email_verified_at': prefs.email_verified_at,
            'identity_verified': identity_verified,
            'identity_status': identity_record.status if identity_record else CandidateIdentityVerification.Status.NOT_STARTED,
            'identity_method': identity_record.verification_method if identity_record else '',
            'identity_error': identity_record.error_message if identity_record else '',
            'identity_processed_at': identity_record.processed_at if identity_record else None,
        },
        'analytics': {
            'profile_completion': profile_completion,
            'total_roles': total_roles,
            'active_roles': active_roles,
            'average_score': average_score,
            'resume_status': resume_data.get('status', 'missing'),
            'next_interview': next_interview.date if next_interview else None,
            'readiness_label': readiness_label,
            'current_recruiter': current_recruiter,
            'missing_profile_uploads': missing_profile_uploads,
            'has_missing_profile_uploads': bool(missing_profile_uploads),
        },
        'stage_breakdown': stage_breakdown[:5],
        'profile_checklist': profile_checklist,
        'timeline': timeline,
        'resume': {
            'headline': resume_data.get('headline', ''),
            'summary': resume_data.get('summary', ''),
            'career_objective': career_objective,
            'skills': resume_skills,
            'status': resume_data.get('status', 'missing'),
            'processed_at': resume_data.get('processed_at', ''),
            'source_file': resume_data.get('source_file', ''),
            'sections': resume_sections[:6],
        },
        'insights': insights,
        'recent_job_postings': visible_job_postings,
        'more_job_postings': overflow_job_postings,
        'session_timeout_seconds': getattr(settings, 'SESSION_COOKIE_AGE', 1800),
        'session_warning_seconds': getattr(settings, 'SESSION_IDLE_WARNING_SECONDS', 60),
    }


def _candidate_only(request):
    profile = getattr(request.user, 'profile', None)
    return request.user.is_authenticated and profile and profile.role == 'candidate'


@csrf_exempt
@login_required(login_url='candidate-login')
def requestCandidatePhoneVerification(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)

    profile = request.user.profile
    if not profile.phone:
        return JsonResponse({'Success': False, 'Error': 'Add a mobile number before requesting verification.', 'Data': None}, status=400)

    result = request_otp(phone=profile.phone, purpose='verify_phone', user=request.user, metadata={'source': 'candidate_portal'})
    return JsonResponse({'Success': result.get('success', False), 'Error': None if result.get('success') else result.get('message'), 'Data': result}, status=200 if result.get('success') else 400)


@csrf_exempt
@login_required(login_url='candidate-login')
def verifyCandidatePhoneOtp(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)

    otp = (request.POST.get('otp') or '').strip()
    profile = request.user.profile
    if not profile.phone:
        return JsonResponse({'Success': False, 'Error': 'Add a mobile number before verification.', 'Data': None}, status=400)

    result = verify_otp(phone=profile.phone, otp=otp, purpose='verify_phone')
    return JsonResponse({'Success': result.get('success', False), 'Error': None if result.get('success') else result.get('message'), 'Data': result}, status=200 if result.get('success') else 400)


@csrf_exempt
@login_required(login_url='candidate-login')
def requestCandidateEmailVerification(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)
    if not request.user.email:
        return JsonResponse({'Success': False, 'Error': 'Add an email address before requesting verification.', 'Data': None}, status=400)

    result = request_email_otp(email=request.user.email, purpose='verify_email', user=request.user, metadata={'source': 'candidate_portal'})
    return JsonResponse({'Success': result.get('success', False), 'Error': None if result.get('success') else result.get('message'), 'Data': result}, status=200 if result.get('success') else 400)


@csrf_exempt
@login_required(login_url='candidate-login')
def verifyCandidateEmailOtp(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)

    otp = (request.POST.get('otp') or '').strip()
    if not request.user.email:
        return JsonResponse({'Success': False, 'Error': 'Add an email address before verification.', 'Data': None}, status=400)

    result = verify_email_otp(email=request.user.email, otp=otp, purpose='verify_email')
    return JsonResponse({'Success': result.get('success', False), 'Error': None if result.get('success') else result.get('message'), 'Data': result}, status=200 if result.get('success') else 400)


@csrf_exempt
@login_required(login_url='candidate-login')
def triggerCandidateInsights(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)

    profile = request.user.profile
    latest_resume = (
        CandidateResume.objects
        .filter(candidate=request.user, is_active=True)
        .prefetch_related('sections')
        .first()
    )
    latest_interview = get_latest_candidate_interview(request.user)
    service = CandidateInsightService()
    snapshot = service.trigger_generation(request.user, profile, latest_resume, latest_interview)
    data = service.serialize_snapshot(snapshot)
    return JsonResponse({'Success': True, 'Error': None, 'Data': data})


@login_required(login_url='candidate-login')
def candidateInsightStatus(request):
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)
    snapshot = CandidateInsightSnapshot.objects.filter(candidate=request.user).first()
    data = CandidateInsightService().serialize_snapshot(snapshot)
    return JsonResponse({'Success': True, 'Error': None, 'Data': data})


@csrf_exempt
@login_required(login_url='candidate-login')
def submitCandidateIdentityVerification(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)

    mode = (request.POST.get('mode') or '').strip()
    profile = request.user.profile
    service = CandidateIdentityVerificationService()

    try:
        if mode == CandidateIdentityVerification.Method.OFFLINE_XML:
            xml_file = request.FILES.get('xml_file')
            if not xml_file:
                return JsonResponse({'Success': False, 'Error': 'Upload the extracted Aadhaar XML file to continue.', 'Data': None}, status=400)
            record = service.process_offline_xml(request.user, profile, xml_file)
        elif mode == CandidateIdentityVerification.Method.DOCUMENT_UPLOAD:
            pdf_file = request.FILES.get('aadhaar_pdf')
            front_image = request.FILES.get('front_image')
            back_image = request.FILES.get('back_image')
            if not pdf_file and not (front_image and back_image):
                return JsonResponse({'Success': False, 'Error': 'Upload either an Aadhaar PDF or both front and back images.', 'Data': None}, status=400)
            record = service.process_document_upload(
                request.user,
                profile,
                pdf_file=pdf_file,
                front_image=front_image,
                back_image=back_image,
            )
        else:
            return JsonResponse({'Success': False, 'Error': 'Unsupported identity verification mode.', 'Data': None}, status=400)

        matched = is_identity_verified(record)
        message = 'Aadhaar verification completed successfully.' if matched else (record.error_message or 'Aadhaar details could not be matched with your profile.')
        return JsonResponse({
            'Success': matched,
            'Error': None if matched else message,
            'Data': {
                'status': record.status,
                'method': record.verification_method,
                'processed_at': record.processed_at.isoformat() if record.processed_at else '',
                'error_message': record.error_message,
                'matched': matched,
            },
        }, status=200 if matched else 400)
    except Exception as exc:
        return JsonResponse({'Success': False, 'Error': str(exc), 'Data': None}, status=500)


@login_required
def getCandidateProfileData(request, interview_id: int):
    try:
        def trim_text(value, limit: int = 1200) -> str:
            text = str(value or '').strip()
            if len(text) <= limit:
                return text
            return f"{text[:limit].rstrip()}..."

        def compact_resume_payload(payload: dict) -> dict:
            resume_payload = dict(payload or {})
            resume_payload['summary'] = trim_text(resume_payload.get('summary', ''), 1800)
            resume_payload['raw_text_preview'] = trim_text(resume_payload.get('raw_text_preview', ''), 1200)
            resume_payload['ai_raw_preview'] = trim_text(resume_payload.get('ai_raw_preview', ''), 800)
            resume_payload['skills'] = [
                trim_text(skill, 80)
                for skill in (resume_payload.get('skills') or [])[:40]
            ]

            compact_sections = []
            for section in (resume_payload.get('sections') or [])[:12]:
                content = section.get('content') or {}
                raw_items = content.get('items') or []
                compact_items = []
                for item in raw_items[:10]:
                    if isinstance(item, str):
                        compact_items.append(trim_text(item, 220))
                        continue
                    if isinstance(item, dict):
                        compact_item = {}
                        for key, value in list(item.items())[:8]:
                            if isinstance(value, list):
                                compact_item[key] = [trim_text(entry, 140) for entry in value[:6]]
                            elif isinstance(value, str):
                                compact_item[key] = trim_text(value, 220)
                            else:
                                compact_item[key] = value
                        compact_items.append(compact_item)
                compact_sections.append({
                    'section_key': section.get('section_key', ''),
                    'title': trim_text(section.get('title', ''), 80),
                    'section_type': section.get('section_type', ''),
                    'display_order': section.get('display_order', 0),
                    'content': {
                        'text': trim_text(content.get('text', ''), 1400),
                        'items': compact_items,
                    },
                    'raw_text': trim_text(section.get('raw_text', ''), 1200),
                })
            resume_payload['sections'] = compact_sections
            return resume_payload

        def build_file_url(file_field) -> str:
            try:
                return request.build_absolute_uri(file_field.url) if file_field else ''
            except Exception:
                return ''

        interview = (
            get_accessible_interviews(request.user)
            .select_related('candidate', 'candidate__profile', 'recruiter', 'interviewer', 'role')
            .filter(id=interview_id)
            .first()
        )
        if not interview:
            return JsonResponse({'Success': False, 'Error': 'Candidate interview not found.', 'Data': None}, status=404)

        latest_resume = (
            CandidateResume.objects
            .filter(candidate=interview.candidate, is_active=True)
            .prefetch_related('sections')
            .first()
        )
        resume_data = compact_resume_payload(ResumeProcessingService().serialize_resume(latest_resume))
        profile = getattr(interview.candidate, 'profile', None)
        operator_profile = getattr(request.user, 'profile', None)
        operator_role = getattr(operator_profile, 'role', '')
        prefs = UserNotificationPreference.objects.filter(user=interview.candidate).first()
        identity_record = CandidateIdentityVerification.objects.filter(candidate=interview.candidate).first()
        insight_snapshot = CandidateInsightSnapshot.objects.filter(candidate=interview.candidate).first()
        public_resume = CandidatePublicResume.objects.filter(candidate=interview.candidate, is_active=True).first()
        resume_data['file_url'] = build_file_url(getattr(profile, 'resume', None))
        candidate_name = get_display_name(interview.candidate)
        evaluation_summary = build_auto_interview_evaluation_summary(interview)

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'candidate': {
                    'id': interview.id,
                    'user_id': interview.candidate_id,
                    'name': candidate_name,
                    'email': interview.candidate.email,
                    'phone': getattr(profile, 'phone', ''),
                    'candidate_phone_masked': mask_phone_display(getattr(profile, 'phone', '')),
                    'recruiter': get_display_name(interview.recruiter) if interview.recruiter else '',
                    'interviewer': get_display_name(interview.interviewer) if interview.interviewer else '',
                    'role': interview.role.role if interview.role else '',
                    'role_id': interview.role_id,
                    'status': interview.status,
                    'score': interview.score,
                    'date': interview.date.isoformat() if interview.date else '',
                    'profile_picture': build_file_url(getattr(profile, 'profile_picture', None)),
                    'public_resume_downloads': public_resume.download_count if public_resume else 0,
                    'can_call_candidate': bool(
                        operator_role in {'admin', 'recruiter', 'interviewer'}
                        and
                        normalize_phone(getattr(profile, 'phone', ''))
                        and normalize_phone(getattr(operator_profile, 'phone', ''))
                    ),
                },
                'verification': {
                    'phone_verified': bool(getattr(prefs, 'phone_verified_at', None)),
                    'email_verified': bool(getattr(prefs, 'email_verified_at', None)),
                    'identity_verified': is_identity_verified(identity_record),
                    'phone_verified_at': prefs.phone_verified_at.isoformat() if getattr(prefs, 'phone_verified_at', None) else '',
                    'email_verified_at': prefs.email_verified_at.isoformat() if getattr(prefs, 'email_verified_at', None) else '',
                    'identity_verified_at': identity_record.processed_at.isoformat() if identity_record and identity_record.processed_at else '',
                    'identity_status': identity_record.status if identity_record else CandidateIdentityVerification.Status.NOT_STARTED,
                },
                'insights': CandidateInsightService().serialize_snapshot(insight_snapshot),
                'resume': resume_data,
                'evaluation_summary': evaluation_summary,
            }
        })
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': None}, status=500)


@login_required
def getCandidateEvaluationSummary(request, interview_id: int):
    try:
        interview = get_accessible_interviews(request.user).filter(id=interview_id).first()
        if not interview:
            return JsonResponse({'Success': False, 'Error': 'Candidate interview not found.', 'Data': None}, status=404)

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'evaluation_summary': build_auto_interview_evaluation_summary(interview),
            },
        })
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': None}, status=500)


@csrf_exempt
@login_required
def callCandidateProfile(request, interview_id: int):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)

    try:
        operator_profile = getattr(request.user, 'profile', None)
        if not operator_profile or operator_profile.role not in {'admin', 'recruiter', 'interviewer'}:
            return JsonResponse({'Success': False, 'Error': 'Calling is restricted to workspace users.', 'Data': None}, status=403)

        interview = (
            get_accessible_interviews(request.user)
            .select_related('candidate', 'candidate__profile', 'recruiter', 'interviewer', 'role')
            .filter(id=interview_id)
            .first()
        )
        if not interview:
            return JsonResponse({'Success': False, 'Error': 'Candidate interview not found.', 'Data': None}, status=404)

        caller_phone = normalize_phone(getattr(operator_profile, 'phone', '') or '')
        if len(caller_phone) < 12:
            return JsonResponse({
                'Success': False,
                'Error': 'Add your registered mobile number to place Exotel calls.',
                'Data': None,
            }, status=400)

        candidate_profile = getattr(interview.candidate, 'profile', None)
        candidate_phone = normalize_phone(getattr(candidate_profile, 'phone', '') or '')
        if len(candidate_phone) < 12:
            return JsonResponse({
                'Success': False,
                'Error': 'Candidate phone number is not available for calling.',
                'Data': None,
            }, status=400)

        call_result = exotel_voice_provider.connect_agent_to_candidate(
            agent_phone=caller_phone,
            candidate_phone=candidate_phone,
            interview_id=interview.id,
            metadata={'TimeLimit': request.POST.get('time_limit') or '900'},
        )
        if not call_result.success:
            return JsonResponse({
                'Success': False,
                'Error': call_result.error_message or 'Unable to start the Exotel call right now.',
                'Data': {
                    'caller_phone_masked': mask_phone_display(caller_phone),
                    'candidate_phone_masked': mask_phone_display(candidate_phone),
                }
            }, status=502)

        session = interview_call_service.create_session(
            interview=interview,
            initiated_by=request.user,
            caller_phone=caller_phone,
            candidate_phone=candidate_phone,
            provider_result=call_result,
        )

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'call_sid': call_result.provider_message_id,
                'session': interview_call_service.serialize_session(session),
                'caller_phone_masked': mask_phone_display(caller_phone),
                'candidate_phone_masked': mask_phone_display(candidate_phone),
            }
        })
    except Exception as e:
        logger.exception('Unable to initiate Exotel call for candidate profile')
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': None}, status=500)


@login_required
def getCandidateCallSession(request, interview_id: int, session_id: int):
    if request.method != 'GET':
        return JsonResponse({'Success': False, 'Error': 'Only GET is allowed.', 'Data': None}, status=405)

    try:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role not in {'admin', 'recruiter', 'interviewer'}:
            return JsonResponse({'Success': False, 'Error': 'Calling is restricted to workspace users.', 'Data': None}, status=403)

        session = interview_call_service.get_session(user=request.user, interview_id=interview_id, session_id=session_id)
        if not session:
            return JsonResponse({'Success': False, 'Error': 'Call session not found.', 'Data': None}, status=404)

        session = interview_call_service.refresh_session(session)
        return JsonResponse({'Success': True, 'Error': None, 'Data': interview_call_service.serialize_session(session)})
    except Exception as exc:
        logger.exception('Unable to fetch Exotel call session status')
        return JsonResponse({'Success': False, 'Error': str(exc), 'Data': None}, status=500)


@csrf_exempt
@login_required
def disconnectCandidateCallSession(request, interview_id: int, session_id: int):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)

    try:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role not in {'admin', 'recruiter', 'interviewer'}:
            return JsonResponse({'Success': False, 'Error': 'Calling is restricted to workspace users.', 'Data': None}, status=403)

        session = interview_call_service.get_session(user=request.user, interview_id=interview_id, session_id=session_id)
        if not session:
            return JsonResponse({'Success': False, 'Error': 'Call session not found.', 'Data': None}, status=404)

        result = interview_call_service.disconnect_session(session)
        session.refresh_from_db()
        if not result.success:
            return JsonResponse({
                'Success': False,
                'Error': result.error_message or 'Unable to disconnect the Exotel call right now.',
                'Data': interview_call_service.serialize_session(session),
            }, status=502)

        return JsonResponse({'Success': True, 'Error': None, 'Data': interview_call_service.serialize_session(session)})
    except Exception as exc:
        logger.exception('Unable to disconnect Exotel call session')
        return JsonResponse({'Success': False, 'Error': str(exc), 'Data': None}, status=500)


@login_required
def resumeProcessingHealth(request):
    try:
        if not getattr(request.user, 'profile', None) or request.user.profile.role != 'admin':
            return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)
        data = ResumeProcessingService().health_check()
        return JsonResponse({'Success': True, 'Error': None, 'Data': data})
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': None}, status=500)


@csrf_exempt
@login_required
def reprocessCandidateResume(request, interview_id: int):
    try:
        if request.method != 'POST':
            return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)

        interview = (
            Interview.objects
            .select_related('candidate', 'candidate__profile')
            .filter(id=interview_id)
            .first()
        )
        if not interview:
            return JsonResponse({'Success': False, 'Error': 'Candidate interview not found.', 'Data': None}, status=404)

        profile = getattr(interview.candidate, 'profile', None)
        if not profile or not profile.resume:
            return JsonResponse({'Success': False, 'Error': 'No stored resume available for this candidate.', 'Data': None}, status=400)

        resume = ResumeProcessingService().process_profile_resume(interview.candidate, profile, interview=interview)
        CandidateInsightService().mark_stale(interview.candidate)
        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'resume_id': resume.id,
                'status': resume.status,
                'processed_at': resume.processed_at.isoformat() if resume.processed_at else '',
                'error_message': resume.error_message,
            }
        })
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': None}, status=500)


@csrf_exempt
@login_required(login_url='candidate-login')
def refreshCandidateResumeDetails(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': None}, status=405)
    if not _candidate_only(request):
        return JsonResponse({'Success': False, 'Error': 'Unauthorized', 'Data': None}, status=403)

    try:
        profile = request.user.profile
        if not profile.resume:
            return JsonResponse({'Success': False, 'Error': 'Upload a resume before refreshing resume details.', 'Data': None}, status=400)

        latest_interview = get_latest_candidate_interview(request.user)
        resume = ResumeProcessingService().process_profile_resume(request.user, profile, interview=latest_interview)
        CandidateInsightService().mark_stale(request.user)
        resume_data = ResumeProcessingService().serialize_resume(resume)

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'resume': resume_data,
                'analytics': {
                    'resume_status': resume_data.get('status', 'missing'),
                },
            }
        })
    except Exception as exc:
        return JsonResponse({'Success': False, 'Error': str(exc), 'Data': None}, status=500)

def generate_username(name: str) -> str:
    parts = name.split(" ")
    first = parts[0].lower()
    last = parts[1].lower() if len(parts) > 1 else ""

    # base pattern: firstname + lastname + random 4 digits
    base_username = f"{first}{last}{random.randint(1000, 9999)}"

    # ensure uniqueness in User table
    while User.objects.filter(username=base_username).exists():
        base_username = f"{first}{last}{random.randint(1000, 9999)}"

    return base_username

@csrf_exempt
@login_required
def addRole(request):
    try:
        with transaction.atomic():
            name = request.POST.get('name', '')
            description = request.POST.get('description', '')
            vacancies = request.POST.get('vacancies', '')
            job_type = request.POST.get('job_type', '')
            location = request.POST.get('location', '')
            salary_range = request.POST.get('salary_range', '')
            experience_required = request.POST.get('experience_required', '')
            status = request.POST.get('status', '')
            recruiter_ids = request.POST.getlist('recruiter')
            if not recruiter_ids:
                single_recruiter = request.POST.get('recruiter', '')
                if single_recruiter:
                    recruiter_ids = [single_recruiter]
            user = User.objects.get(username=request.user.username)
            current_role = get_user_role(user)
            if current_role not in {'admin', 'recruiter'}:
                return JsonResponse({"Success": False, "Error": "Only admins or recruiters can post jobs.", "Data": ""})

            admin_user = get_admin_for_user(user)
            if not admin_user:
                return JsonResponse({"Success": False, "Error": "Unable to resolve admin scope for this job posting.", "Data": ""})

            linked_company = getattr(admin_user, 'company_profile', None)
            if linked_company is None:
                linked_company = getattr(getattr(user, 'profile', None), 'company', None)

            if current_role == 'recruiter' and not recruiter_ids:
                recruiter_ids = [str(user.id)]

            valid_recruiters = User.objects.filter(id__in=recruiter_ids, profile__role='recruiter')
            if not valid_recruiters.exists():
                return JsonResponse({"Success": False, "Error": "Please select at least one valid recruiter.", "Data": ""})

            obj = Vacancies(
                    role=name,
                    description=description,
                    position=int(vacancies) if vacancies.isdigit() else 0,
                    job_type=(job_type or '').strip(),
                    location=(location or '').strip(),
                    salary_range=(salary_range or '').strip(),
                    experience_required=(experience_required or '').strip(),
                    status=status,
                    company=linked_company,
                    admin=admin_user,
            )
            obj.save()
            obj.recruiter.add(*valid_recruiters)
        return JsonResponse({
            "Success": True,
            "Error": None,
            "Data": {
                "RoleDetails": {
                    "id": obj.id,
                    "name": obj.role,
                    "description": obj.description,
                    "vacancies": obj.position,
                    "job_type": obj.get_job_type_display() if obj.job_type else '',
                    "location": obj.location,
                    "salary_range": obj.salary_range,
                    "experience_required": obj.experience_required,
                    "date": obj.date,
                    "status": obj.status,
                    "company": serialize_company_summary(obj.company, request=request),
                }
            }
        })
    except Exception as e:
        return JsonResponse({"Success": False, "Error": e, "Data": ""})


@csrf_exempt
@login_required
def closeVacancy(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}}, status=405)

    current_user = get_object_or_404(User, username=request.user.username)
    current_role = get_user_role(current_user)
    if current_role not in {'admin', 'recruiter'}:
        return JsonResponse({'Success': False, 'Error': 'Admin or recruiter access is required.', 'Data': {}}, status=403)

    vacancy_id_raw = (request.POST.get('vacancy_id') or '').strip()
    if not vacancy_id_raw.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid vacancy is required.', 'Data': {}}, status=400)

    admin_scope = get_admin_for_user(current_user)
    if not admin_scope:
        return JsonResponse({'Success': False, 'Error': 'Unable to resolve admin scope for this vacancy.', 'Data': {}}, status=403)

    vacancies_qs = Vacancies.objects.filter(id=int(vacancy_id_raw), admin=admin_scope)
    if current_role == 'recruiter':
        vacancies_qs = vacancies_qs.filter(recruiter=current_user)

    vacancy = vacancies_qs.first()
    if vacancy is None:
        return JsonResponse({'Success': False, 'Error': 'Vacancy not found.', 'Data': {}}, status=404)

    if vacancy.status == 'closed':
        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'vacancy_id': vacancy.id,
                'status': vacancy.status,
                'status_label': vacancy.get_status_display(),
            }
        })

    vacancy.status = 'closed'
    vacancy.save(update_fields=['status'])

    return JsonResponse({
        'Success': True,
        'Error': None,
        'Data': {
            'vacancy_id': vacancy.id,
            'status': vacancy.status,
            'status_label': vacancy.get_status_display(),
        }
    })

@login_required
def getRoleList(request):
    try:
        current_user = get_object_or_404(User, username=request.user.username)
        current_role = get_user_role(current_user)
        admin_scope = get_admin_for_user(current_user)
        if not admin_scope:
            return JsonResponse({"Success": True, "Error": None, "RoleData": []})

        role_data = (
            Vacancies.objects
            .filter(admin=admin_scope)
            .select_related('company', 'admin', 'admin__company_profile')
            .prefetch_related('recruiter')
            .annotate(
                applications_count=Count('interviews', distinct=True),
                hired_count=Count('interviews', filter=Q(interviews__status='hired'), distinct=True),
                active_pipeline_count=Count(
                    'interviews',
                    filter=Q(interviews__status__in=[
                        'scheduled',
                        'shortlisted',
                        'assessment_pending',
                        'assessment_completed',
                        'auto_screening_scheduled',
                    ]),
                    distinct=True,
                ),
            )
            .order_by('-date', '-id')
        )

        if current_role == 'recruiter':
            role_data = role_data.filter(recruiter=current_user).distinct()

        role_list = []
        for role in role_data:
            vacancy_count = int(role.position) if str(role.position).isdigit() else 0
            role_details = build_vacancy_card_payload(role, include_external_company_logo=False, request=request)
            role_details['name'] = role.role
            role_details['vacancies'] = vacancy_count
            role_details['applications'] = int(role.applications_count or 0)
            role_details['hired'] = int(role.hired_count or 0)
            role_details['inprogress'] = int(role.active_pipeline_count or 0)
            role_details['open_positions'] = max(vacancy_count - role_details['hired'], 0)
            role_details['recruiter_count'] = len(role_details.get('recruiters', []))
            role_list.append(role_details)
        return JsonResponse({"Success":True, "Error":None, "RoleData":role_list})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})

@login_required
def getRoleData(request, id):
    try:
        role_data = Vacancies.objects.select_related('company').get(id=id)

        # Get queryset of interviews
        interviews = Interview.objects.filter(role=role_data)
        # Total number of interviews (rows)
        total_interviews = interviews.count()
        # Count interviews by status
        interview_counts = (
            interviews
            .annotate(
                normalized_status=Case(
                    When(status__in=["shortlisted", "assessment_Pending", "assessment_pending", "assessment pending"], then=Value("shortlisted")),
                    default="status",  # keep other statuses unchanged
                    output_field=CharField()
                )
            )
            .values("normalized_status")
            .annotate(count=Count("id"))
        )

        # Convert to dictionary: {status: count}
        counts = {item['normalized_status']: item['count'] for item in interview_counts}

        role_details = {}
        role_details['id'] = role_data.id
        role_details['name'] = role_data.role
        role_details['description'] = role_data.description
        role_details['position'] = role_data.position
        role_details['job_type'] = role_data.get_job_type_display() if role_data.job_type else ''
        role_details['location'] = role_data.location
        role_details['salary_range'] = role_data.salary_range
        role_details['experience_required'] = role_data.experience_required
        role_details['status'] = role_data.status
        role_details['date'] = role_data.date
        role_details['company'] = serialize_company_summary(role_data.company, request=request)
        role_details["applications"] = total_interviews,
        role_details["hired"] = counts.get("hired", 0),
        role_details["inprogress"] = counts.get("shortlisted", 0),

        return JsonResponse({"Success":True, "Error":None, "RoleData":role_details})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})


@login_required
def getHrList(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        recruiter_data = (
            UserProfile.objects
            .filter(hr=admin, role='recruiter')
            .exclude(user__username__iexact='TBD')
            .annotate(
                interviewers_count=Count('user__recruiter_interviews__interviewer', distinct=True),
                candidates_count=Count(
                    'user__recruiter_interviews__candidate',
                    filter=Q(user__recruiter_interviews__interviewer__isnull=False),
                    distinct=True
                ),
            )
            .order_by('user__first_name', 'user__last_name')
        )
        recruiter_list = []
        for recruiter in recruiter_data:
            recruiter_details = {}
            recruiter_details['id'] = recruiter.user.id
            recruiter_details['user_id'] = recruiter.user.id
            recruiter_details['profile_id'] = recruiter.id
            recruiter_details['name'] = get_display_name(recruiter.user)
            recruiter_details['email'] = recruiter.user.email
            recruiter_details['role'] = recruiter.role
            recruiter_details['phone'] = recruiter.phone
            recruiter_details['gender'] = recruiter.gender
            recruiter_details['company_url'] = recruiter.company_url or ''
            recruiter_details['interviewers_count'] = recruiter.interviewers_count
            recruiter_details['candidates_count'] = recruiter.candidates_count
            recruiter_list.append(recruiter_details)
        return JsonResponse({"Success":True, "Error":None, "RecruiterData":recruiter_list})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})

@login_required
def getEvaluator(request):
    try:
        current_user = get_object_or_404(User, username=request.user.username)
        current_role = get_user_role(current_user)
        admin_user = get_admin_for_user(current_user)
        if not admin_user:
            return JsonResponse({"Success": True, "Error": None, "RecruiterData": []})

        interviews_qs = Interview.objects.select_related(
            'interviewer', 'interviewer__profile', 'recruiter'
        ).filter(hr=admin_user, interviewer__isnull=False)

        if current_role == 'recruiter':
            interviews_qs = interviews_qs.filter(recruiter=current_user)

        interviewer_ids = list(
            interviews_qs.values_list('interviewer_id', flat=True).distinct()
        )

        recruiter_data = (
            UserProfile.objects
            .select_related('user')
            .filter(user_id__in=interviewer_ids, role='interviewer')
            .exclude(user__username__iexact='TBD')
            .order_by('user__first_name', 'user__last_name')
        )

        interview_counts = {
            item['interviewer']: item['count']
            for item in interviews_qs.values('interviewer').annotate(count=Count('id'))
        }

        recruiter_names_by_interviewer: dict[int, list[str]] = defaultdict(list)
        for item in interviews_qs.exclude(recruiter__isnull=True):
            interviewer_id = item.interviewer_id
            recruiter_name = f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title()
            if recruiter_name and recruiter_name not in recruiter_names_by_interviewer[interviewer_id]:
                recruiter_names_by_interviewer[interviewer_id].append(recruiter_name)

        recruiter_list = []
        for recruiter in recruiter_data:
            recruiter_details = {}
            recruiter_details['id'] = recruiter.user_id
            recruiter_details['user_id'] = recruiter.user_id
            recruiter_details['profile_id'] = recruiter.id
            recruiter_details['name'] = get_display_name(recruiter.user)
            recruiter_details['email'] = recruiter.user.email
            recruiter_details['role'] = recruiter.role
            recruiter_details['phone'] = recruiter.phone
            recruiter_details['gender'] = recruiter.gender
            recruiter_details['interviews_count'] = interview_counts.get(recruiter.user_id, 0)
            linked_names = recruiter_names_by_interviewer.get(recruiter.user_id, [])
            recruiter_details['recruiter_id'] = recruiter.recruiter_id
            recruiter_details['recruiter_name'] = get_display_name(recruiter.recruiter) if recruiter.recruiter_id else ''
            recruiter_details['recruiters_count'] = len(linked_names)
            recruiter_details['hr_id'] = recruiter.recruiter_id if current_role == 'recruiter' else recruiter.hr_id
            recruiter_details['hr_name'] = ', '.join(linked_names[:3])
            recruiter_list.append(recruiter_details)
        return JsonResponse({"Success":True, "Error":None, "RecruiterData":recruiter_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "RecruiterData": []})

@csrf_exempt
@login_required
def evaluatorSearch(request):
    try:
        current_user = get_object_or_404(User, username=request.user.username)
        name = (request.POST.get('name') or '').strip()
        current_role = get_user_role(current_user)
        admin_user = get_admin_for_user(current_user)
        if not admin_user:
            return JsonResponse({"Success": True, "Error": None, "RecruiterData": []})

        interviews_qs = Interview.objects.select_related(
            'interviewer', 'interviewer__profile', 'recruiter'
        ).filter(hr=admin_user, interviewer__isnull=False)

        if current_role == 'recruiter':
            interviews_qs = interviews_qs.filter(recruiter=current_user)

        if name:
            interviews_qs = interviews_qs.filter(
                Q(interviewer__first_name__icontains=name)
                | Q(interviewer__last_name__icontains=name)
                | Q(interviewer__email__icontains=name)
                | Q(interviewer__profile__phone__icontains=name)
                | Q(recruiter__first_name__icontains=name)
                | Q(recruiter__last_name__icontains=name)
            )

        interviewer_ids = list(
            interviews_qs.values_list('interviewer_id', flat=True).distinct()
        )

        recruiter_data = (
            UserProfile.objects
            .select_related('user')
            .filter(user_id__in=interviewer_ids, role='interviewer')
            .exclude(user__username__iexact='TBD')
            .order_by('user__first_name', 'user__last_name')
        )

        interview_counts = {
            item['interviewer']: item['count']
            for item in interviews_qs.values('interviewer').annotate(count=Count('id'))
        }

        recruiter_names_by_interviewer: dict[int, list[str]] = defaultdict(list)
        for item in interviews_qs.exclude(recruiter__isnull=True):
            interviewer_id = item.interviewer_id
            recruiter_name = f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title()
            if recruiter_name and recruiter_name not in recruiter_names_by_interviewer[interviewer_id]:
                recruiter_names_by_interviewer[interviewer_id].append(recruiter_name)

        recruiter_list = []
        for recruiter in recruiter_data:
            recruiter_details = {}
            recruiter_details['id'] = recruiter.user_id
            recruiter_details['user_id'] = recruiter.user_id
            recruiter_details['profile_id'] = recruiter.id
            recruiter_details['name'] = get_display_name(recruiter.user)
            recruiter_details['email'] = recruiter.user.email
            recruiter_details['role'] = recruiter.role
            recruiter_details['phone'] = recruiter.phone
            recruiter_details['gender'] = recruiter.gender
            recruiter_details['interviews_count'] = interview_counts.get(recruiter.user_id, 0)
            recruiter_details['recruiter_id'] = recruiter.recruiter_id
            recruiter_details['recruiter_name'] = get_display_name(recruiter.recruiter) if recruiter.recruiter_id else ''
            recruiter_details['hr_name'] = ', '.join(recruiter_names_by_interviewer.get(recruiter.user_id, [])[:3])
            recruiter_list.append(recruiter_details)
        return JsonResponse({"Success": True, "Error": None, "RecruiterData": recruiter_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "RecruiterData": []})

@csrf_exempt
@login_required
def getInterviewsForProfile(request):
    try:
        recruiter_email = (
            request.POST.get('recruiter')
            or request.POST.get('recruiter_email')
            or request.GET.get('recruiter')
            or request.GET.get('recruiter_email')
            or ''
        ).strip()
        recruiter_id = (
            request.POST.get('recruiter_id')
            or request.GET.get('recruiter_id')
            or ''
        ).strip()
        profile_type = (
            request.POST.get('profile_type')
            or request.GET.get('profile_type')
            or 'evaluator'
        ).strip().lower()

        current_user = get_object_or_404(User, username=request.user.username)
        admin_user = get_admin_for_user(current_user)
        target_user = None
        target_role = 'recruiter' if profile_type == 'recruiter' else 'interviewer'

        if not admin_user:
            return JsonResponse({"Success": False, "Error": "Admin scope not found.", "Interviews": []})

        if recruiter_email:
            target_user = User.objects.filter(email__iexact=recruiter_email, profile__role=target_role).first()

        if target_user is None and recruiter_id.isdigit():
            lookup_id = int(recruiter_id)
            profile = UserProfile.objects.filter(
                Q(id=lookup_id) | Q(user_id=lookup_id),
                role=target_role
            ).select_related('user').first()
            if profile:
                target_user = profile.user
            else:
                target_user = User.objects.filter(id=lookup_id, profile__role=target_role).first()

        if target_user is None:
            return JsonResponse({"Success": False, "Error": f"{target_role.title()} not found.", "Interviews": []})

        if target_role == 'recruiter':
            interviews = (
                Interview.objects
                .select_related('candidate', 'role', 'recruiter', 'interviewer')
                .filter(hr=admin_user, recruiter=target_user, interviewer__isnull=False)
                .order_by('-date')[:1000]
            )
        else:
            interviews = (
                Interview.objects
                .select_related('candidate', 'role', 'recruiter', 'interviewer')
                .filter(hr=admin_user, interviewer=target_user)
            )
            if get_user_role(current_user) == 'recruiter':
                interviews = interviews.filter(recruiter=current_user)
            interviews = interviews.order_by('-date')[:1000]
        interview_list = []

        for interview in interviews:
            interview_details = {}
            interview_details['id'] = interview.id
            interview_details['candidate'] = f"{interview.candidate.first_name} {interview.candidate.last_name}".title()
            interview_details['status'] = interview.status
            interview_details['score'] = interview.score
            interview_details['role'] = interview.role.role if interview.role else ''
            interview_details['date'] = interview.date.isoformat() if interview.date else ''
            interview_details['recruiter'] = (
                f"{interview.recruiter.first_name} {interview.recruiter.last_name}".strip().title()
                if interview.recruiter else ''
            )
            interview_details['interviewer'] = (
                f"{interview.interviewer.first_name} {interview.interviewer.last_name}".strip().title()
                if interview.interviewer else ''
            )
            interview_details['admin_id'] = admin_user.id if admin_user else None
            interview_list.append(interview_details)
            
        return JsonResponse({"Success": True, "Error": None, "Interviews": interview_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "Interviews": []})

@login_required
def getVacancyReruiters(request, id):
    try:
        tbd_obj = User.objects.get(username='TBD')
        vacancy = Vacancies.objects.get(id=id)
        vacancy.recruiter.add(tbd_obj)
        recruiters = vacancy.recruiter.all()
        recruiter_list = []
        for recruiter in recruiters:
            recruiter_details = {}
            recruiter_details['id'] = recruiter.id
            recruiter_details['name'] = (recruiter.first_name + " " + recruiter.last_name).title()
            recruiter_details['email'] = recruiter.email
            recruiter_list.append(recruiter_details)
        return JsonResponse({"Success": True, "Error": None, "RecruiterData": recruiter_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e)})


@login_required
def candidatesTabData(request):
    try:
        interviews = get_accessible_interviews(request.user).order_by('-date')

        status_counts = defaultdict(int)
        role_agg = defaultdict(lambda: {"count": 0, "hired": 0, "scheduled": 0})
        recruiter_agg = defaultdict(int)
        candidate_rows = []

        for item in interviews:
            normalized = normalize_interview_status(item.status)
            status_counts[normalized] += 1

            role_name = item.role.role if item.role else 'Unassigned'
            role_agg[role_name]["count"] += 1
            if normalized in ['completed', 'hired']:
                role_agg[role_name]["hired"] += 1
            if normalized == 'scheduled':
                role_agg[role_name]["scheduled"] += 1

            recruiter_name = (
                f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title()
                if item.recruiter else 'Unassigned'
            )
            interviewer_name = (
                f"{item.interviewer.first_name} {item.interviewer.last_name}".strip().title()
                if item.interviewer else recruiter_name
            )
            recruiter_agg[interviewer_name] += 1

            candidate_rows.append({
                "id": item.id,
                "name": f"{item.candidate.first_name} {item.candidate.last_name}".strip().title(),
                "email": item.candidate.email,
                "status": normalized,
                "recruiter": recruiter_name,
                "interviewer": interviewer_name,
                "role": role_name,
                "role_id": item.role.id if item.role else None,
                "score": float(item.score) if item.score is not None else None,
                "date": item.date.isoformat() if item.date else '',
            })

        upcoming_qs = (
            interviews
            .filter(status='scheduled', date__gte=timezone.now())
            .order_by('date')[:8]
        )
        upcoming = []
        for item in upcoming_qs:
            upcoming.append({
                "id": item.id,
                "candidate": f"{item.candidate.first_name} {item.candidate.last_name}".strip().title(),
                "role": item.role.role if item.role else 'Unassigned',
                "recruiter": (
                    f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title()
                    if item.recruiter else 'Unassigned'
                ),
                "interviewer": (
                    f"{item.interviewer.first_name} {item.interviewer.last_name}".strip().title()
                    if item.interviewer else 'Unassigned'
                ),
                "date": item.date.isoformat() if item.date else '',
                "status": 'scheduled',
            })

        role_breakdown = [
            {
                "role": role_name,
                "count": values["count"],
                "hired": values["hired"],
                "scheduled": values["scheduled"],
            }
            for role_name, values in role_agg.items()
        ]
        role_breakdown.sort(key=lambda x: x["count"], reverse=True)

        recruiter_breakdown = [
            {"name": name, "count": count}
            for name, count in recruiter_agg.items()
        ]
        recruiter_breakdown.sort(key=lambda x: x["count"], reverse=True)

        summary = {
            "total": len(candidate_rows),
            "scheduled": status_counts["scheduled"],
            "shortlisted": status_counts["shortlisted"],
            "hired": status_counts["hired"] + status_counts["completed"],
            "rejected": status_counts["rejected"],
            "assessment_pending": status_counts["assessment_pending"],
            "assessment_completed": status_counts["assessment_completed"],
            "auto_screening_scheduled": status_counts["auto_screening_scheduled"],
            "cancelled": status_counts["cancelled"],
        }

        return JsonResponse({
            "Success": True,
            "Error": None,
            "Data": {
                "summary": summary,
                "candidates": candidate_rows,
                "role_breakdown": role_breakdown[:8],
                "recruiter_breakdown": recruiter_breakdown[:8],
                "upcoming": upcoming,
            }
        })
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "Data": {}})


@csrf_exempt
@login_required
def ai_talent_pool_match(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    role_id_raw = (payload.get('role_id') or request.POST.get('role_id') or '').__str__().strip()
    top_k_raw = (payload.get('top_k') or request.POST.get('top_k') or '20').__str__().strip()

    if not role_id_raw.isdigit():
        return JsonResponse({'Success': False, 'Error': 'A valid role_id is required.', 'Data': {}}, status=400)

    try:
        top_k = max(1, min(int(top_k_raw or '20'), 100))
    except (TypeError, ValueError):
        top_k = 20

    current_user = get_object_or_404(User, username=request.user.username)
    current_role = get_user_role(current_user)
    if current_role not in {'admin', 'recruiter', 'interviewer'}:
        return JsonResponse({'Success': False, 'Error': 'Hiring workspace access is required.', 'Data': {}}, status=403)

    admin_scope = get_admin_for_user(current_user)
    if not admin_scope:
        return JsonResponse({'Success': False, 'Error': 'No hiring workspace is mapped to the current user.', 'Data': {}}, status=403)

    role_qs = (
        Vacancies.objects
        .select_related('company', 'admin', 'admin__company_profile')
        .prefetch_related('recruiter')
        .filter(id=int(role_id_raw), admin=admin_scope)
    )
    if current_role == 'recruiter':
        role_qs = role_qs.filter(recruiter=current_user).distinct()
    role = role_qs.first()
    if not role:
        return JsonResponse({'Success': False, 'Error': 'Role not found or inaccessible.', 'Data': {}}, status=404)

    try:
        service = AiTalentPoolService()
        data = service.build_matches(
            role=role,
            top_k=top_k,
            accessible_interviews=get_accessible_interviews(current_user),
        )
        return JsonResponse({'Success': True, 'Error': None, 'Data': data})
    except RetrievalBackendUnavailable as exc:
        logger.exception('AI talent pool retrieval backend unavailable user=%s role=%s', current_user.id, role.id)
        return JsonResponse({'Success': False, 'Error': str(exc), 'Data': {}}, status=503)
    except Exception as exc:
        logger.exception('AI talent pool matching failed for user=%s role=%s', current_user.id, role.id)
        return JsonResponse({'Success': False, 'Error': f'Unable to build AI talent pool right now: {exc}', 'Data': {}}, status=500)


@csrf_exempt
@login_required
def ai_talent_pool_search(request):
    if request.method != 'POST':
        return JsonResponse({'Success': False, 'Error': 'Only POST is allowed.', 'Data': {}}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    query = str(payload.get('query') or '').strip()
    filters = payload.get('filters') or {}
    top_k_raw = str(payload.get('top_k') or '20').strip()
    if not query:
        return JsonResponse({'Success': False, 'Error': 'A search query is required.', 'Data': {}}, status=400)

    try:
        top_k = max(1, min(int(top_k_raw), 100))
    except (TypeError, ValueError):
        top_k = 20

    current_user = get_object_or_404(User, username=request.user.username)
    current_role = get_user_role(current_user)
    if current_role not in {'admin', 'recruiter', 'interviewer'}:
        return JsonResponse({'Success': False, 'Error': 'Hiring workspace access is required.', 'Data': {}}, status=403)

    admin_scope = get_admin_for_user(current_user)
    if not admin_scope:
        return JsonResponse({'Success': False, 'Error': 'No hiring workspace is mapped to the current user.', 'Data': {}}, status=403)

    try:
        service = AiTalentPoolService()
        data = service.build_search(
            query=query,
            filters=filters,
            top_k=top_k,
            accessible_interviews=get_accessible_interviews(current_user),
        )
        return JsonResponse({'Success': True, 'Error': None, 'Data': data})
    except RetrievalBackendUnavailable as exc:
        logger.exception('AI talent pool search retrieval backend unavailable user=%s', current_user.id)
        return JsonResponse({'Success': False, 'Error': str(exc), 'Data': {}}, status=503)
    except Exception as exc:
        logger.exception('AI talent pool search failed for user=%s query=%s', current_user.id, query)
        return JsonResponse({'Success': False, 'Error': f'Unable to search AI talent pool right now: {exc}', 'Data': {}}, status=500)


@login_required
def ai_talent_pool_audit(request, role_id: int):
    current_user = get_object_or_404(User, username=request.user.username)
    current_role = get_user_role(current_user)
    if current_role not in {'admin', 'recruiter', 'interviewer'}:
        return JsonResponse({'Success': False, 'Error': 'Hiring workspace access is required.', 'Data': {}}, status=403)

    admin_scope = get_admin_for_user(current_user)
    if not admin_scope:
        return JsonResponse({'Success': False, 'Error': 'No hiring workspace is mapped to the current user.', 'Data': {}}, status=403)

    top_k_raw = (request.GET.get('top_k') or '20').strip()
    export_format = (request.GET.get('format') or 'json').strip().lower()
    try:
        top_k = max(1, min(int(top_k_raw), 100))
    except (TypeError, ValueError):
        top_k = 20

    role_qs = (
        Vacancies.objects
        .select_related('company', 'admin', 'admin__company_profile')
        .prefetch_related('recruiter')
        .filter(id=role_id, admin=admin_scope)
    )
    if current_role == 'recruiter':
        role_qs = role_qs.filter(recruiter=current_user).distinct()
    role = role_qs.first()
    if not role:
        return JsonResponse({'Success': False, 'Error': 'Role not found or inaccessible.', 'Data': {}}, status=404)

    try:
        service = AiTalentPoolService()
        data = service.build_matches(
            role=role,
            top_k=top_k,
            accessible_interviews=get_accessible_interviews(current_user),
        )
    except Exception as exc:
        logger.exception('AI talent pool audit failed for user=%s role=%s', current_user.id, role.id)
        return JsonResponse({'Success': False, 'Error': f'Unable to build AI talent pool audit right now: {exc}', 'Data': {}}, status=500)

    audit_payload = {
        'role_summary': data.get('role_summary', {}),
        'retrieval_diagnostics': data.get('retrieval_diagnostics', {}),
        'scoring_config': data.get('scoring_config', {}),
        'results': data.get('results', [])[:top_k],
    }

    if export_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="ai_talent_pool_audit_role_{role.id}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'candidate_id',
            'name',
            'email',
            'title',
            'location',
            'ai_score',
            'ai_band',
            'vector_rank',
            'retrieval_distance',
            'retrieval_similarity',
            'retrieval_source',
            'pre_calibration_band',
            'post_calibration_band',
            'band_calibration_applied',
            'band_calibration_reason',
            'ranking_confidence',
            'role_profile_is_sparse',
            'role_family',
            'role_subfamily',
            'candidate_primary_family',
            'inferred_role_family',
            'used_title_inference',
            'confidence_adjustment_reason',
            'confidence_upgrade_reason',
            'confidence_downgrade_reason',
            'graph_boost_applied',
            'title_adjacency_reason',
            'semantic_similarity_raw',
            'semantic_similarity_calibrated',
            'semantic_floor_applied',
            'semantic_floor_reason',
            'semantic_similarity_score',
            'must_have_score',
            'preferred_score',
            'experience_fit_score',
            'title_fit_score',
            'location_score',
            'pipeline_signal_score',
            'required_skills_count',
            'matched_required_skills_count',
            'missing_required_skills_count',
            'exact_required_skills',
            'normalized_required_skills',
            'normalized_preferred_skills',
            'exact_candidate_skills',
            'normalized_candidate_skills',
            'selected_embedding_skills',
            'omitted_embedding_skills',
            'embedding_selection_source',
            'embedding_text_builder_version',
            'candidate_embedding_sections_used',
            'exact_skill_matches',
            'related_skill_matches_summary',
            'role_supporting_skill_inference',
            'role_adjacent_skill_inference',
            'role_embedding_text',
            'role_embedding_builder_version',
            'role_embedding_sections_used',
            'matched_required_skills',
            'missing_required_skills',
            'candidate_embedding_text',
            'candidate_embedding_text_token_count',
            'role_embedding_text_token_count',
            'candidate_embedding_present',
            'role_embedding_present',
            'candidate_embedding_dimension',
            'role_embedding_dimension',
            'raw_vector_distance',
            'indexed_similarity_from_pgvector',
            'pgvector_distance_metric',
            'distance_to_similarity_formula',
            'similarity_before_clamp',
            'similarity_after_clamp',
            'cosine_similarity_before_calibration',
            'recomputed_role_aware_cosine_similarity',
            'semantic_score_source',
            'semantic_score_clamp_reason',
            'pgvector_enabled',
            'pgvector_backend_available',
            'retrieval_fallback_reason',
            'matched_skills',
            'missing_skills',
            'explanations',
        ])
        for item in audit_payload['results']:
            writer.writerow([
                item.get('candidate_id', ''),
                item.get('name', ''),
                item.get('email', ''),
                item.get('title', ''),
                item.get('location', ''),
                item.get('ai_score', ''),
                item.get('ai_band', ''),
                item.get('vector_rank', ''),
                item.get('retrieval_distance', ''),
                item.get('retrieval_similarity', ''),
                item.get('retrieval_source', ''),
                item.get('pre_calibration_band', ''),
                item.get('post_calibration_band', ''),
                item.get('band_calibration_applied', ''),
                item.get('band_calibration_reason', ''),
                item.get('ranking_confidence', ''),
                item.get('role_profile_is_sparse', ''),
                item.get('role_family', ''),
                item.get('role_subfamily', ''),
                item.get('candidate_primary_family', ''),
                item.get('inferred_role_family', ''),
                item.get('used_title_inference', ''),
                item.get('confidence_adjustment_reason', ''),
                item.get('confidence_upgrade_reason', ''),
                item.get('confidence_downgrade_reason', ''),
                item.get('graph_boost_applied', ''),
                item.get('title_adjacency_reason', ''),
                item.get('semantic_similarity_raw', ''),
                item.get('semantic_similarity_calibrated', ''),
                item.get('semantic_floor_applied', ''),
                item.get('semantic_floor_reason', ''),
                item.get('semantic_similarity_score', ''),
                item.get('must_have_score', ''),
                item.get('preferred_score', ''),
                item.get('experience_fit_score', ''),
                item.get('title_fit_score', ''),
                item.get('location_score', ''),
                item.get('pipeline_signal_score', ''),
                item.get('required_skills_count', ''),
                item.get('matched_required_skills_count', ''),
                item.get('missing_required_skills_count', ''),
                ', '.join(item.get('exact_required_skills', []) or []),
                ', '.join(item.get('normalized_required_skills', []) or []),
                ', '.join(item.get('normalized_preferred_skills', []) or []),
                ', '.join(item.get('exact_candidate_skills', []) or []),
                ', '.join(item.get('normalized_candidate_skills', []) or []),
                ', '.join(item.get('selected_embedding_skills', []) or []),
                ', '.join(item.get('omitted_embedding_skills', []) or []),
                item.get('embedding_selection_source', ''),
                item.get('embedding_text_builder_version', ''),
                ' | '.join(item.get('candidate_embedding_sections_used', []) or []),
                ', '.join(item.get('exact_skill_matches', []) or []),
                ' | '.join(item.get('related_skill_matches_summary', []) or []),
                ', '.join(item.get('role_supporting_skill_inference', []) or []),
                ', '.join(item.get('role_adjacent_skill_inference', []) or []),
                item.get('role_embedding_text', ''),
                item.get('role_embedding_builder_version', ''),
                ' | '.join(item.get('role_embedding_sections_used', []) or []),
                ', '.join(item.get('matched_required_skills', []) or []),
                ', '.join(item.get('missing_required_skills', []) or []),
                item.get('candidate_embedding_text', ''),
                item.get('candidate_embedding_text_token_count', ''),
                item.get('role_embedding_text_token_count', ''),
                item.get('candidate_embedding_present', ''),
                item.get('role_embedding_present', ''),
                item.get('candidate_embedding_dimension', ''),
                item.get('role_embedding_dimension', ''),
                item.get('raw_vector_distance', ''),
                item.get('indexed_similarity_from_pgvector', ''),
                item.get('pgvector_distance_metric', ''),
                item.get('distance_to_similarity_formula', ''),
                item.get('similarity_before_clamp', ''),
                item.get('similarity_after_clamp', ''),
                item.get('cosine_similarity_before_calibration', ''),
                item.get('recomputed_role_aware_cosine_similarity', ''),
                item.get('semantic_score_source', ''),
                item.get('semantic_score_clamp_reason', ''),
                item.get('pgvector_enabled', ''),
                item.get('pgvector_backend_available', ''),
                item.get('retrieval_fallback_reason', ''),
                ', '.join(item.get('matched_skills', []) or []),
                ', '.join(item.get('missing_skills', []) or []),
                ' | '.join(item.get('explanations', []) or []),
            ])
        return response

    return JsonResponse({'Success': True, 'Error': None, 'Data': audit_payload})


@login_required
def activityTabData(request):
    try:
        admin = get_admin_for_user(request.user)
        now = timezone.now()
        tz = timezone.get_current_timezone()
        base_qs = get_accessible_interviews(request.user).order_by('-date')

        def normalize_recruiter_display(first_name, last_name, fallback='Not Assigned'):
            full_name = f"{(first_name or '').strip()} {(last_name or '').strip()}".strip().title()
            if not full_name:
                return fallback
            lowered = full_name.lower()
            if lowered in {'tbd', 'tbd tbd'}:
                return 'Not Assigned'
            return full_name

        def normalize_role_display(role_name):
            value = (role_name or '').strip()
            if value.lower() == 'salesfore developer':
                return 'Salesforce Developer'
            return value or 'Unassigned'

        recruiter_options = []
        recruiter_seen = set()
        for row in (
            base_qs
            .exclude(recruiter__isnull=True)
            .values('recruiter', 'recruiter__first_name', 'recruiter__last_name')
            .distinct()
            .order_by('recruiter__first_name', 'recruiter__last_name')
        ):
            r_id = row.get('recruiter')
            if not r_id or r_id in recruiter_seen:
                continue
            recruiter_seen.add(r_id)
            recruiter_options.append({
                'id': r_id,
                'name': normalize_recruiter_display(
                    row.get('recruiter__first_name'),
                    row.get('recruiter__last_name'),
                ),
            })

        role_options = []
        role_seen = set()
        for row in (
            base_qs
            .exclude(role__isnull=True)
            .values('role', 'role__role')
            .distinct()
            .order_by('role__role')
        ):
            role_id = row.get('role')
            if not role_id or role_id in role_seen:
                continue
            role_seen.add(role_id)
            role_options.append({
                'id': role_id,
                'name': normalize_role_display(row.get('role__role')),
            })

        interviews = base_qs
        recruiter_filter = (request.GET.get('recruiter') or '').strip()
        role_filter = (request.GET.get('role') or '').strip()
        status_filter = normalize_interview_status((request.GET.get('status') or '').strip())
        start_date_str = (request.GET.get('start_date') or '').strip()
        end_date_str = (request.GET.get('end_date') or '').strip()
        parsed_start_date = None
        parsed_end_date = None

        if recruiter_filter and recruiter_filter != 'all' and recruiter_filter.isdigit():
            interviews = interviews.filter(recruiter_id=int(recruiter_filter))

        if role_filter and role_filter != 'all' and role_filter.isdigit():
            interviews = interviews.filter(role_id=int(role_filter))

        if status_filter and status_filter != 'all':
            if status_filter in ['hired_group', 'hired_or_completed']:
                interviews = interviews.filter(status__in=['hired', 'completed'])
            else:
                interviews = interviews.filter(status=status_filter)

        if start_date_str:
            parsed_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        if end_date_str:
            parsed_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
            parsed_start_date, parsed_end_date = parsed_end_date, parsed_start_date
            start_date_str, end_date_str = parsed_start_date.strftime('%Y-%m-%d'), parsed_end_date.strftime('%Y-%m-%d')

        if parsed_start_date:
            start_dt = timezone.make_aware(datetime.combine(parsed_start_date, time.min), timezone.get_current_timezone())
            interviews = interviews.filter(date__gte=start_dt)

        if parsed_end_date:
            end_dt = timezone.make_aware(datetime.combine(parsed_end_date, time.max), timezone.get_current_timezone())
            interviews = interviews.filter(date__lte=end_dt)
        else:
            end_dt = now

        if parsed_start_date:
            current_start_dt = timezone.make_aware(datetime.combine(parsed_start_date, time.min), tz)
        else:
            current_start_dt = now - timedelta(days=30)

        current_end_dt = end_dt
        if current_end_dt < current_start_dt:
            current_start_dt, current_end_dt = current_end_dt, current_start_dt

        period_days = max((current_end_dt.date() - current_start_dt.date()).days + 1, 1)
        prev_end_dt = current_start_dt - timedelta(seconds=1)
        prev_start_dt = prev_end_dt - timedelta(days=period_days - 1)

        interview_rows = list(
            interviews.values(
                'id',
                'candidate_id',
                'candidate__first_name',
                'candidate__last_name',
                'candidate__date_joined',
                'recruiter_id',
                'recruiter__first_name',
                'recruiter__last_name',
                'role_id',
                'role__role',
                'date',
                'status',
                'score',
            ).order_by('-date')
        )

        total_interviews = len(interview_rows)
        open_roles = Vacancies.objects.filter(admin=admin).exclude(status__in=['closed', 'canceled', 'hired']).count() if admin else 0
        last_30_boundary = now - timedelta(days=30)
        upcoming_heat_window_end = now + timedelta(days=7)
        assessment_stale_cutoff = now - timedelta(days=7)
        shortlisted_stale_cutoff = now - timedelta(days=10)

        total_status_counts = Counter()
        status_buckets = {
            'Scheduled': 0,
            'Assessment Pending': 0,
            'Shortlisted': 0,
            'Hired': 0,
            'Rejected': 0,
            'Cancelled': 0,
            'Auto Screening': 0,
        }
        active_recruiter_ids = set()
        role_stats_map = {}
        recruiter_stats_map = {}
        quality_by_role_map = {}
        monthly_counts = Counter()
        monthly_hired_counts = Counter()
        scored_count = 0
        evaluated_count = 0
        score_bands = {
            'Excellent (8-10)': 0,
            'Good (6-7.9)': 0,
            'Average (4-5.9)': 0,
            'Low (<4)': 0,
        }
        role_pipeline_counts = Counter()
        role_filled_counts = Counter()
        recent_activity = []
        upcoming_candidates = []
        candidate_entries = defaultdict(list)
        first_touch_by_candidate = {}
        upcoming_count = 0
        hired_count = 0
        last_30_days = 0
        overdue_scheduled = 0
        stale_assessment = 0
        stale_shortlisted = 0
        unassigned_recruiter = 0

        def increment_stage_bucket(stage_counts, normalized_status):
            stage_counts['Applied'] += 1
            if normalized_status in ['assessment_pending', 'auto_screening_scheduled']:
                stage_counts['Assessment Pending'] += 1
            elif normalized_status == 'scheduled':
                stage_counts['Scheduled'] += 1
            elif normalized_status == 'shortlisted':
                stage_counts['Shortlisted'] += 1
            elif normalized_status in ['hired', 'completed']:
                stage_counts['Hired'] += 1
            elif normalized_status == 'rejected':
                stage_counts['Rejected'] += 1
            elif normalized_status == 'cancelled':
                stage_counts['Cancelled'] += 1

        current_stage_counts = {
            'Applied': 0,
            'Assessment Pending': 0,
            'Scheduled': 0,
            'Shortlisted': 0,
            'Hired': 0,
            'Rejected': 0,
            'Cancelled': 0,
        }

        today_local = timezone.localtime(now, tz).date()
        daily_totals = {}
        daily_hired = {}
        daily_scheduled = {}
        for idx in range(13, -1, -1):
            day = today_local - timedelta(days=idx)
            day_key = day.strftime('%Y-%m-%d')
            daily_totals[day_key] = 0
            daily_hired[day_key] = 0
            daily_scheduled[day_key] = 0

        heat_days = [today_local + timedelta(days=i) for i in range(7)]
        slot_order = ['Night', 'Morning', 'Afternoon', 'Evening']
        heat_rows = {
            day.strftime('%Y-%m-%d'): {slot: 0 for slot in slot_order}
            for day in heat_days
        }
        max_cell = 0

        for row in interview_rows:
            row_date = row.get('date')
            normalized_status = normalize_interview_status(row.get('status'))
            total_status_counts[normalized_status] += 1

            if normalized_status == 'scheduled':
                status_buckets['Scheduled'] += 1
            elif normalized_status == 'assessment_pending':
                status_buckets['Assessment Pending'] += 1
            elif normalized_status == 'shortlisted':
                status_buckets['Shortlisted'] += 1
            elif normalized_status in ['hired', 'completed']:
                status_buckets['Hired'] += 1
            elif normalized_status == 'rejected':
                status_buckets['Rejected'] += 1
            elif normalized_status == 'cancelled':
                status_buckets['Cancelled'] += 1
            elif normalized_status == 'auto_screening_scheduled':
                status_buckets['Auto Screening'] += 1

            recruiter_id = row.get('recruiter_id')
            recruiter_name = normalize_recruiter_display(
                row.get('recruiter__first_name'),
                row.get('recruiter__last_name'),
            )
            role_id = row.get('role_id')
            role_name = normalize_role_display(row.get('role__role'))
            candidate_name = f"{(row.get('candidate__first_name') or '').strip()} {(row.get('candidate__last_name') or '').strip()}".strip().title()

            if recruiter_id:
                active_recruiter_ids.add(recruiter_id)
                stats = recruiter_stats_map.setdefault(recruiter_id, {
                    'recruiter_id': recruiter_id,
                    'name': recruiter_name,
                    'count': 0,
                })
                stats['count'] += 1
            else:
                unassigned_recruiter += 1

            if role_id:
                role_stats = role_stats_map.setdefault(role_id, {
                    'role_id': role_id,
                    'role': role_name,
                    'count': 0,
                    'hired': 0,
                })
                role_stats['count'] += 1
                if normalized_status in ['hired', 'completed']:
                    role_stats['hired'] += 1

            if role_id:
                quality_stats = quality_by_role_map.setdefault(role_id, {
                    'role': role_name,
                    'total': 0,
                    'positive': 0,
                })
                quality_stats['total'] += 1
                if normalized_status in ['hired', 'completed', 'shortlisted']:
                    quality_stats['positive'] += 1

            if normalized_status in ['scheduled', 'assessment_pending', 'auto_screening_scheduled', 'shortlisted'] and role_id:
                role_pipeline_counts[role_id] += 1
            if normalized_status in ['hired', 'completed'] and role_id:
                role_filled_counts[role_id] += 1

            if row_date:
                local_dt = timezone.localtime(row_date, tz)
                month_key = (local_dt.year, local_dt.month)
                monthly_counts[month_key] += 1
                if normalized_status in ['hired', 'completed']:
                    monthly_hired_counts[month_key] += 1

                day_key = local_dt.date().strftime('%Y-%m-%d')
                if day_key in daily_totals:
                    daily_totals[day_key] += 1
                    if normalized_status in ['hired', 'completed']:
                        daily_hired[day_key] += 1
                    if normalized_status == 'scheduled':
                        daily_scheduled[day_key] += 1

                if current_start_dt <= row_date <= current_end_dt:
                    increment_stage_bucket(current_stage_counts, normalized_status)

                if normalized_status == 'scheduled' and now <= row_date <= upcoming_heat_window_end:
                    heat_day_key = local_dt.date().strftime('%Y-%m-%d')
                    if heat_day_key in heat_rows:
                        if local_dt.hour < 6:
                            slot = 'Night'
                        elif local_dt.hour < 12:
                            slot = 'Morning'
                        elif local_dt.hour < 18:
                            slot = 'Afternoon'
                        else:
                            slot = 'Evening'
                        heat_rows[heat_day_key][slot] += 1
                        max_cell = max(max_cell, heat_rows[heat_day_key][slot])

                if row_date >= last_30_boundary:
                    last_30_days += 1

            if normalized_status == 'scheduled' and row_date and row_date >= now:
                upcoming_count += 1
                upcoming_candidates.append({
                    'id': row.get('id'),
                    'candidate': candidate_name,
                    'role': role_name,
                    'date': row_date,
                })
            if normalized_status in ['hired', 'completed']:
                hired_count += 1
            if normalized_status == 'scheduled' and row_date and row_date < now:
                overdue_scheduled += 1
            if normalized_status == 'assessment_pending' and row_date and row_date < assessment_stale_cutoff:
                stale_assessment += 1
            if normalized_status == 'shortlisted' and row_date and row_date < shortlisted_stale_cutoff:
                stale_shortlisted += 1
            if normalized_status in ['completed', 'hired', 'shortlisted', 'rejected', 'cancelled']:
                evaluated_count += 1

            score = row.get('score')
            if score is not None:
                scored_count += 1
                score_val = float(score)
                if score_val >= 8:
                    score_bands['Excellent (8-10)'] += 1
                elif score_val >= 6:
                    score_bands['Good (6-7.9)'] += 1
                elif score_val >= 4:
                    score_bands['Average (4-5.9)'] += 1
                else:
                    score_bands['Low (<4)'] += 1

            candidate_id = row.get('candidate_id')
            if candidate_id:
                entry = {
                    'date': row_date,
                    'status': normalized_status,
                    'candidate_name': candidate_name,
                    'role_name': role_name,
                    'role_id': role_id,
                }
                candidate_entries[candidate_id].append(entry)

                current_first_touch = first_touch_by_candidate.get(candidate_id)
                candidate_joined_at = row.get('candidate__date_joined')
                if candidate_joined_at and row_date and (
                    current_first_touch is None or row_date < current_first_touch['date']
                ):
                    first_touch_by_candidate[candidate_id] = {
                        'date': row_date,
                        'candidate_joined_at': candidate_joined_at,
                        'recruiter_id': recruiter_id,
                        'recruiter_name': recruiter_name,
                    }

            if len(recent_activity) < 14:
                recent_activity.append({
                    'id': row.get('id'),
                    'title': f"{candidate_name} - {normalized_status.replace('_', ' ').title()}",
                    'meta': f"{role_name} • {recruiter_name}",
                    'date': row_date.isoformat() if row_date else '',
                })

        # Trend range (dynamic if date filter applied)
        month_points = []
        trend_title = 'Interview Trend (Last 6 Months)'
        if parsed_start_date or parsed_end_date:
            range_start = parsed_start_date if parsed_start_date else (now - timedelta(days=150)).date()
            range_end = parsed_end_date if parsed_end_date else now.date()
            if range_start > range_end:
                range_start, range_end = range_end, range_start

            y, m = range_start.year, range_start.month
            end_y, end_m = range_end.year, range_end.month
            while (y < end_y) or (y == end_y and m <= end_m):
                month_points.append((y, m))
                m += 1
                if m == 13:
                    m = 1
                    y += 1

            if len(month_points) > 12:
                month_points = month_points[-12:]
        else:
            latest_hire_dt = interviews.filter(status__in=['hired', 'completed']).aggregate(latest=Max('date')).get('latest')
            latest_activity_dt = interviews.aggregate(latest=Max('date')).get('latest')
            trend_anchor = latest_hire_dt or latest_activity_dt or now
            trend_anchor = timezone.localtime(trend_anchor, tz)
            cursor_year = trend_anchor.year
            cursor_month = trend_anchor.month
            for _ in range(6):
                month_points.append((cursor_year, cursor_month))
                cursor_month -= 1
                if cursor_month == 0:
                    cursor_month = 12
                    cursor_year -= 1
            month_points.reverse()

        month_labels = []
        trend_counts = []
        trend_hired = []
        for y, m in month_points:
            label = timezone.datetime(y, m, 1).strftime('%b %Y')
            month_labels.append(label)
            trend_counts.append(monthly_counts.get((y, m), 0))
            trend_hired.append(monthly_hired_counts.get((y, m), 0))

        if month_labels:
            trend_title = f"Interview Trend ({month_labels[0]} - {month_labels[-1]})" if (parsed_start_date or parsed_end_date) else trend_title

        # Phase 1: SLA alerts
        sla_alerts = []
        if overdue_scheduled:
            sla_alerts.append({
                'type': 'overdue_interviews',
                'title': 'Overdue scheduled interviews',
                'count': overdue_scheduled,
                'severity': 'high',
                'description': 'Scheduled time has passed without closure.',
            })
        if stale_assessment:
            sla_alerts.append({
                'type': 'stale_assessment',
                'title': 'Assessment pending beyond 7 days',
                'count': stale_assessment,
                'severity': 'medium',
                'description': 'Candidates waiting too long in assessment stage.',
            })
        if stale_shortlisted:
            sla_alerts.append({
                'type': 'stale_shortlisted',
                'title': 'Shortlisted not progressed beyond 10 days',
                'count': stale_shortlisted,
                'severity': 'medium',
                'description': 'Follow-up needed to avoid drop-offs.',
            })
        if unassigned_recruiter:
            sla_alerts.append({
                'type': 'unassigned_recruiter',
                'title': 'Interviews without assigned recruiter',
                'count': unassigned_recruiter,
                'severity': 'low',
                'description': 'Assign recruiter ownership for faster movement.',
            })

        # Phase 1: Stage movement (current range vs previous range)
        previous_range_qs = base_qs.filter(date__gte=prev_start_dt, date__lte=prev_end_dt)
        if recruiter_filter and recruiter_filter != 'all' and recruiter_filter.isdigit():
            previous_range_qs = previous_range_qs.filter(recruiter_id=int(recruiter_filter))
        if role_filter and role_filter != 'all' and role_filter.isdigit():
            previous_range_qs = previous_range_qs.filter(role_id=int(role_filter))

        def build_stage_counts(statuses):
            stage_counts = {
                'Applied': 0,
                'Assessment Pending': 0,
                'Scheduled': 0,
                'Shortlisted': 0,
                'Hired': 0,
                'Rejected': 0,
                'Cancelled': 0,
            }
            for status_value in statuses:
                increment_stage_bucket(stage_counts, normalize_interview_status(status_value))
            return stage_counts

        previous_stage_counts = build_stage_counts(previous_range_qs.values_list('status', flat=True))
        stage_order = ['Applied', 'Assessment Pending', 'Scheduled', 'Shortlisted', 'Hired', 'Rejected', 'Cancelled']
        stage_movement = []
        for stage in stage_order:
            current_count = current_stage_counts.get(stage, 0)
            prev_count = previous_stage_counts.get(stage, 0)
            stage_movement.append({
                'stage': stage,
                'current': current_count,
                'previous': prev_count,
                'delta': current_count - prev_count,
            })

        # Phase 1: Drop-off reasons (status-derived)
        dropoff_reasons = [
            {'reason': 'Rejected', 'count': total_status_counts.get('rejected', 0)},
            {'reason': 'Cancelled', 'count': total_status_counts.get('cancelled', 0)},
            {'reason': 'No Show / Missed', 'count': overdue_scheduled},
            {'reason': 'Screening Timeout', 'count': stale_assessment},
        ]
        dropoff_reasons = [x for x in dropoff_reasons if x['count'] > 0]
        dropoff_reasons.sort(key=lambda x: x['count'], reverse=True)

        # Phase 1: Insights
        insights = []
        if total_interviews == 0:
            insights.append('No activity in selected filters. Try widening the date range.')
        else:
            if hired_count == 0:
                insights.append('No hires recorded in this range yet.')
            else:
                insights.append(f'Hire rate is {round((hired_count / total_interviews) * 100)}% in selected range.')

            top_status = max(status_buckets.items(), key=lambda x: x[1]) if status_buckets else None
            if top_status and top_status[1] > 0:
                insights.append(f'Most common stage is {top_status[0]} ({top_status[1]} candidates).')
            if overdue_scheduled > 0:
                insights.append(f'{overdue_scheduled} scheduled interviews are overdue and need action.')
            if dropoff_reasons:
                top_drop = dropoff_reasons[0]
                insights.append(f'Top drop-off reason: {top_drop["reason"]} ({top_drop["count"]}).')

        # Phase 2: Recruiter response-time proxy.
        # Measure first recruiter touch as candidate creation -> first interview date, and
        # ignore legacy/outlier lags beyond 30 days because they usually represent dormant
        # inventory or migrated records rather than operational response time.
        lead_time_hours = []
        recruiter_lead = defaultdict(list)
        response_time_outlier_limit_hours = 24 * 30
        for item in first_touch_by_candidate.values():
            if not item['date'] or not item['candidate_joined_at']:
                continue
            diff_hours = (item['date'] - item['candidate_joined_at']).total_seconds() / 3600
            if diff_hours < 0 or diff_hours > response_time_outlier_limit_hours:
                continue
            lead_time_hours.append(diff_hours)
            recruiter_lead[item['recruiter_name']].append(diff_hours)

        response_time = {
            'avg_hours': round(sum(lead_time_hours) / len(lead_time_hours), 1) if lead_time_hours else 0,
            'median_hours': round(median(lead_time_hours), 1) if lead_time_hours else 0,
            'samples': len(lead_time_hours),
            'by_recruiter': []
        }
        for recruiter_name, values in recruiter_lead.items():
            response_time['by_recruiter'].append({
                'name': recruiter_name,
                'avg_hours': round(sum(values) / len(values), 1),
                'count': len(values),
            })
        response_time['by_recruiter'].sort(key=lambda x: x['avg_hours'])
        response_time['by_recruiter'] = response_time['by_recruiter'][:8]

        # Phase 2: Interview outcome quality
        quality_by_role = []
        for row in sorted(quality_by_role_map.values(), key=lambda x: x['total'], reverse=True)[:8]:
            total = row.get('total') or 0
            positive = row.get('positive') or 0
            quality_by_role.append({
                'role': row.get('role') or 'Unassigned',
                'total': total,
                'positive': positive,
                'pass_rate': round((positive / total) * 100) if total else 0,
            })

        outcome_quality = {
            'evaluated': evaluated_count,
            'hired': hired_count,
            'shortlisted': total_status_counts.get('shortlisted', 0),
            'rejected': total_status_counts.get('rejected', 0),
            'score_bands': score_bands,
            'scored_count': scored_count,
            'quality_by_role': quality_by_role,
        }

        # Phase 2: Daily/weekly productivity
        daily_points = []
        for idx in range(13, -1, -1):
            day = today_local - timedelta(days=idx)
            day_key = day.strftime('%Y-%m-%d')
            daily_points.append({
                'key': day_key,
                'label': day.strftime('%d %b'),
                'total': daily_totals.get(day_key, 0),
                'hired': daily_hired.get(day_key, 0),
                'scheduled': daily_scheduled.get(day_key, 0),
            })

        current_week_start = today_local - timedelta(days=today_local.weekday())
        prev_week_end = current_week_start - timedelta(days=1)
        prev_week_start = prev_week_end - timedelta(days=6)
        current_week_total = 0
        previous_week_total = 0
        current_week_hired = 0
        for point in daily_points:
            point_date = datetime.strptime(point['key'], '%Y-%m-%d').date()
            if current_week_start <= point_date <= today_local:
                current_week_total += point['total']
                current_week_hired += point['hired']
            elif prev_week_start <= point_date <= prev_week_end:
                previous_week_total += point['total']

        productivity = {
            'daily': daily_points,
            'current_week_total': current_week_total,
            'previous_week_total': previous_week_total,
            'current_week_hired': current_week_hired,
        }

        # Phase 2: Upcoming load heat (next 7 days x 4 slots)
        upcoming_load_heat = {
            'slots': slot_order,
            'days': [
                {
                    'key': day.strftime('%Y-%m-%d'),
                    'label': day.strftime('%a %d'),
                    'cells': heat_rows[day.strftime('%Y-%m-%d')]
                }
                for day in heat_days
            ],
            'max_cell': max_cell,
            'total_scheduled': sum(
                count
                for cells in heat_rows.values()
                for count in cells.values()
            ),
        }

        # Phase 3: Open role risk score
        open_vacancies_qs = Vacancies.objects.filter(admin=admin).exclude(status__in=['closed', 'canceled', 'hired']) if admin else Vacancies.objects.none()
        if role_filter and role_filter != 'all' and role_filter.isdigit():
            open_vacancies_qs = open_vacancies_qs.filter(id=int(role_filter))
        if recruiter_filter and recruiter_filter != 'all' and recruiter_filter.isdigit():
            open_vacancies_qs = open_vacancies_qs.filter(recruiter__id=int(recruiter_filter))
        open_vacancies_qs = open_vacancies_qs.distinct()

        role_risk_score = []
        total_target = 0
        total_filled = 0
        for vacancy in open_vacancies_qs:
            try:
                target_positions = int(vacancy.position)
            except (TypeError, ValueError):
                target_positions = 0

            filled = role_filled_counts.get(vacancy.id, 0)
            active_pipeline_count = role_pipeline_counts.get(vacancy.id, 0)
            remaining = max(target_positions - filled, 0)
            progress_pct = round((filled / target_positions) * 100) if target_positions > 0 else 0
            age_days = max((timezone.localtime(now, tz).date() - timezone.localtime(vacancy.date, tz).date()).days, 0) if vacancy.date else 0
            capacity_gap_pct = round((remaining / target_positions) * 100) if target_positions > 0 else 0
            stale_factor = min(age_days, 60) / 60
            risk_score = min(100, round((capacity_gap_pct * 0.7) + (stale_factor * 30)))

            if risk_score >= 70:
                severity = 'high'
            elif risk_score >= 40:
                severity = 'medium'
            else:
                severity = 'low'

            role_risk_score.append({
                'role_id': vacancy.id,
                'role': vacancy.role,
                'target': target_positions,
                'filled': filled,
                'remaining': remaining,
                'pipeline': active_pipeline_count,
                'progress_pct': progress_pct,
                'risk_score': risk_score,
                'severity': severity,
                'age_days': age_days,
            })
            total_target += max(target_positions, 0)
            total_filled += filled

        role_risk_score.sort(key=lambda x: (-x['risk_score'], -x['remaining']))
        role_risk_score = role_risk_score[:8]

        # Phase 3: Target vs Actual
        month_labels_target = []
        target_actual_hires = []
        target_actual_target = []
        cursor = timezone.localtime(now, tz)
        month_points_target = []
        year = cursor.year
        month = cursor.month
        for _ in range(6):
            month_points_target.append((year, month))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        month_points_target.reverse()

        monthly_target = max(total_target, 0)
        for y, m in month_points_target:
            month_labels_target.append(timezone.datetime(y, m, 1).strftime('%b %Y'))
            hires_for_month = monthly_hired_counts.get((y, m), 0)
            target_actual_hires.append(hires_for_month)
            target_actual_target.append(monthly_target)

        target_vs_actual = {
            'target_total': total_target,
            'actual_total': total_filled,
            'gap': max(total_target - total_filled, 0),
            'progress_pct': round((total_filled / total_target) * 100) if total_target else 0,
            'labels': month_labels_target,
            'keys': [f"{y:04d}-{m:02d}" for y, m in month_points_target],
            'target_series': target_actual_target,
            'actual_series': target_actual_hires,
        }

        # Phase 3: Re-opened / recycled candidates
        recycled_candidates = []
        reopened_count = 0
        recycled_total_count = 0

        closed_statuses = {'rejected', 'cancelled'}
        active_statuses = {'assessment_pending', 'auto_screening_scheduled', 'scheduled', 'shortlisted', 'hired', 'completed'}

        for _, entries in candidate_entries.items():
            if not entries:
                continue
            entries.sort(key=lambda item: item['date'] or now)
            candidate_name = entries[0]['candidate_name']
            latest = entries[-1]
            normalized_statuses = [entry['status'] for entry in entries]
            seen_closed = False
            is_reopened = False
            for status in normalized_statuses:
                if status in closed_statuses:
                    seen_closed = True
                elif seen_closed and status in active_statuses:
                    is_reopened = True
                    break

            if is_reopened:
                reopened_count += 1

            if len(entries) > 1:
                recycled_total_count += 1
                role_names = sorted({entry['role_name'] for entry in entries})
                recycled_candidates.append({
                    'candidate': candidate_name,
                    'interviews': len(entries),
                    'roles': role_names[:3],
                    'primary_role_id': latest['role_id'] if latest['role_id'] else None,
                    'latest_status': latest['status'].replace('_', ' ').title(),
                    'reopened': is_reopened,
                })

        recycled_candidates.sort(key=lambda x: (-x['interviews'], x['candidate']))
        recycled_candidates = recycled_candidates[:8]
        recycled_summary = {
            'total_recycled': recycled_total_count,
            'reopened': reopened_count,
            'list': recycled_candidates,
        }

        export_meta = {
            'generated_at': now.isoformat(),
            'filters': {
                'recruiter': recruiter_filter or 'all',
                'role': role_filter or 'all',
                'start_date': start_date_str,
                'end_date': end_date_str,
            }
        }

        recruiter_breakdown = sorted(
            recruiter_stats_map.values(),
            key=lambda item: item['count'],
            reverse=True,
        )[:8]

        role_breakdown = sorted(
            role_stats_map.values(),
            key=lambda item: item['count'],
            reverse=True,
        )[:8]

        upcoming_list = [
            {
                'id': item['id'],
                'candidate': item['candidate'],
                'role': item['role'],
                'date': item['date'].isoformat() if item['date'] else '',
            }
            for item in sorted(upcoming_candidates, key=lambda row: row['date'])[:8]
        ]

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'summary': {
                    'total_interviews': total_interviews,
                    'upcoming': upcoming_count,
                    'hired': hired_count,
                    'active_recruiters': len(active_recruiter_ids),
                    'open_roles': open_roles,
                    'last_30_days': last_30_days,
                    'hire_rate': round((hired_count / total_interviews) * 100) if total_interviews else 0,
                },
                'trend': {
                    'title': trend_title,
                    'labels': month_labels,
                    'interviews': trend_counts,
                    'hired': trend_hired,
                },
                'status_split': status_buckets,
                'recruiter_breakdown': recruiter_breakdown,
                'role_breakdown': role_breakdown,
                'recent_activity': recent_activity,
                'upcoming_list': upcoming_list,
                'sla_alerts': sla_alerts,
                'stage_movement': stage_movement,
                'dropoff_reasons': dropoff_reasons,
                'insights': insights,
                'response_time': response_time,
                'outcome_quality': outcome_quality,
                'productivity': productivity,
                'upcoming_load_heat': upcoming_load_heat,
                'role_risk_score': role_risk_score,
                'target_vs_actual': target_vs_actual,
                'recycled_summary': recycled_summary,
                'export_meta': export_meta,
                'filter_options': {
                    'recruiters': recruiter_options,
                    'roles': role_options,
                    'statuses': [
                        {'value': 'all', 'label': 'All Statuses'},
                        {'value': 'assessment_pending', 'label': 'Assessment Pending'},
                        {'value': 'auto_screening_scheduled', 'label': 'Auto Screening Scheduled'},
                        {'value': 'scheduled', 'label': 'Scheduled'},
                        {'value': 'shortlisted', 'label': 'Shortlisted'},
                        {'value': 'hired_group', 'label': 'Hired (incl Completed)'},
                        {'value': 'rejected', 'label': 'Rejected'},
                        {'value': 'cancelled', 'label': 'Cancelled'},
                    ],
                },
                'applied_filters': {
                    'recruiter': recruiter_filter or 'all',
                    'role': role_filter or 'all',
                    'status': status_filter or 'all',
                    'start_date': start_date_str,
                    'end_date': end_date_str,
                }
            }
        })
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': {}})


@login_required
def analyticsTabData(request):
    try:
        admin = get_admin_for_user(request.user)
        now = timezone.now()
        tz = timezone.get_current_timezone()
        include_debug = request.GET.get('debug') == '1'
        def ensure_aware(value):
            if not value:
                return None
            if timezone.is_naive(value):
                return timezone.make_aware(value, tz)
            return timezone.localtime(value, tz)

        def iso_or_empty(value):
            return value.isoformat() if value else ''

        base_scope = get_accessible_interviews(request.user).order_by('-date')

        recruiter_options = [
            {
                'id': row['recruiter'],
                'name': f"{(row.get('recruiter__first_name') or '').strip()} {(row.get('recruiter__last_name') or '').strip()}".strip().title() or 'Unassigned',
            }
            for row in (
                base_scope
                .exclude(recruiter__isnull=True)
                .values('recruiter', 'recruiter__first_name', 'recruiter__last_name')
                .order_by('recruiter__first_name', 'recruiter__last_name')
                .distinct()
            )
            if row.get('recruiter')
        ]

        role_options = [
            {
                'id': row['role'],
                'name': row.get('role__role') or 'Unassigned',
            }
            for row in (
                base_scope
                .exclude(role__isnull=True)
                .values('role', 'role__role')
                .order_by('role__role')
                .distinct()
            )
            if row.get('role')
        ]

        recruiter_filter = (request.GET.get('recruiter') or '').strip()
        role_filter = (request.GET.get('role') or '').strip()
        start_date_str = (request.GET.get('start_date') or '').strip()
        end_date_str = (request.GET.get('end_date') or '').strip()
        parsed_start_date = None
        parsed_end_date = None

        if recruiter_filter and recruiter_filter != 'all' and recruiter_filter.isdigit():
            base_scope = base_scope.filter(recruiter_id=int(recruiter_filter))
        if role_filter and role_filter != 'all' and role_filter.isdigit():
            base_scope = base_scope.filter(role_id=int(role_filter))

        if start_date_str:
            parsed_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        if end_date_str:
            parsed_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
            parsed_start_date, parsed_end_date = parsed_end_date, parsed_start_date

        start_dt = ensure_aware(datetime.combine(parsed_start_date, time.min)) if parsed_start_date else None
        end_dt = ensure_aware(datetime.combine(parsed_end_date, time.max)) if parsed_end_date else None

        canonical_hire_annotation = Case(
            When(hired_at__isnull=False, then=F('hired_at')),
            When(status__in=['hired', 'completed'], then=F('date')),
            default=Value(None),
            output_field=DateTimeField(),
        )
        event_timestamp_annotation = Case(
            When(status__in=['hired', 'completed'], then=canonical_hire_annotation),
            default=F('date'),
            output_field=DateTimeField(),
        )

        base_scope = (
            base_scope
            .annotate(
                canonical_hire_at=canonical_hire_annotation,
                analytics_event_at=event_timestamp_annotation,
            )
            .distinct()
        )

        filtered_interviews = base_scope
        if start_dt:
            filtered_interviews = filtered_interviews.filter(analytics_event_at__gte=start_dt)
        if end_dt:
            filtered_interviews = filtered_interviews.filter(analytics_event_at__lte=end_dt)
        filtered_interviews = filtered_interviews.distinct()

        scoped_interviews = filtered_interviews

        hire_rows = list(
            scoped_interviews
            .filter(status__in=['hired', 'completed'])
            .exclude(canonical_hire_at__isnull=True)
            .values('id', 'candidate_id', 'role_id', 'recruiter_id', 'canonical_hire_at')
        )
        hire_ids = {row['id'] for row in hire_rows}

        status_counts = {
            row['status']: row['count']
            for row in scoped_interviews.values('status').annotate(count=Count('id', distinct=True))
        }
        total_interviews = sum(status_counts.values())
        hired_count = len(hire_rows)

        open_roles_qs = Vacancies.objects.filter(admin=admin).exclude(status__in=['closed', 'canceled', 'hired']) if admin else Vacancies.objects.none()
        if recruiter_filter and recruiter_filter != 'all' and recruiter_filter.isdigit():
            open_roles_qs = open_roles_qs.filter(recruiter__id=int(recruiter_filter))
        if role_filter and role_filter != 'all' and role_filter.isdigit():
            open_roles_qs = open_roles_qs.filter(id=int(role_filter))
        open_roles = list(open_roles_qs.distinct().values('id', 'role', 'position'))
        open_roles_count = len(open_roles)

        funnel_labels = ['Applied', 'Assessment Pending', 'Scheduled', 'Shortlisted', 'Hired']
        assessment_count = status_counts.get('assessment_pending', 0) + status_counts.get('auto_screening_scheduled', 0)
        scheduled_count = status_counts.get('scheduled', 0)
        shortlisted_count = status_counts.get('shortlisted', 0)
        funnel_values = [total_interviews, assessment_count, scheduled_count, shortlisted_count, hired_count]
        conversions = []
        for idx in range(len(funnel_labels) - 1):
            current = funnel_values[idx]
            nxt = funnel_values[idx + 1]
            conversions.append({
                'from': funnel_labels[idx],
                'to': funnel_labels[idx + 1],
                'rate': min(100, round((nxt / current) * 100)) if current else 0,
            })

        # Time-to-hire analytics
        # `Interview.date` is not a guaranteed hiring-cycle start timestamp.
        # Start priority is:
        # 1. earliest CandidateVacancyApplication.hiring_started_at
        # 2. earliest CandidateVacancyApplication.applied_at
        # 3. earliest CandidateVacancyApplication.created_at
        # 4. earliest non-terminal Interview.date for the same candidate-role pair
        # End timestamp is `hired_at`, with legacy fallback to the hired/completed
        # interview `date` only when `hired_at` is missing.
        # TTH therefore depends on application data quality.
        # Recommendation: CandidateVacancyApplication.hiring_started_at should be
        # the canonical TTH start field and should be indexed + reliably populated
        # for every candidate-role pair.
        month_points = []
        cursor_year = now.year
        cursor_month = now.month
        for _ in range(6):
            month_points.append((cursor_year, cursor_month))
            cursor_month -= 1
            if cursor_month == 0:
                cursor_month = 12
                cursor_year -= 1
        month_points.reverse()

        candidate_ids = {row['candidate_id'] for row in hire_rows if row.get('candidate_id')}
        vacancy_ids = {row['role_id'] for row in hire_rows if row.get('role_id')}

        application_hiring_started_by_pair = {}
        application_applied_by_pair = {}
        application_created_by_pair = {}
        if candidate_ids and vacancy_ids:
            hiring_started_rows = (
                CandidateVacancyApplication.objects
                .filter(candidate_id__in=candidate_ids, vacancy_id__in=vacancy_ids)
                .exclude(hiring_started_at__isnull=True)
                .values('candidate_id', 'vacancy_id')
                .annotate(first_hiring_started_at=Min('hiring_started_at'))
            )
            application_hiring_started_by_pair = {
                (row['candidate_id'], row['vacancy_id']): row['first_hiring_started_at']
                for row in hiring_started_rows
            }

            applied_rows = (
                CandidateVacancyApplication.objects
                .filter(candidate_id__in=candidate_ids, vacancy_id__in=vacancy_ids)
                .exclude(applied_at__isnull=True)
                .values('candidate_id', 'vacancy_id')
                .annotate(first_applied_at=Min('applied_at'))
            )
            application_applied_by_pair = {
                (row['candidate_id'], row['vacancy_id']): row['first_applied_at']
                for row in applied_rows
            }
            created_rows = (
                CandidateVacancyApplication.objects
                .filter(candidate_id__in=candidate_ids, vacancy_id__in=vacancy_ids)
                .exclude(created_at__isnull=True)
                .values('candidate_id', 'vacancy_id')
                .annotate(first_created_at=Min('created_at'))
            )
            application_created_by_pair = {
                (row['candidate_id'], row['vacancy_id']): row['first_created_at']
                for row in created_rows
            }

        interview_fallback_start_by_pair = {}
        if candidate_ids and vacancy_ids:
            fallback_rows = (
                scoped_interviews
                .filter(candidate_id__in=candidate_ids, role_id__in=vacancy_ids)
                .exclude(status__in=['hired', 'completed'])
                .exclude(date__isnull=True)
                .values('candidate_id', 'role_id')
                .annotate(first_seen_at=Min('date'))
            )
            interview_fallback_start_by_pair = {
                (row['candidate_id'], row['role_id']): row['first_seen_at']
                for row in fallback_rows
            }

        monthly_tth_values = {(y, m): [] for y, m in month_points}
        valid_tth_monthly_counts = {(y, m): 0 for y, m in month_points}
        all_hire_monthly_counts = {(y, m): 0 for y, m in month_points}
        tth_days: list[float] = []
        sample_hires = [] if include_debug else None
        suspicious_start_equals_hire_count = 0

        debug = {
            'total_hires_considered': len(hire_rows),
            'hires_with_valid_start': 0,
            'hires_with_valid_end': 0,
            'hires_used_for_tth': 0,
            'hires_skipped_missing_start': 0,
            'hires_skipped_missing_end': 0,
            'hires_skipped_negative_duration': 0,
            'suspicious_start_equals_hire_count': 0,
            'tth_sum_days': 0,
            'tth_min_days': 0,
            'tth_max_days': 0,
        }
        if include_debug:
            debug['sample_hires'] = sample_hires

        for row in hire_rows:
            hire_ts = ensure_aware(row.get('canonical_hire_at'))
            hiring_started_at = ensure_aware(application_hiring_started_by_pair.get((row['candidate_id'], row['role_id'])))
            applied_start = ensure_aware(application_applied_by_pair.get((row['candidate_id'], row['role_id'])))
            created_fallback = ensure_aware(application_created_by_pair.get((row['candidate_id'], row['role_id'])))
            interview_fallback = ensure_aware(interview_fallback_start_by_pair.get((row['candidate_id'], row['role_id'])))

            skip_reason = ''
            duration_days = None
            chosen_start = None

            if not hire_ts:
                debug['hires_skipped_missing_end'] += 1
                skip_reason = 'missing_hire_timestamp'
            else:
                debug['hires_with_valid_end'] += 1
                month_key = (hire_ts.year, hire_ts.month)
                if month_key in all_hire_monthly_counts:
                    all_hire_monthly_counts[month_key] += 1

                # Never use hired/completed interview rows as the default cycle
                # start; that would collapse start and end onto the same event.
                chosen_start = hiring_started_at or applied_start or created_fallback or interview_fallback
                if not chosen_start:
                    debug['hires_skipped_missing_start'] += 1
                    skip_reason = 'missing_start_timestamp'
                else:
                    debug['hires_with_valid_start'] += 1
                    if chosen_start == hire_ts:
                        suspicious_start_equals_hire_count += 1
                    duration_days = (hire_ts - chosen_start).total_seconds() / 86400
                    if duration_days < 0:
                        debug['hires_skipped_negative_duration'] += 1
                        skip_reason = 'negative_duration'
                        duration_days = None
                    else:
                        month_key = (hire_ts.year, hire_ts.month)
                        if month_key in monthly_tth_values:
                            monthly_tth_values[month_key].append(duration_days)
                            valid_tth_monthly_counts[month_key] += 1
                        tth_days.append(duration_days)
                        debug['hires_used_for_tth'] += 1

            if include_debug and sample_hires is not None and len(sample_hires) < 10:
                sample_hires.append({
                    'interview_id': row['id'],
                    'candidate_id': row['candidate_id'],
                    'role_id': row['role_id'],
                    'canonical_hire_at': iso_or_empty(hire_ts),
                    'hiring_started_at': iso_or_empty(hiring_started_at),
                    'application_start_at': iso_or_empty(applied_start),
                    'application_created_fallback_at': iso_or_empty(created_fallback),
                    'interview_fallback_start_at': iso_or_empty(interview_fallback),
                    'chosen_start_at': iso_or_empty(chosen_start),
                    'duration_days': round(duration_days, 3) if duration_days is not None else None,
                    'skip_reason': skip_reason,
                })

        debug['suspicious_start_equals_hire_count'] = suspicious_start_equals_hire_count
        if tth_days:
            debug['tth_sum_days'] = round(sum(tth_days), 3)
            debug['tth_min_days'] = round(min(tth_days), 3)
            debug['tth_max_days'] = round(max(tth_days), 3)

        tth_labels = []
        tth_monthly_avg = []
        tth_monthly_hires = []
        tth_monthly_total_hires = []
        for y, m in month_points:
            tth_labels.append(timezone.datetime(y, m, 1).strftime('%b %Y'))
            month_values = monthly_tth_values[(y, m)]
            tth_monthly_avg.append(round(sum(month_values) / len(month_values), 1) if month_values else 0)
            tth_monthly_hires.append(valid_tth_monthly_counts[(y, m)])
            tth_monthly_total_hires.append(all_hire_monthly_counts[(y, m)])

        source_effectiveness = []
        pipeline_source_labels = {
            CandidateVacancyApplication.PipelineSource.SELF_APPLIED: 'Self Applied',
            CandidateVacancyApplication.PipelineSource.DIRECT: 'Direct',
            CandidateVacancyApplication.PipelineSource.REFERRAL: 'Referral',
        }
        source_agg = defaultdict(lambda: {'total': 0, 'hired': 0})
        scoped_pairs = {
            (row['candidate_id'], row['role_id'])
            for row in scoped_interviews.values('candidate_id', 'role_id').distinct()
            if row.get('candidate_id') and row.get('role_id')
        }
        application_sources = {}
        if scoped_pairs:
            source_rows = (
                CandidateVacancyApplication.objects
                .filter(
                    candidate_id__in={pair[0] for pair in scoped_pairs},
                    vacancy_id__in={pair[1] for pair in scoped_pairs},
                )
                .values('candidate_id', 'vacancy_id', 'pipeline_source')
            )
            application_sources = {
                (row['candidate_id'], row['vacancy_id']): row['pipeline_source']
                for row in source_rows
            }

        for row in scoped_interviews.values('id', 'candidate_id', 'role_id').distinct().iterator():
            pipeline_source = application_sources.get((row.get('candidate_id'), row.get('role_id'))) or ''
            source_label = pipeline_source_labels.get(pipeline_source, 'Unclassified')
            source_agg[source_label]['total'] += 1
            if row['id'] in hire_ids:
                source_agg[source_label]['hired'] += 1
        for source, val in source_agg.items():
            total = val['total']
            hired = val['hired']
            source_effectiveness.append({
                'source': source,
                'total': total,
                'hired': hired,
                'conversion': round((hired / total) * 100) if total else 0,
            })
        source_effectiveness.sort(key=lambda x: x['total'], reverse=True)

        recruiter_totals = {
            row['recruiter_id']: row
            for row in (
                scoped_interviews
                .values('recruiter_id', 'recruiter__first_name', 'recruiter__last_name')
                .annotate(interviews=Count('id', distinct=True))
            )
        }
        recruiter_hires = {
            row['recruiter_id']: row['hired']
            for row in (
                scoped_interviews
                .filter(id__in=hire_ids)
                .values('recruiter_id')
                .annotate(hired=Count('id', distinct=True))
            )
        }
        recruiter_performance = []
        for recruiter_id, row in recruiter_totals.items():
            total = row['interviews']
            hired = recruiter_hires.get(recruiter_id, 0)
            name = f"{(row.get('recruiter__first_name') or '').strip()} {(row.get('recruiter__last_name') or '').strip()}".strip().title() or 'Unassigned'
            recruiter_performance.append({
                'name': name,
                'interviews': total,
                'hired': hired,
                'conversion': round((hired / total) * 100) if total else 0,
            })
        recruiter_performance.sort(key=lambda x: x['interviews'], reverse=True)

        role_pipeline_counts = {
            row['role_id']: row['pipeline']
            for row in (
                scoped_interviews
                .values('role_id')
                .annotate(
                    pipeline=Count(
                        'id',
                        filter=Q(status__in=['assessment_pending', 'auto_screening_scheduled', 'scheduled', 'shortlisted']),
                        distinct=True,
                    )
                )
            )
        }
        role_hire_counts = {
            row['role_id']: row['filled']
            for row in (
                scoped_interviews
                .filter(id__in=hire_ids)
                .values('role_id')
                .annotate(filled=Count('id', distinct=True))
            )
        }
        role_health = []
        for role in open_roles:
            try:
                target = int(role.get('position') or 0)
            except (TypeError, ValueError):
                target = 0
            role_id = role['id']
            filled = role_hire_counts.get(role_id, 0)
            pipeline = role_pipeline_counts.get(role_id, 0)
            coverage_gap = max(target - (filled + pipeline), 0)
            risk = round((coverage_gap / target) * 100) if target > 0 else 0
            role_health.append({
                'role': role.get('role') or 'Unassigned',
                'target': target,
                'filled': filled,
                'pipeline': pipeline,
                'risk': min(100, risk),
            })
        role_health.sort(key=lambda x: x['risk'], reverse=True)

        score_bands = {
            'Excellent (8-10)': 0,
            'Good (6-7.9)': 0,
            'Average (4-5.9)': 0,
            'Low (<4)': 0,
        }
        evaluated = 0
        for score in scoped_interviews.exclude(score__isnull=True).values_list('score', flat=True).distinct():
            score_val = float(score)
            evaluated += 1
            if score_val >= 8:
                score_bands['Excellent (8-10)'] += 1
            elif score_val >= 6:
                score_bands['Good (6-7.9)'] += 1
            elif score_val >= 4:
                score_bands['Average (4-5.9)'] += 1
            else:
                score_bands['Low (<4)'] += 1

        timing_metrics = scoped_interviews.aggregate(
            no_show=Count('id', filter=Q(status='scheduled', date__lt=now), distinct=True),
            screening_timeout=Count('id', filter=Q(status='assessment_pending', date__lt=now - timedelta(days=7)), distinct=True),
            scheduled_overdue=Count('id', filter=Q(status='scheduled', date__lt=now), distinct=True),
            assessment_timeout=Count('id', filter=Q(status='assessment_pending', date__lt=now - timedelta(days=7)), distinct=True),
            shortlisted_stale=Count('id', filter=Q(status='shortlisted', date__lt=now - timedelta(days=10)), distinct=True),
        )
        no_show = timing_metrics['no_show'] or 0
        screening_timeout = timing_metrics['screening_timeout'] or 0

        dropoff_analysis = {
            'total_dropoffs': status_counts.get('rejected', 0) + status_counts.get('cancelled', 0) + no_show + screening_timeout,
            'rejected': status_counts.get('rejected', 0),
            'cancelled': status_counts.get('cancelled', 0),
            'no_show': no_show,
            'screening_timeout': screening_timeout,
            'by_role': [],
        }
        role_drop = (
            scoped_interviews
            .values('role__role')
            .annotate(
                rejected=Count('id', filter=Q(status='rejected'), distinct=True),
                cancelled=Count('id', filter=Q(status='cancelled'), distinct=True),
                total=Count('id', distinct=True),
            )
            .order_by('-rejected', '-cancelled')[:8]
        )
        for row in role_drop:
            total = row.get('total') or 0
            drop_count = (row.get('rejected') or 0) + (row.get('cancelled') or 0)
            dropoff_analysis['by_role'].append({
                'role': row.get('role__role') or 'Unassigned',
                'dropoffs': drop_count,
                'drop_rate': round((drop_count / total) * 100) if total else 0,
            })

        # Offer-stage analytics prefer the explicit offer statuses when present.
        # Because Interview.status is a current-state field, hires/completions are
        # still treated as accepted offer outcomes for downstream compatibility.
        offer_stage_statuses = ['offer_made', 'offer_accepted', 'offer_declined', 'hired', 'completed']
        offer_stage_qs = scoped_interviews.filter(status__in=offer_stage_statuses)
        offers_made = offer_stage_qs.values('id').distinct().count()
        offers_accepted = scoped_interviews.filter(status__in=['offer_accepted', 'hired', 'completed']).values('id').distinct().count()
        offers_pending = scoped_interviews.filter(status='offer_made').values('id').distinct().count()
        if offers_made == 0:
            # Legacy fallback while old records are still using shortlist/hire as
            # the closest proxy for offer-stage movement.
            offers_made = max(
                scoped_interviews.filter(status__in=['shortlisted', 'hired', 'completed']).values('id').distinct().count(),
                hired_count,
            )
            offers_accepted = min(hired_count, offers_made)
            offers_pending = max(shortlisted_count, 0)
        offer_acceptance = {
            'offers_made': offers_made,
            'offers_accepted': offers_accepted,
            'offers_pending': offers_pending,
            'acceptance_rate': round((offers_accepted / offers_made) * 100) if offers_made else 0,
            'monthly_labels': tth_labels,
            'monthly_offers': [],
            'monthly_accepted': [],
        }
        offers_by_month = {
            (row['month'].year, row['month'].month): row['count']
            for row in (
                scoped_interviews
                .filter(status__in=offer_stage_statuses)
                .annotate(month=TruncMonth('analytics_event_at', tzinfo=tz))
                .values('month')
                .annotate(count=Count('id', distinct=True))
                .order_by('month')
            )
            if row.get('month')
        }
        for y, m in month_points:
            offer_acceptance['monthly_offers'].append(max(offers_by_month.get((y, m), 0), all_hire_monthly_counts[(y, m)] if offers_by_month else 0))
            offer_acceptance['monthly_accepted'].append(all_hire_monthly_counts[(y, m)])

        active_pipeline_total = assessment_count + scheduled_count + shortlisted_count
        scheduled_overdue = timing_metrics['scheduled_overdue'] or 0
        assessment_timeout = timing_metrics['assessment_timeout'] or 0
        shortlisted_stale = timing_metrics['shortlisted_stale'] or 0
        breached_count = min(scheduled_overdue + assessment_timeout + shortlisted_stale, active_pipeline_total)
        breach_candidates = []
        breach_seen = set()
        breach_specs = [
            ('Scheduled overdue', Q(status='scheduled', date__lt=now)),
            ('Assessment > 7 days', Q(status='assessment_pending', date__lt=now - timedelta(days=7))),
            ('Shortlisted > 10 days', Q(status='shortlisted', date__lt=now - timedelta(days=10))),
        ]
        for breach_label, breach_filter in breach_specs:
            rows = (
                scoped_interviews
                .filter(breach_filter)
                .select_related('candidate', 'role')
                .order_by('date')
            )
            for item in rows:
                if item.id in breach_seen:
                    continue
                breach_seen.add(item.id)
                candidate_name = f"{item.candidate.first_name} {item.candidate.last_name}".strip() or item.candidate.username or item.candidate.email or f"Candidate {item.candidate_id}"
                breach_candidates.append({
                    'candidate_name': candidate_name,
                    'role': item.role.role if item.role else '',
                    'breach_label': breach_label,
                })

        sla_compliance = {
            'active_pipeline': active_pipeline_total,
            'breached': breached_count,
            'compliance_rate': max(0, min(100, round(((active_pipeline_total - breached_count) / active_pipeline_total) * 100))) if active_pipeline_total else 100,
            'breakdown': [
                {'label': 'Scheduled overdue', 'count': scheduled_overdue},
                {'label': 'Assessment > 7 days', 'count': assessment_timeout},
                {'label': 'Shortlisted > 10 days', 'count': shortlisted_stale},
            ],
            'breach_candidates': breach_candidates[:8],
        }

        executive_insights = []
        if total_interviews == 0:
            executive_insights.append('No interviews in selected range.')
        else:
            executive_insights.append(f'Hire rate is {round((hired_count / total_interviews) * 100)}% across selected scope.')
            if dropoff_analysis['total_dropoffs'] > 0:
                executive_insights.append(f'Drop-offs total {dropoff_analysis["total_dropoffs"]}, led by rejected/cancelled candidates.')
            if offers_made > 0:
                executive_insights.append(f'Offer acceptance is {offer_acceptance["acceptance_rate"]}% ({offers_accepted}/{offers_made}).')
            if sla_compliance['breached'] > 0:
                executive_insights.append(f'{sla_compliance["breached"]} candidates are currently outside SLA.')

        total_target = 0
        for role in open_roles:
            try:
                total_target += max(int(role.get('position') or 0), 0)
            except (TypeError, ValueError):
                continue
        all_monthly_hires = [all_hire_monthly_counts[(y, m)] for y, m in month_points]
        last3_hires = all_monthly_hires[-3:] if len(all_monthly_hires) >= 3 else all_monthly_hires
        avg_recent_hires = round(sum(last3_hires) / len(last3_hires), 1) if last3_hires else 0

        forecast_labels = []
        projected_hires = []
        next_month_date = timezone.localtime(now, tz).replace(day=1)
        for i in range(1, 4):
            m = next_month_date.month + i - 1
            y = next_month_date.year + ((m - 1) // 12)
            m = ((m - 1) % 12) + 1
            forecast_labels.append(timezone.datetime(y, m, 1).strftime('%b %Y'))
            projected_hires.append(round(avg_recent_hires, 1))

        open_demand_target = total_target
        monthly_target = round(open_demand_target / 3, 1) if open_demand_target else 0
        if total_target == 0:
            delivery_status = 'Monitoring'
        elif hired_count > total_target:
            delivery_status = 'Ahead of target'
        elif hired_count == total_target:
            delivery_status = 'At target'
        elif hired_count > 0:
            delivery_status = 'In progress'
        else:
            delivery_status = 'Not started'
        delivery_ratio = round((hired_count / total_target), 3) if total_target else 0

        forecast_vs_target = {
            'current_target': total_target,
            'current_hired': hired_count,
            'monthly_target': monthly_target,
            'open_demand_target': open_demand_target,
            'next_labels': forecast_labels,
            'projected_hires': projected_hires,
            'expected_gap_next_month': round(max(monthly_target - projected_hires[0], 0), 1) if projected_hires else 0,
            'projection_basis': 'Projection based on average hires from the last 3 months',
            'delivery_status': delivery_status,
            'delivery_ratio': delivery_ratio,
        }

        anomaly_flags = []
        drop_rate = round((dropoff_analysis['total_dropoffs'] / total_interviews) * 100, 1) if total_interviews else 0
        if drop_rate >= 35:
            anomaly_flags.append({
                'severity': 'high',
                'title': 'High drop-off rate',
                'detail': f'{drop_rate}% of interviews ended in drop-offs.',
            })
        if sla_compliance['compliance_rate'] < 70:
            anomaly_flags.append({
                'severity': 'high',
                'title': 'Low SLA compliance',
                'detail': f'Compliance is {sla_compliance["compliance_rate"]}%.',
            })
        if offers_made >= 3 and offer_acceptance['acceptance_rate'] < 50:
            anomaly_flags.append({
                'severity': 'medium',
                'title': 'Low offer acceptance',
                'detail': f'Acceptance rate is {offer_acceptance["acceptance_rate"]}% over {offers_made} offers.',
            })
        low_conv_recruiter = next((x for x in recruiter_performance if x['interviews'] >= 5 and x['conversion'] < 15), None)
        if low_conv_recruiter:
            anomaly_flags.append({
                'severity': 'medium',
                'title': 'Recruiter conversion below threshold',
                'detail': f'{low_conv_recruiter["name"]} conversion is {low_conv_recruiter["conversion"]}% ({low_conv_recruiter["interviews"]} interviews).',
            })
        risky_role = next((x for x in role_health if x['risk'] >= 80), None)
        if risky_role:
            anomaly_flags.append({
                'severity': 'medium',
                'title': 'Role at high hiring risk',
                'detail': f'{risky_role["role"]} risk score is {risky_role["risk"]}.',
            })
        anomaly_flags = anomaly_flags[:6]

        executive_snapshot = {
            'generated_at': now.isoformat(),
            'filters': {
                'recruiter': recruiter_filter or 'all',
                'role': role_filter or 'all',
                'start_date': start_date_str or '',
                'end_date': end_date_str or '',
            },
            'kpis': {
                'total_interviews': total_interviews,
                'hire_rate': round((hired_count / total_interviews) * 100) if total_interviews else 0,
                'dropoff_rate': drop_rate,
                'sla_compliance_rate': sla_compliance['compliance_rate'],
                'offer_acceptance_rate': offer_acceptance['acceptance_rate'],
            }
        }

        avg_tth = round(sum(tth_days) / len(tth_days), 1) if tth_days else 0
        median_tth = round(median(tth_days), 1) if tth_days else 0

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'summary': {
                    'total_interviews': total_interviews,
                    'hires': hired_count,
                    'hire_rate': round((hired_count / total_interviews) * 100) if total_interviews else 0,
                    'open_roles': open_roles_count,
                    'avg_time_to_hire_days': avg_tth,
                    'median_time_to_hire_days': median_tth,
                },
                'funnel': {
                    'labels': funnel_labels,
                    'values': funnel_values,
                    'conversions': conversions,
                },
                'time_to_hire': {
                    'avg_days': avg_tth,
                    'median_days': median_tth,
                    'monthly_labels': tth_labels,
                    'monthly_avg_days': tth_monthly_avg,
                    'monthly_hires': tth_monthly_hires,
                    'monthly_total_hires': tth_monthly_total_hires,
                },
                'source_effectiveness': source_effectiveness[:8],
                'recruiter_performance': recruiter_performance[:8],
                'role_health': role_health[:8],
                'interview_quality': {
                    'evaluated': evaluated,
                    'score_bands': score_bands,
                },
                'dropoff_analysis': dropoff_analysis,
                'offer_acceptance': offer_acceptance,
                'sla_compliance': sla_compliance,
                'executive_insights': executive_insights,
                'forecast_vs_target': forecast_vs_target,
                'anomaly_flags': anomaly_flags,
                'executive_snapshot': executive_snapshot,
                'filter_options': {
                    'recruiters': recruiter_options,
                    'roles': role_options,
                },
                'phase_meta': {
                    'implemented': [1, 2, 3],
                    'pending': [],
                    'note': 'All three phases are implemented.',
                    **({'debug': debug} if include_debug else {}),
                }
            }
        })
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': {}})
