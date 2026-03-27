import base64
import io
import mimetypes
import os
import random
import re
import string
import secrets
import signal
import subprocess
import tempfile
from collections import defaultdict
from datetime import timedelta, datetime, time
from statistics import median

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import signing
from django.core import serializers
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .forms import LoginForm, CandidateSignupForm, CandidateLoginForm, CandidateProfileUpdateForm
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from .models import Interview
from .models import UserNotificationPreference, UserProfile, Vacancies
from django.db import transaction
from django.db.models import Count, Case, When, CharField, Value, Q, F
from django.utils import timezone
from smartInterviewApp.notifications.channels import send_sms, send_template_message
from smartInterviewApp.identity_verification import CandidateIdentityVerificationService
from smartInterviewApp.insights import CandidateInsightService
from smartInterviewApp.otp.services import request_email_otp, request_otp, verify_email_otp, verify_otp
from smartInterviewApp.resume_processing import ResumeProcessingService
from .models import CandidateIdentityVerification, CandidateInsightSnapshot, CandidatePublicResume, CandidateResume, CandidateVacancyApplication


SIGNUP_TOKEN_SALT = 'candidate-signup'
SIGNUP_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
PDF_RENDERER_PYTHON_CANDIDATES = [
    '/Users/sayyadlucky/PycharmProjects/smartvideo/.venv/bin/python',
]
PDF_BROWSER_CANDIDATES = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]


def normalize_interview_status(value: str) -> str:
    raw = (value or '').strip().lower().replace('-', ' ').replace('_', ' ')
    raw = ' '.join(raw.split()).replace('assesment', 'assessment')
    status_map = {
        'scheduled': 'scheduled',
        'completed': 'completed',
        'cancelled': 'cancelled',
        'shortlisted': 'shortlisted',
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
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def split_name(name: str) -> tuple[str, str]:
    parts = [part for part in (name or '').strip().split() if part]
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


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


def is_identity_verified(record: CandidateIdentityVerification | None) -> bool:
    if not record:
        return False
    return record.status in {
        CandidateIdentityVerification.Status.XML_VERIFIED,
        CandidateIdentityVerification.Status.DOCUMENT_MATCHED,
    }


def build_candidate_details(candidate: Interview) -> dict:
    return {
        'id': candidate.id,
        'name': f"{candidate.candidate.first_name} {candidate.candidate.last_name}".strip().title(),
        'email': candidate.candidate.email,
        'phone': candidate.candidate.profile.phone if hasattr(candidate.candidate, 'profile') else '',
        'recruiter': f"{candidate.recruiter.first_name} {candidate.recruiter.last_name}".strip().title() if candidate.recruiter else '',
        'status': candidate.status,
        'score': candidate.score,
        'recording_url': candidate.recording_url,
        'notes': candidate.notes,
        'date': candidate.date,
        'role': candidate.role.role if candidate.role else '',
        'role_id': candidate.role.id if candidate.role else None,
    }


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
    profile_picture_url = request.build_absolute_uri(profile.profile_picture.url) if profile and profile.profile_picture else ''
    profile_picture_data_url = ''
    if profile and profile.profile_picture:
        try:
            mime_type, _ = mimetypes.guess_type(profile.profile_picture.path)
            with open(profile.profile_picture.path, 'rb') as image_handle:
                encoded = base64.b64encode(image_handle.read()).decode('ascii')
            profile_picture_data_url = f"data:{mime_type or 'image/jpeg'};base64,{encoded}"
        except Exception:
            profile_picture_data_url = ''
    share_url = request.build_absolute_uri(reverse('public-candidate-resume', args=[public_resume.short_code]))

    sections = []
    for section in resume_data.get('sections') or []:
        section_text = extract_resume_section_text(section)
        sections.append({
            'title': section.get('title') or 'Section',
            'section_key': section.get('section_key') or '',
            'text': section_text,
            'items': ((section.get('content') or {}).get('items') or []),
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


def send_existing_candidate_sms(candidate: User, interview: Interview) -> dict:
    profile = getattr(candidate, 'profile', None)
    phone = normalize_phone(profile.phone if profile else '')
    if not phone:
        return {'sent': False, 'reason': 'Candidate phone number is missing.'}

    recruiter_name = f"{interview.recruiter.first_name} {interview.recruiter.last_name}".strip().title() if interview.recruiter else 'our team'
    role_name = interview.role.role if interview.role else 'the role'
    message = (
        f"Hi {candidate.first_name or 'Candidate'}, you have been added for the {role_name} role on SmartInterview. "
        f"Our recruiter {recruiter_name} will connect with you shortly regarding the interview."
    )
    sms_result = send_sms(phone, message, metadata={'event_type': 'candidate_interview_created', 'interview_id': interview.id})
    whatsapp_result = send_candidate_whatsapp_notification(
        phone=phone,
        template_name=getattr(settings, 'CANDIDATE_EXISTING_WHATSAPP_TEMPLATE', 'candidate_interview_created'),
        parameters=[candidate.first_name or 'Candidate', role_name, recruiter_name],
        metadata={'event_type': 'candidate_interview_created', 'interview_id': interview.id},
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
        'message': message,
    }


def send_new_candidate_signup_sms(request, candidate: User, interview: Interview) -> dict:
    profile = getattr(candidate, 'profile', None)
    phone = normalize_phone(profile.phone if profile else '')
    if not phone:
        return {'sent': False, 'reason': 'Candidate phone number is missing.'}

    token = build_candidate_signup_token(candidate, interview)
    signup_url = request.build_absolute_uri(f"{reverse('candidate-signup')}?token={token}")
    role_name = interview.role.role if interview.role else 'the role'
    message = (
        f"Hi {candidate.first_name or 'Candidate'}, complete your SmartInterview profile for the {role_name} role: "
        f"{signup_url} Set your password and upload your resume to proceed."
    )
    sms_result = send_sms(phone, message, metadata={'event_type': 'candidate_signup_invite', 'interview_id': interview.id})
    whatsapp_result = send_candidate_whatsapp_notification(
        phone=phone,
        template_name=getattr(settings, 'CANDIDATE_SIGNUP_WHATSAPP_TEMPLATE', 'candidate_signup_invite'),
        parameters=[candidate.first_name or 'Candidate', role_name, signup_url],
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

        message = (
            f"Candidate application alert: {candidate_name} applied for {vacancy.role}. "
            f"Please review the candidate profile and decide the next hiring step."
        )
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
            user_type = request.POST.get('role','')
            recruiter = request.POST.get('recruiter','')
            admin = get_object_or_404(User, username=request.user.username)
            normalized_user_type = (user_type or '').strip().lower()
            role_obj = Vacancies.objects.get(id=role) if normalized_user_type != 'recruiter' and role else None
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
                    obj.set_unusable_password()
                    obj.save()
                    # Create or update UserProfile with the given role
                    profile, created_profile = UserProfile.objects.get_or_create(
                        user=obj,
                        defaults={
                            'gender': gender,
                            'role': normalized_user_type,
                            'phone': phone,
                            'hr': admin
                        }
                    )
                    if not created_profile:
                        profile.role = normalized_user_type
                        profile.gender = gender or profile.gender
                        profile.phone = phone or profile.phone
                        profile.hr = admin
                        profile.save()
                    if normalized_user_type != 'recruiter':
                        # Add the created user profile to the Interview model if needed
                        recruiter = User.objects.get(id=recruiter)
                        hr = User.objects.get(username=request.user.username)
                        candidate = Interview.objects.create(candidate=obj, recruiter=recruiter, hr=hr, status='assessment_pending', role=role_obj)
                        candidate.save()
                        candidate_details = build_candidate_details(candidate)
                        notification_result = send_new_candidate_signup_sms(request, obj, candidate)
                    if normalized_user_type == 'recruiter':
                        recruiter_details = {}
                        recruiter_details['id'] = profile.id
                        recruiter_details['name'] = (
                                    profile.user.first_name + " " + profile.user.last_name).title()
                        recruiter_details['email'] = profile.user.email
                        recruiter_details['role'] = profile.role
                        recruiter_details['phone'] = profile.phone
                        recruiter_details['gender'] = profile.gender
                        return JsonResponse({"Success": True, "Error": None, "RecruiterData": recruiter_details})
                else:
                    if not obj.first_name or not obj.last_name:
                        obj.first_name = first_name or obj.first_name
                        obj.last_name = last_name or obj.last_name
                        obj.save(update_fields=['first_name', 'last_name'])
                    profile, created_profile = UserProfile.objects.get_or_create(
                        user=obj,
                        defaults={
                            'gender': gender,
                            'role': normalized_user_type,
                            'phone': phone,
                            'hr': admin
                        }
                    )
                    if not created_profile:
                        profile.role = normalized_user_type
                        profile.gender = gender or profile.gender
                        profile.phone = phone or profile.phone
                        profile.hr = admin
                        profile.save()
                    if normalized_user_type == 'recruiter':
                        recruiter_details = {}
                        recruiter_details['id'] = profile.id
                        recruiter_details['name'] = (
                            profile.user.first_name + " " + profile.user.last_name).title()
                        recruiter_details['email'] = profile.user.email
                        recruiter_details['role'] = profile.role
                        recruiter_details['phone'] = profile.phone
                        recruiter_details['gender'] = profile.gender
                        return JsonResponse({"Success": True, "Error": None, "RecruiterData": recruiter_details})
                    if normalized_user_type != 'recruiter':
                        # Add the created user profile to the Interview model if needed
                        recruiter = User.objects.get(id=recruiter)
                        hr = User.objects.get(username=request.user.username)
                        candidate = Interview.objects.create(candidate=obj, recruiter=recruiter, hr=hr,
                                                             status='assessment_pending', role=role_obj)
                        candidate.save()
                        candidate_details = build_candidate_details(candidate)
                        notification_result = send_existing_candidate_sms(obj, candidate)
            else:
                    return JsonResponse({"Success":False, "Error":'Add user failed'})
            return JsonResponse({
                "Success": True,
                "Error": None,
                "CandidateDetails": candidate_details,
                "Notification": notification_result if normalized_user_type != 'recruiter' else None,
                "CandidateExists": not created if normalized_user_type != 'recruiter' else False,
                "SignupRequired": created if normalized_user_type != 'recruiter' else False,
            })
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})


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


def candidateSignup(request):
    token = (request.GET.get('token') or '').strip()
    signup_context = None
    token_error = ''
    interview = None
    user = None
    profile = None

    if token:
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
            return render(request, 'smartInterview/candidate_signup.html', {
                'form': None,
                'token_error': token_error,
                'signup_context': signup_context,
                'signup_success': True,
            })
    else:
        form = CandidateSignupForm(user=user, manual_mode=signup_context is None)

    return render(request, 'smartInterview/candidate_signup.html', {
        'form': form,
        'token': token,
        'token_error': token_error,
        'signup_context': signup_context,
        'signup_success': False,
    })


def candidateLogin(request):
    if request.user.is_authenticated:
        role = getattr(getattr(request.user, 'profile', None), 'role', '')
        if role == 'candidate':
            return redirect('candidate-dashboard')
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
                return redirect('candidate-dashboard')
    else:
        form = CandidateLoginForm()

    return render(request, 'smartInterview/candidate_login.html', {'form': form})


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
        )
    else:
        application.status = CandidateVacancyApplication.Status.PENDING_REVIEW
        application.reviewed_at = None
        application.save(update_fields=['status', 'reviewed_at', 'updated_at'])

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
        defaults={'status': CandidateVacancyApplication.Status.NOT_INTERESTED},
    )
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


@login_required
def recruiterApplicationFeed(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in {'recruiter', 'admin'}:
        return JsonResponse({'Success': False, 'Error': 'Recruiter or admin access required.', 'Data': {}})

    applications_qs = (
        CandidateVacancyApplication.objects
        .select_related('candidate', 'candidate__profile', 'vacancy', 'vacancy__admin')
        .prefetch_related('vacancy__recruiter')
        .filter(status=CandidateVacancyApplication.Status.PENDING_REVIEW)
        .order_by('-applied_at', '-id')
    )
    if profile.role == 'recruiter':
        applications_qs = applications_qs.filter(vacancy__recruiter=request.user)
    else:
        applications_qs = applications_qs.filter(vacancy__admin=request.user)

    applications_qs = applications_qs.distinct()
    applications = []
    for application in applications_qs[:12]:
        candidate = application.candidate
        candidate_profile = getattr(candidate, 'profile', None)
        applications.append({
            'id': application.id,
            'candidate_id': candidate.id,
            'candidate_name': f"{candidate.first_name} {candidate.last_name}".strip() or candidate.username,
            'candidate_email': candidate.email,
            'candidate_phone': candidate_profile.phone if candidate_profile else '',
            'vacancy_id': application.vacancy_id,
            'vacancy_role': application.vacancy.role,
            'status': application.status,
            'status_label': application.status.replace('_', ' ').title(),
            'applied_at': application.applied_at.isoformat() if application.applied_at else '',
            'source': application.source,
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
    profile_picture_url = request.build_absolute_uri(profile.profile_picture.url) if profile.profile_picture else ''
    resume_file_url = request.build_absolute_uri(profile.resume.url) if profile.resume else ''
    resume_sections = []
    career_objective = ''
    for section in (resume_data.get('sections') or []):
        if section.get('section_key') == 'objective' and not career_objective:
            career_objective = ((section.get('content') or {}).get('text') or section.get('raw_text') or '').strip()
        if section.get('section_key') in {'summary', 'objective', 'skills'}:
            continue
        resume_sections.append({
            'title': section.get('title') or 'Section',
            'text': (section.get('content') or {}).get('text') or section.get('raw_text') or '',
            'items': (section.get('content') or {}).get('items') or [],
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
            'status': vacancy.status,
            'date': vacancy.date,
            'description': (vacancy.description or '').strip(),
            'recruiters': recruiter_names,
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
        interview = (
            Interview.objects
            .select_related('candidate', 'candidate__profile', 'recruiter', 'role')
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
        resume_data = ResumeProcessingService().serialize_resume(latest_resume)
        profile = interview.candidate.profile
        prefs, _ = UserNotificationPreference.objects.get_or_create(user=interview.candidate)
        identity_record = CandidateIdentityVerification.objects.filter(candidate=interview.candidate).first()
        insight_snapshot = CandidateInsightSnapshot.objects.filter(candidate=interview.candidate).first()
        public_resume = CandidatePublicResume.objects.filter(candidate=interview.candidate, is_active=True).first()
        resume_data['file_url'] = (
            request.build_absolute_uri(profile.resume.url)
            if getattr(profile, 'resume', None)
            else ''
        )
        candidate_name = f"{interview.candidate.first_name} {interview.candidate.last_name}".strip().title()

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
                    'recruiter': f"{interview.recruiter.first_name} {interview.recruiter.last_name}".strip().title() if interview.recruiter else '',
                    'role': interview.role.role if interview.role else '',
                    'role_id': interview.role_id,
                    'status': interview.status,
                    'score': interview.score,
                    'date': interview.date.isoformat() if interview.date else '',
                    'profile_picture': request.build_absolute_uri(profile.profile_picture.url)
                    if getattr(profile, 'profile_picture', None)
                    else '',
                    'public_resume_downloads': public_resume.download_count if public_resume else 0,
                },
                'verification': {
                    'phone_verified': bool(prefs.phone_verified_at),
                    'email_verified': bool(prefs.email_verified_at),
                    'identity_verified': is_identity_verified(identity_record),
                    'phone_verified_at': prefs.phone_verified_at.isoformat() if prefs.phone_verified_at else '',
                    'email_verified_at': prefs.email_verified_at.isoformat() if prefs.email_verified_at else '',
                    'identity_verified_at': identity_record.processed_at.isoformat() if identity_record and identity_record.processed_at else '',
                    'identity_status': identity_record.status if identity_record else CandidateIdentityVerification.Status.NOT_STARTED,
                },
                'insights': CandidateInsightService().serialize_snapshot(insight_snapshot),
                'resume': resume_data,
            }
        })
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': None}, status=500)


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
            status = request.POST.get('status', '')
            recruiter_ids = request.POST.getlist('recruiter')
            if not recruiter_ids:
                single_recruiter = request.POST.get('recruiter', '')
                if single_recruiter:
                    recruiter_ids = [single_recruiter]
            user = User.objects.get(username=request.user.username)
            if user.profile.role == 'admin':
                obj = Vacancies(
                        role= name,
                        description= description,
                        position= int(vacancies) if vacancies.isdigit() else 0,
                        status= status,
                        admin= user,
                )
                obj.save()
                valid_recruiters = User.objects.filter(id__in=recruiter_ids, profile__role='recruiter')
                if not valid_recruiters.exists():
                    return JsonResponse({"Success": False, "Error": "Please select at least one valid recruiter.", "Data": ""})
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
                    "date": obj.date,
                    "status": obj.status,
                }
            }
        })
    except Exception as e:
        return JsonResponse({"Success": False, "Error": e, "Data": ""})

@login_required
def getRoleList(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        role_data = Vacancies.objects.filter(admin=admin)
        role_list = []
        for role in role_data:
            role_details = {}
            role_details['id'] = role.id
            role_details['name'] = role.role
            role_details['description'] = role.description
            role_details['vacancies'] = int(role.position) if str(role.position).isdigit() else 0
            role_list.append(role_details)
        return JsonResponse({"Success":True, "Error":None, "RoleData":role_list})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})

@login_required
def getRoleData(request, id):
    try:
        role_data = Vacancies.objects.get(id=id)

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
        role_details['status'] = role_data.status
        role_details['date'] = role_data.date
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
        recruiter_data = UserProfile.objects.filter(hr=admin, role='recruiter')
        recruiter_list = []
        for recruiter in recruiter_data:
            recruiter_details = {}
            recruiter_details['id'] = recruiter.user.id
            recruiter_details['name'] = (recruiter.user.first_name + " " + recruiter.user.last_name).title()
            recruiter_details['email'] = recruiter.user.email
            recruiter_details['role'] = recruiter.role
            recruiter_list.append(recruiter_details)
        return JsonResponse({"Success":True, "Error":None, "RecruiterData":recruiter_list})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})

@login_required
def getEvaluator(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        recruiter_data = (
            UserProfile.objects
            .filter(hr=admin, role='recruiter')
            .exclude(user__username__iexact='TBD')
            .annotate(
                interviews_count=Count(
                    'user__recruiter_interviews',
                    filter=Q(user__recruiter_interviews__hr=admin),
                    distinct=True
                )
            )
            .order_by('-interviews_count', 'user__first_name', 'user__last_name')[:8]
        )
        recruiter_list = []
        for recruiter in recruiter_data:
            recruiter_details = {}
            recruiter_details['id'] = recruiter.id
            recruiter_details['name'] = (recruiter.user.first_name + " " + recruiter.user.last_name).title()
            recruiter_details['email'] = recruiter.user.email
            recruiter_details['role'] = recruiter.role
            recruiter_details['phone'] = recruiter.phone
            recruiter_details['gender'] = recruiter.gender
            recruiter_details['interviews_count'] = recruiter.interviews_count
            recruiter_list.append(recruiter_details)
        return JsonResponse({"Success":True, "Error":None, "RecruiterData":recruiter_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "RecruiterData": []})

@csrf_exempt
@login_required
def evaluatorSearch(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        name = (request.POST.get('name') or '').strip()
        recruiter_data = UserProfile.objects.filter(hr=admin, role='recruiter').exclude(user__username__iexact='TBD')
        if name:
            recruiter_data = recruiter_data.filter(
                Q(user__first_name__icontains=name) | Q(user__last_name__icontains=name)
            )
        recruiter_data = recruiter_data.distinct()
        recruiter_list = []
        for recruiter in recruiter_data:
            recruiter_details = {}
            recruiter_details['id'] = recruiter.id
            recruiter_details['name'] = (recruiter.user.first_name + " " + recruiter.user.last_name).title()
            recruiter_details['email'] = recruiter.user.email
            recruiter_details['role'] = recruiter.role
            recruiter_details['phone'] = recruiter.phone
            recruiter_details['gender'] = recruiter.gender
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

        hr = get_object_or_404(User, username=request.user.username)
        recruiter = None

        if recruiter_email:
            recruiter = User.objects.filter(email__iexact=recruiter_email).first()

        if recruiter is None and recruiter_id.isdigit():
            profile = UserProfile.objects.filter(id=int(recruiter_id), role='recruiter').select_related('user').first()
            if profile:
                recruiter = profile.user
            else:
                recruiter = User.objects.filter(id=int(recruiter_id)).first()

        if recruiter is None:
            return JsonResponse({"Success": False, "Error": "Recruiter not found.", "Interviews": []})

        interviews = (
            Interview.objects
            .filter(recruiter=recruiter, hr=hr)
            .select_related('candidate', 'role')
            .order_by('-date')[:1000]
        )
        interview_list = []

        for interview in interviews:
            interview_details = {}
            interview_details['id'] = interview.id
            interview_details['candidate'] = f"{interview.candidate.first_name} {interview.candidate.last_name}".title()
            interview_details['status'] = interview.status
            interview_details['score'] = interview.score
            interview_details['role'] = interview.role.role if interview.role else ''
            interview_details['date'] = interview.date.isoformat() if interview.date else ''
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
        admin = get_object_or_404(User, username=request.user.username)
        interviews = (
            Interview.objects
            .filter(hr=admin)
            .select_related('candidate', 'recruiter', 'role')
            .order_by('-date')
        )

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
            recruiter_agg[recruiter_name] += 1

            candidate_rows.append({
                "id": item.id,
                "name": f"{item.candidate.first_name} {item.candidate.last_name}".strip().title(),
                "email": item.candidate.email,
                "status": normalized,
                "recruiter": recruiter_name,
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


@login_required
def activityTabData(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        now = timezone.now()
        tz = timezone.get_current_timezone()
        base_qs = (
            Interview.objects
            .filter(hr=admin)
            .select_related('candidate', 'recruiter', 'role')
            .order_by('-date')
        )

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
                'name': f"{(row.get('recruiter__first_name') or '').strip()} {(row.get('recruiter__last_name') or '').strip()}".strip().title() or 'Unassigned'
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
                'name': row.get('role__role') or 'Unassigned'
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

        total_interviews = interviews.count()
        upcoming_count = interviews.filter(status='scheduled', date__gte=now).count()
        hired_count = interviews.filter(status__in=['hired', 'completed']).count()
        active_recruiters = interviews.exclude(recruiter__isnull=True).values('recruiter').distinct().count()
        open_roles = Vacancies.objects.filter(admin=admin).exclude(status__in=['closed', 'canceled', 'hired']).count()
        last_30_days = interviews.filter(date__gte=now - timedelta(days=30)).count()

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
            cursor_year = now.year
            cursor_month = now.month
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
            month_qs = interviews.filter(date__year=y, date__month=m)
            trend_counts.append(month_qs.count())
            trend_hired.append(month_qs.filter(status__in=['hired', 'completed']).count())

        if month_labels:
            trend_title = f"Interview Trend ({month_labels[0]} - {month_labels[-1]})" if (parsed_start_date or parsed_end_date) else trend_title

        status_buckets = {
            'Scheduled': 0,
            'Assessment Pending': 0,
            'Shortlisted': 0,
            'Hired': 0,
            'Rejected': 0,
            'Cancelled': 0,
            'Auto Screening': 0,
        }
        for item in interviews:
            normalized = normalize_interview_status(item.status)
            if normalized == 'scheduled':
                status_buckets['Scheduled'] += 1
            elif normalized == 'assessment_pending':
                status_buckets['Assessment Pending'] += 1
            elif normalized == 'shortlisted':
                status_buckets['Shortlisted'] += 1
            elif normalized in ['hired', 'completed']:
                status_buckets['Hired'] += 1
            elif normalized == 'rejected':
                status_buckets['Rejected'] += 1
            elif normalized == 'cancelled':
                status_buckets['Cancelled'] += 1
            elif normalized == 'auto_screening_scheduled':
                status_buckets['Auto Screening'] += 1

        # Phase 1: SLA alerts
        overdue_scheduled = interviews.filter(status='scheduled', date__lt=now).count()
        stale_assessment = interviews.filter(status='assessment_pending', date__lt=now - timedelta(days=7)).count()
        stale_shortlisted = interviews.filter(status='shortlisted', date__lt=now - timedelta(days=10)).count()
        unassigned_recruiter = interviews.filter(recruiter__isnull=True).count()
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
        current_range_qs = interviews.filter(date__gte=current_start_dt, date__lte=current_end_dt)
        previous_range_qs = base_qs.filter(date__gte=prev_start_dt, date__lte=prev_end_dt)
        if recruiter_filter and recruiter_filter != 'all' and recruiter_filter.isdigit():
            previous_range_qs = previous_range_qs.filter(recruiter_id=int(recruiter_filter))
        if role_filter and role_filter != 'all' and role_filter.isdigit():
            previous_range_qs = previous_range_qs.filter(role_id=int(role_filter))

        def build_stage_counts(queryset):
            stage_counts = {
                'Applied': 0,
                'Assessment Pending': 0,
                'Scheduled': 0,
                'Shortlisted': 0,
                'Hired': 0,
                'Rejected': 0,
                'Cancelled': 0,
            }
            for x in queryset:
                n = normalize_interview_status(x.status)
                if n in ['assessment_pending', 'auto_screening_scheduled']:
                    stage_counts['Assessment Pending'] += 1
                elif n == 'scheduled':
                    stage_counts['Scheduled'] += 1
                elif n == 'shortlisted':
                    stage_counts['Shortlisted'] += 1
                elif n in ['hired', 'completed']:
                    stage_counts['Hired'] += 1
                elif n == 'rejected':
                    stage_counts['Rejected'] += 1
                elif n == 'cancelled':
                    stage_counts['Cancelled'] += 1
                stage_counts['Applied'] += 1
            return stage_counts

        current_stage_counts = build_stage_counts(current_range_qs)
        previous_stage_counts = build_stage_counts(previous_range_qs)
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
        no_show_count = interviews.filter(status='scheduled', date__lt=now).count()
        screening_drop = interviews.filter(status='assessment_pending', date__lt=now - timedelta(days=7)).count()
        dropoff_reasons = [
            {'reason': 'Rejected', 'count': interviews.filter(status='rejected').count()},
            {'reason': 'Cancelled', 'count': interviews.filter(status='cancelled').count()},
            {'reason': 'No Show / Missed', 'count': no_show_count},
            {'reason': 'Screening Timeout', 'count': screening_drop},
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

        # Phase 2: Recruiter response-time proxy (candidate created -> interview date)
        lead_time_hours = []
        recruiter_lead = defaultdict(list)
        for item in interviews:
            if not item.date or not item.candidate or not item.candidate.date_joined:
                continue
            diff_hours = (item.date - item.candidate.date_joined).total_seconds() / 3600
            if diff_hours < 0:
                continue
            lead_time_hours.append(diff_hours)
            recruiter_name = (
                f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title()
                if item.recruiter else 'Unassigned'
            )
            recruiter_lead[recruiter_name].append(diff_hours)

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
        score_bands = {
            'Excellent (8-10)': 0,
            'Good (6-7.9)': 0,
            'Average (4-5.9)': 0,
            'Low (<4)': 0,
        }
        scored_count = 0
        for item in interviews:
            if item.score is None:
                continue
            scored_count += 1
            score_val = float(item.score)
            if score_val >= 8:
                score_bands['Excellent (8-10)'] += 1
            elif score_val >= 6:
                score_bands['Good (6-7.9)'] += 1
            elif score_val >= 4:
                score_bands['Average (4-5.9)'] += 1
            else:
                score_bands['Low (<4)'] += 1

        quality_by_role = []
        role_quality_stats = (
            interviews
            .values('role__role')
            .annotate(
                total=Count('id'),
                hired=Count('id', filter=Q(status__in=['hired', 'completed'])),
                shortlisted=Count('id', filter=Q(status='shortlisted')),
            )
            .order_by('-total')[:8]
        )
        for row in role_quality_stats:
            total = row.get('total') or 0
            positive = (row.get('hired') or 0) + (row.get('shortlisted') or 0)
            quality_by_role.append({
                'role': row.get('role__role') or 'Unassigned',
                'total': total,
                'positive': positive,
                'pass_rate': round((positive / total) * 100) if total else 0,
            })

        outcome_quality = {
            'evaluated': interviews.filter(status__in=['completed', 'hired', 'shortlisted', 'rejected', 'cancelled']).count(),
            'hired': hired_count,
            'shortlisted': interviews.filter(status='shortlisted').count(),
            'rejected': interviews.filter(status='rejected').count(),
            'score_bands': score_bands,
            'scored_count': scored_count,
            'quality_by_role': quality_by_role,
        }

        # Phase 2: Daily/weekly productivity
        today_local = timezone.localtime(now, tz).date()
        daily_points = []
        for idx in range(13, -1, -1):
            day = today_local - timedelta(days=idx)
            day_start = timezone.make_aware(datetime.combine(day, time.min), tz)
            day_end = timezone.make_aware(datetime.combine(day, time.max), tz)
            day_qs = interviews.filter(date__gte=day_start, date__lte=day_end)
            daily_points.append({
                'key': day.strftime('%Y-%m-%d'),
                'label': day.strftime('%d %b'),
                'total': day_qs.count(),
                'hired': day_qs.filter(status__in=['hired', 'completed']).count(),
                'scheduled': day_qs.filter(status='scheduled').count(),
            })

        current_week_start = today_local - timedelta(days=today_local.weekday())
        current_week_start_dt = timezone.make_aware(datetime.combine(current_week_start, time.min), tz)
        current_week_end_dt = timezone.make_aware(datetime.combine(today_local, time.max), tz)
        prev_week_end = current_week_start - timedelta(days=1)
        prev_week_start = prev_week_end - timedelta(days=6)
        prev_week_start_dt = timezone.make_aware(datetime.combine(prev_week_start, time.min), tz)
        prev_week_end_dt = timezone.make_aware(datetime.combine(prev_week_end, time.max), tz)

        productivity = {
            'daily': daily_points,
            'current_week_total': interviews.filter(date__gte=current_week_start_dt, date__lte=current_week_end_dt).count(),
            'previous_week_total': interviews.filter(date__gte=prev_week_start_dt, date__lte=prev_week_end_dt).count(),
            'current_week_hired': interviews.filter(date__gte=current_week_start_dt, date__lte=current_week_end_dt, status__in=['hired', 'completed']).count(),
        }

        # Phase 2: Upcoming load heat (next 7 days x 4 slots)
        heat_days = []
        for i in range(7):
            heat_days.append(today_local + timedelta(days=i))
        slot_order = ['Night', 'Morning', 'Afternoon', 'Evening']
        slot_map = {slot: 0 for slot in slot_order}
        heat_rows = {day.strftime('%Y-%m-%d'): dict(slot_map) for day in heat_days}
        upcoming_heat_qs = interviews.filter(status='scheduled', date__gte=now, date__lte=now + timedelta(days=7))

        max_cell = 0
        for item in upcoming_heat_qs:
            local_dt = timezone.localtime(item.date, tz)
            day_key = local_dt.date().strftime('%Y-%m-%d')
            if day_key not in heat_rows:
                continue
            hour = local_dt.hour
            if hour < 6:
                slot = 'Night'
            elif hour < 12:
                slot = 'Morning'
            elif hour < 18:
                slot = 'Afternoon'
            else:
                slot = 'Evening'
            heat_rows[day_key][slot] += 1
            max_cell = max(max_cell, heat_rows[day_key][slot])

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
            'total_scheduled': upcoming_heat_qs.count(),
        }

        # Phase 3: Open role risk score
        open_vacancies_qs = Vacancies.objects.filter(admin=admin).exclude(status__in=['closed', 'canceled', 'hired'])
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

            role_qs = interviews.filter(role_id=vacancy.id)
            filled = role_qs.filter(status__in=['hired', 'completed']).count()
            active_pipeline_count = role_qs.filter(
                status__in=['scheduled', 'assessment_pending', 'auto_screening_scheduled', 'shortlisted']
            ).count()
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
            hires_for_month = interviews.filter(date__year=y, date__month=m, status__in=['hired', 'completed']).count()
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
        candidate_map = defaultdict(list)
        for item in interviews.order_by('candidate_id', 'date'):
            candidate_map[item.candidate_id].append(item)

        closed_statuses = {'rejected', 'cancelled'}
        active_statuses = {'assessment_pending', 'auto_screening_scheduled', 'scheduled', 'shortlisted', 'hired', 'completed'}

        for _, entries in candidate_map.items():
            if not entries:
                continue
            candidate_name = f"{entries[0].candidate.first_name} {entries[0].candidate.last_name}".strip().title()
            latest = entries[-1]
            normalized_statuses = [normalize_interview_status(x.status) for x in entries]
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
                role_names = sorted({(x.role.role if x.role else 'Unassigned') for x in entries})
                recycled_candidates.append({
                    'candidate': candidate_name,
                    'interviews': len(entries),
                    'roles': role_names[:3],
                    'latest_status': normalize_interview_status(latest.status).replace('_', ' ').title(),
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

        recruiter_stats = (
            interviews
            .exclude(recruiter__isnull=True)
            .values('recruiter', 'recruiter__first_name', 'recruiter__last_name')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        recruiter_breakdown = []
        for r in recruiter_stats:
            recruiter_breakdown.append({
                'name': f"{(r.get('recruiter__first_name') or '').strip()} {(r.get('recruiter__last_name') or '').strip()}".strip().title() or 'Unassigned',
                'count': r.get('count', 0),
            })

        role_stats = (
            interviews
            .values('role', 'role__role')
            .annotate(
                count=Count('id'),
                hired=Count('id', filter=Q(status__in=['hired', 'completed']))
            )
            .order_by('-count')[:8]
        )
        role_breakdown = []
        for r in role_stats:
            role_breakdown.append({
                'role': r.get('role__role') or 'Unassigned',
                'count': r.get('count', 0),
                'hired': r.get('hired', 0),
            })

        recent_activity = []
        for item in interviews[:14]:
            status = normalize_interview_status(item.status).replace('_', ' ').title()
            candidate_name = f"{item.candidate.first_name} {item.candidate.last_name}".strip().title()
            role_name = item.role.role if item.role else 'Unassigned'
            recruiter_name = (
                f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title()
                if item.recruiter else 'Unassigned'
            )
            recent_activity.append({
                'id': item.id,
                'title': f"{candidate_name} - {status}",
                'meta': f"{role_name} • {recruiter_name}",
                'date': item.date.isoformat() if item.date else '',
            })

        upcoming_list = []
        for item in interviews.filter(status='scheduled', date__gte=now).order_by('date')[:8]:
            upcoming_list.append({
                'id': item.id,
                'candidate': f"{item.candidate.first_name} {item.candidate.last_name}".strip().title(),
                'role': item.role.role if item.role else 'Unassigned',
                'date': item.date.isoformat() if item.date else '',
            })

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'summary': {
                    'total_interviews': total_interviews,
                    'upcoming': upcoming_count,
                    'hired': hired_count,
                    'active_recruiters': active_recruiters,
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
        admin = get_object_or_404(User, username=request.user.username)
        now = timezone.now()
        tz = timezone.get_current_timezone()

        base_qs = (
            Interview.objects
            .filter(hr=admin)
            .select_related('candidate', 'recruiter', 'role')
            .order_by('-date')
        )

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
                'name': f"{(row.get('recruiter__first_name') or '').strip()} {(row.get('recruiter__last_name') or '').strip()}".strip().title() or 'Unassigned'
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
                'name': row.get('role__role') or 'Unassigned'
            })

        interviews = base_qs
        recruiter_filter = (request.GET.get('recruiter') or '').strip()
        role_filter = (request.GET.get('role') or '').strip()
        start_date_str = (request.GET.get('start_date') or '').strip()
        end_date_str = (request.GET.get('end_date') or '').strip()
        parsed_start_date = None
        parsed_end_date = None

        if recruiter_filter and recruiter_filter != 'all' and recruiter_filter.isdigit():
            interviews = interviews.filter(recruiter_id=int(recruiter_filter))
        if role_filter and role_filter != 'all' and role_filter.isdigit():
            interviews = interviews.filter(role_id=int(role_filter))

        if start_date_str:
            parsed_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        if end_date_str:
            parsed_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
            parsed_start_date, parsed_end_date = parsed_end_date, parsed_start_date

        if parsed_start_date:
            start_dt = timezone.make_aware(datetime.combine(parsed_start_date, time.min), tz)
            interviews = interviews.filter(date__gte=start_dt)
        if parsed_end_date:
            end_dt = timezone.make_aware(datetime.combine(parsed_end_date, time.max), tz)
            interviews = interviews.filter(date__lte=end_dt)

        total_interviews = interviews.count()
        hired_qs = interviews.filter(status__in=['hired', 'completed'])
        hired_count = hired_qs.count()
        open_roles_count = Vacancies.objects.filter(admin=admin).exclude(status__in=['closed', 'canceled', 'hired']).count()

        # Funnel analytics
        funnel_labels = ['Applied', 'Assessment Pending', 'Scheduled', 'Shortlisted', 'Hired']
        assessment_count = interviews.filter(status__in=['assessment_pending', 'auto_screening_scheduled']).count()
        scheduled_count = interviews.filter(status='scheduled').count()
        shortlisted_count = interviews.filter(status='shortlisted').count()
        funnel_values = [total_interviews, assessment_count, scheduled_count, shortlisted_count, hired_count]
        conversions = []
        for idx in range(len(funnel_labels) - 1):
            current = funnel_values[idx]
            nxt = funnel_values[idx + 1]
            conversions.append({
                'from': funnel_labels[idx],
                'to': funnel_labels[idx + 1],
                'rate': round((nxt / current) * 100) if current else 0,
            })

        # Time-to-hire analytics
        tth_days = []
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

        tth_labels = []
        tth_monthly_avg = []
        tth_monthly_hires = []
        for y, m in month_points:
            tth_labels.append(timezone.datetime(y, m, 1).strftime('%b %Y'))
            month_hires = hired_qs.filter(date__year=y, date__month=m)
            month_values = []
            for item in month_hires:
                if item.candidate and item.candidate.date_joined and item.date:
                    diff_days = (item.date - item.candidate.date_joined).total_seconds() / 86400
                    if diff_days >= 0:
                        month_values.append(diff_days)
                        tth_days.append(diff_days)
            tth_monthly_avg.append(round(sum(month_values) / len(month_values), 1) if month_values else 0)
            tth_monthly_hires.append(month_hires.count())

        # Source effectiveness (heuristic from email domain)
        source_agg = defaultdict(lambda: {'total': 0, 'hired': 0})
        for item in interviews:
            email = (item.candidate.email or '').lower()
            if '.edu' in email:
                source = 'Campus'
            elif any(x in email for x in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']):
                source = 'Direct'
            elif '@' in email:
                source = 'Referral/Internal'
            else:
                source = 'Unknown'
            source_agg[source]['total'] += 1
            if item.status in ['hired', 'completed']:
                source_agg[source]['hired'] += 1
        source_effectiveness = []
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

        # Recruiter performance
        recruiter_map = defaultdict(lambda: {'interviews': 0, 'hired': 0})
        for item in interviews:
            r_name = (
                f"{item.recruiter.first_name} {item.recruiter.last_name}".strip().title()
                if item.recruiter else 'Unassigned'
            )
            recruiter_map[r_name]['interviews'] += 1
            if item.status in ['hired', 'completed']:
                recruiter_map[r_name]['hired'] += 1
        recruiter_performance = []
        for name, val in recruiter_map.items():
            total = val['interviews']
            hired = val['hired']
            recruiter_performance.append({
                'name': name,
                'interviews': total,
                'hired': hired,
                'conversion': round((hired / total) * 100) if total else 0,
            })
        recruiter_performance.sort(key=lambda x: x['interviews'], reverse=True)

        # Role health
        role_health = []
        open_roles_qs = Vacancies.objects.filter(admin=admin).exclude(status__in=['closed', 'canceled', 'hired'])
        if role_filter and role_filter != 'all' and role_filter.isdigit():
            open_roles_qs = open_roles_qs.filter(id=int(role_filter))
        for role in open_roles_qs:
            try:
                target = int(role.position)
            except (TypeError, ValueError):
                target = 0
            role_qs = interviews.filter(role_id=role.id)
            filled = role_qs.filter(status__in=['hired', 'completed']).count()
            pipeline = role_qs.filter(status__in=['assessment_pending', 'auto_screening_scheduled', 'scheduled', 'shortlisted']).count()
            remaining = max(target - filled, 0)
            risk = round((remaining / target) * 100) if target > 0 else 0
            role_health.append({
                'role': role.role,
                'target': target,
                'filled': filled,
                'pipeline': pipeline,
                'risk': min(100, risk),
            })
        role_health.sort(key=lambda x: x['risk'], reverse=True)

        # Interview quality
        score_bands = {
            'Excellent (8-10)': 0,
            'Good (6-7.9)': 0,
            'Average (4-5.9)': 0,
            'Low (<4)': 0,
        }
        evaluated = 0
        for item in interviews:
            if item.score is None:
                continue
            evaluated += 1
            score_val = float(item.score)
            if score_val >= 8:
                score_bands['Excellent (8-10)'] += 1
            elif score_val >= 6:
                score_bands['Good (6-7.9)'] += 1
            elif score_val >= 4:
                score_bands['Average (4-5.9)'] += 1
            else:
                score_bands['Low (<4)'] += 1

        # Phase 2: Drop-off and rejection analysis
        no_show = interviews.filter(status='scheduled', date__lt=now).count()
        screening_timeout = interviews.filter(status='assessment_pending', date__lt=now - timedelta(days=7)).count()
        dropoff_analysis = {
            'total_dropoffs': interviews.filter(status__in=['rejected', 'cancelled']).count() + no_show + screening_timeout,
            'rejected': interviews.filter(status='rejected').count(),
            'cancelled': interviews.filter(status='cancelled').count(),
            'no_show': no_show,
            'screening_timeout': screening_timeout,
            'by_role': [],
        }
        role_drop = (
            interviews
            .values('role__role')
            .annotate(
                rejected=Count('id', filter=Q(status='rejected')),
                cancelled=Count('id', filter=Q(status='cancelled')),
                total=Count('id')
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

        # Phase 2: Offer and acceptance (inferred from shortlisted/hired)
        offers_made = interviews.filter(status__in=['shortlisted', 'hired', 'completed']).count()
        offers_accepted = interviews.filter(status__in=['hired', 'completed']).count()
        offers_pending = interviews.filter(status='shortlisted').count()
        offer_acceptance = {
            'offers_made': offers_made,
            'offers_accepted': offers_accepted,
            'offers_pending': offers_pending,
            'acceptance_rate': round((offers_accepted / offers_made) * 100) if offers_made else 0,
            'monthly_labels': tth_labels,
            'monthly_offers': [],
            'monthly_accepted': [],
        }
        for y, m in month_points:
            month_qs = interviews.filter(date__year=y, date__month=m)
            offer_acceptance['monthly_offers'].append(month_qs.filter(status__in=['shortlisted', 'hired', 'completed']).count())
            offer_acceptance['monthly_accepted'].append(month_qs.filter(status__in=['hired', 'completed']).count())

        # Phase 2: SLA compliance
        active_pipeline_qs = interviews.filter(status__in=['assessment_pending', 'auto_screening_scheduled', 'scheduled', 'shortlisted'])
        active_pipeline_total = active_pipeline_qs.count()
        breached_count = (
            interviews.filter(status='scheduled', date__lt=now).count()
            + interviews.filter(status='assessment_pending', date__lt=now - timedelta(days=7)).count()
            + interviews.filter(status='shortlisted', date__lt=now - timedelta(days=10)).count()
        )
        sla_compliance = {
            'active_pipeline': active_pipeline_total,
            'breached': breached_count,
            'compliance_rate': round(((active_pipeline_total - breached_count) / active_pipeline_total) * 100) if active_pipeline_total else 100,
            'breakdown': [
                {
                    'label': 'Scheduled overdue',
                    'count': interviews.filter(status='scheduled', date__lt=now).count()
                },
                {
                    'label': 'Assessment > 7 days',
                    'count': interviews.filter(status='assessment_pending', date__lt=now - timedelta(days=7)).count()
                },
                {
                    'label': 'Shortlisted > 10 days',
                    'count': interviews.filter(status='shortlisted', date__lt=now - timedelta(days=10)).count()
                },
            ]
        }

        # Phase 2: Executive insights
        executive_insights = []
        if total_interviews == 0:
            executive_insights.append('No interviews in selected range.')
        else:
            executive_insights.append(f'Hire rate is {round((hired_count / total_interviews) * 100)}% across selected scope.')
            if dropoff_analysis['total_dropoffs'] > 0:
                executive_insights.append(
                    f'Drop-offs total {dropoff_analysis["total_dropoffs"]}, led by rejected/cancelled candidates.'
                )
            if offers_made > 0:
                executive_insights.append(f'Offer acceptance is {offer_acceptance["acceptance_rate"]}% ({offers_accepted}/{offers_made}).')
            if sla_compliance['breached'] > 0:
                executive_insights.append(f'{sla_compliance["breached"]} candidates are currently outside SLA.')

        # Phase 3: Forecast vs target
        total_target = 0
        for role in open_roles_qs:
            try:
                total_target += max(int(role.position), 0)
            except (TypeError, ValueError):
                continue
        last3_hires = tth_monthly_hires[-3:] if len(tth_monthly_hires) >= 3 else tth_monthly_hires
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

        forecast_vs_target = {
            'current_target': total_target,
            'current_hired': hired_count,
            'monthly_target': round(total_target / 3, 1) if total_target else 0,
            'next_labels': forecast_labels,
            'projected_hires': projected_hires,
            'expected_gap_next_month': round(max((total_target / 3) - avg_recent_hires, 0), 1) if total_target else 0,
            'projection_basis': 'Average hires from last 3 months',
        }

        # Phase 3: anomaly flags
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

        return JsonResponse({
            'Success': True,
            'Error': None,
            'Data': {
                'summary': {
                    'total_interviews': total_interviews,
                    'hires': hired_count,
                    'hire_rate': round((hired_count / total_interviews) * 100) if total_interviews else 0,
                    'open_roles': open_roles_count,
                    'avg_time_to_hire_days': round(sum(tth_days) / len(tth_days), 1) if tth_days else 0,
                    'median_time_to_hire_days': round(median(tth_days), 1) if tth_days else 0,
                },
                'funnel': {
                    'labels': funnel_labels,
                    'values': funnel_values,
                    'conversions': conversions,
                },
                'time_to_hire': {
                    'avg_days': round(sum(tth_days) / len(tth_days), 1) if tth_days else 0,
                    'median_days': round(median(tth_days), 1) if tth_days else 0,
                    'monthly_labels': tth_labels,
                    'monthly_avg_days': tth_monthly_avg,
                    'monthly_hires': tth_monthly_hires,
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
                }
            }
        })
    except Exception as e:
        return JsonResponse({'Success': False, 'Error': str(e), 'Data': {}})
