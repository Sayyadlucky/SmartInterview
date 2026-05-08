from __future__ import annotations

import logging
from email.mime.image import MIMEImage
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from smartInterviewApp.models import Interview, UserProfile
from smartInterviewApp.templatetags.host_links import build_host_link


logger = logging.getLogger(__name__)
DEFAULT_SUPPORT_EMAIL = 'support@shortlistii.com'
DEFAULT_FROM_EMAIL = 'no-reply@shortlistii.com'
WELCOME_EMAIL_LOGO_CID = 'shortlistii-company-logo'


def get_support_email() -> str:
    return getattr(settings, 'CONTACT_SUPPORT_EMAIL', DEFAULT_SUPPORT_EMAIL)


def get_default_from_email() -> str:
    return getattr(settings, 'DEFAULT_FROM_EMAIL', None) or DEFAULT_FROM_EMAIL


def _welcome_recipient_name(user: User) -> str:
    name = (user.first_name or '').strip()
    if name:
        return name
    full_name = f"{user.first_name} {user.last_name}".strip()
    if full_name:
        return full_name
    return 'there'


def _build_home_url(request) -> str:
    if request is not None:
        return build_host_link(request, 'home')
    return getattr(settings, 'MARKETING_HOME_URL', 'https://shortlistii.com').rstrip('/') or 'https://shortlistii.com'


def _brand_logo_path() -> Path:
    return Path(settings.BASE_DIR) / 'smartInterviewApp' / 'static' / 'smartInterview' / 'company-logo.png'


def build_email_base_context(request, **extra_context) -> dict[str, object]:
    context: dict[str, object] = {
        'brand_name': 'Shortlistii',
        'brand_home_url': _build_home_url(request),
        'brand_logo_src': f'cid:{WELCOME_EMAIL_LOGO_CID}' if _brand_logo_path().exists() else '',
        'support_email': get_support_email(),
        'sent_by_note': 'Sent by Shortlistii',
        'footer_note': 'Shortlistii handles candidate communication, interview coordination, and recruiting operations with a calm, production-grade workflow.',
    }
    context.update(extra_context)
    return context


def _format_interview_datetime(value) -> tuple[str, str, str]:
    if not value:
        return '', '', timezone.get_current_timezone_name()
    localized = timezone.localtime(value)
    return (
        localized.strftime('%d %b %Y'),
        localized.strftime('%I:%M %p'),
        timezone.get_current_timezone_name(),
    )


def build_candidate_welcome_email_context(
    request,
    user: User,
    profile: UserProfile | None,
    interview: Interview | None = None,
) -> dict[str, object]:
    recipient_name = _welcome_recipient_name(user)
    role_name = ''
    if interview and interview.role:
        role_name = (interview.role.role or '').strip()
    verify_next = f"{reverse('candidate-dashboard')}?verify=email&send_otp=1"

    return build_email_base_context(
        request,
        recipient_name=recipient_name,
        full_name=f"{user.first_name} {user.last_name}".strip() or recipient_name,
        role_name=role_name,
        candidate_portal_url=build_host_link(request, 'candidates'),
        candidate_login_url=build_host_link(request, 'candidate_login'),
        email_verification_url=f"{build_host_link(request, 'candidate_login')}?next={quote(verify_next, safe='/?:=&')}",
        jobs_url=build_host_link(request, 'jobs'),
    )


def _attach_brand_logo(message: EmailMultiAlternatives) -> None:
    logo_path = _brand_logo_path()
    if not logo_path.exists():
        return

    with logo_path.open('rb') as logo_file:
        logo = MIMEImage(logo_file.read(), _subtype='png')

    logo.add_header('Content-ID', f'<{WELCOME_EMAIL_LOGO_CID}>')
    logo.add_header('Content-Disposition', 'inline', filename='company-logo.png')
    message.attach(logo)


def send_templated_email(
    *,
    subject: str,
    template_name: str,
    context: dict[str, object],
    to: Iterable[str],
    reply_to: Iterable[str] | None = None,
    from_email: str | None = None,
    attach_brand_logo: bool = True,
    raise_on_failure: bool = True,
) -> bool:
    recipients = [str(address or '').strip() for address in to if str(address or '').strip()]
    if not recipients:
        return False

    text_body = render_to_string(f'{template_name}.txt', context).strip()
    html_body = render_to_string(f'{template_name}.html', context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or get_default_from_email(),
        to=recipients,
        reply_to=[str(address or '').strip() for address in (reply_to or []) if str(address or '').strip()],
    )
    message.attach_alternative(html_body, 'text/html')
    if attach_brand_logo:
        _attach_brand_logo(message)

    try:
        message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception(
            'Failed to send templated email template=%s subject=%s to=%s',
            template_name,
            subject,
            recipients,
        )
        if raise_on_failure:
            raise
        return False


def send_contact_notification_email(
    request,
    *,
    cleaned_data: dict[str, str],
    inquiry_label: str,
    company_name: str,
    inbox_email: str,
    subject: str,
) -> bool:
    sender_name = ' '.join((cleaned_data.get('full_name') or '').split()).strip() or 'Website visitor'
    sender_email = ' '.join((cleaned_data.get('work_email') or '').split()).strip()
    team_size_label = cleaned_data.get('team_size_label') or 'Not provided'
    phone_number = ' '.join((cleaned_data.get('phone_number') or '').split()).strip() or 'Not provided'
    message_body = (cleaned_data.get('message') or '').strip()
    reply_email = sender_email or None

    context = build_email_base_context(
        request,
        email_badge='Team notification',
        email_header_kicker='Inbound contact',
        sender_name=sender_name,
        sender_email=sender_email or 'Not provided',
        inquiry_label=inquiry_label,
        company_name=company_name or 'Unknown company',
        subject_line=subject,
        message_body=message_body,
        details_title='Contact details',
        details=[
            {'label': 'Sender', 'value': sender_name},
            {'label': 'Email', 'value': sender_email or 'Not provided'},
            {'label': 'Company', 'value': company_name or 'Unknown company'},
            {'label': 'Phone', 'value': phone_number},
            {'label': 'Team size', 'value': team_size_label},
            {'label': 'Inquiry', 'value': inquiry_label},
            {'label': 'Subject', 'value': subject},
        ],
        button_label='Reply to sender' if reply_email else '',
        button_url=f'mailto:{reply_email}' if reply_email else '',
    )
    return send_templated_email(
        subject=subject,
        template_name='smartInterview/emails/contact_notification',
        context=context,
        to=[inbox_email],
        reply_to=[reply_email] if reply_email else None,
    )


def build_candidate_interview_email_context(
    request,
    candidate: User,
    interview: Interview,
    interview_link: str,
    *,
    notification_kind: str = 'scheduled',
    previous_scheduled_at=None,
) -> dict[str, object]:
    role_name = (interview.role.role or '').strip() if interview.role else 'your interview'
    recruiter_name = f"{interview.recruiter.first_name} {interview.recruiter.last_name}".strip().title() if interview.recruiter else 'Hiring Team'
    interviewer_name = f"{interview.interviewer.first_name} {interview.interviewer.last_name}".strip().title() if interview.interviewer else 'Assigned Team'
    interview_date, interview_time, timezone_label = _format_interview_datetime(interview.date)
    previous_date, previous_time, _previous_timezone = _format_interview_datetime(previous_scheduled_at)
    is_rescheduled = notification_kind == 'rescheduled'

    details = [
        {'label': 'Role', 'value': role_name},
        {'label': 'Date', 'value': interview_date or 'To be confirmed'},
        {'label': 'Time', 'value': f"{interview_time} ({timezone_label})" if interview_time else 'To be confirmed'},
        {'label': 'Interview type', 'value': 'Manual Interview' if getattr(interview, 'interview_type', 'manual') == 'manual' else 'AI Interview'},
        {'label': 'Recruiter', 'value': recruiter_name},
        {'label': 'Interviewer', 'value': interviewer_name},
    ]
    if is_rescheduled and previous_date and previous_time:
        details.append({'label': 'Previous schedule', 'value': f'{previous_date} at {previous_time}'})

    return build_email_base_context(
        request,
        recipient_name=_welcome_recipient_name(candidate),
        is_rescheduled=is_rescheduled,
        role_name=role_name,
        recruiter_name=recruiter_name,
        interviewer_name=interviewer_name,
        interview_type_label='Manual Interview' if getattr(interview, 'interview_type', 'manual') == 'manual' else 'AI Interview',
        interview_date=interview_date,
        interview_time=interview_time,
        timezone_label=timezone_label,
        previous_interview_date=previous_date,
        previous_interview_time=previous_time,
        interview_link=interview_link,
        details_title='Interview details',
        details=details,
        button_label='Open Interview Link',
        button_url=interview_link,
    )


def send_candidate_interview_email(
    request,
    candidate: User,
    interview: Interview,
    interview_link: str,
    *,
    notification_kind: str = 'scheduled',
    previous_scheduled_at=None,
) -> dict[str, str | bool]:
    recipient = (candidate.email or '').strip().lower()
    if not recipient:
        return {'sent': False, 'reason': 'Candidate email address is missing.', 'subject': ''}

    context = build_candidate_interview_email_context(
        request,
        candidate,
        interview,
        interview_link,
        notification_kind=notification_kind,
        previous_scheduled_at=previous_scheduled_at,
    )
    subject_prefix = 'Interview Rescheduled' if notification_kind == 'rescheduled' else 'Interview Scheduled'
    subject = f"{subject_prefix}: {context['role_name']} | Shortlistii"

    sent = send_templated_email(
        subject=subject,
        template_name='smartInterview/emails/interview_scheduled',
        context=context,
        to=[recipient],
        raise_on_failure=False,
    )
    return {'sent': sent, 'reason': '' if sent else 'Email delivery failed.', 'subject': subject}


def send_candidate_welcome_email(
    request,
    user: User,
    profile: UserProfile | None,
    interview: Interview | None = None,
) -> bool:
    recipient = (user.email or '').strip().lower()
    if not recipient:
        return False

    context = build_candidate_welcome_email_context(request, user, profile, interview=interview)
    subject = 'Welcome to Shortlistii'
    if context['role_name']:
        subject = f"Welcome to Shortlistii, your {context['role_name']} profile is ready"

    context.update({
        'email_badge': 'Candidate account ready',
        'email_header_kicker': 'Candidate onboarding',
        'button_label': 'Open Candidate Portal',
        'button_url': context['candidate_portal_url'],
        'next_steps': [
            'Complete your profile details.',
            'Upload or refresh your resume.',
            'Verify your email before your next interview step.',
        ],
    })
    return send_templated_email(
        subject=subject,
        template_name='smartInterview/emails/candidate_welcome',
        context=context,
        to=[recipient],
        raise_on_failure=False,
    )


def send_email_otp_notification(
    *,
    to_email: str,
    otp: str,
    expires_in_minutes: int,
    raise_on_failure: bool = True,
) -> bool:
    recipient = str(to_email or '').strip().lower()
    if not recipient:
        return False

    context = build_email_base_context(
        request=None,
        email_badge='Verification code',
        email_header_kicker='Account security',
        headline='Confirm your email address',
        recipient_name=recipient,
        intro='Use the verification code below to confirm your Shortlistii email address.',
        body_copy='Enter this code in the verification screen. For your security, do not share it with anyone.',
        details_title='Verification details',
        details=[
            {'label': 'Verification code', 'value': otp},
            {'label': 'Expires in', 'value': f'{max(1, expires_in_minutes)} minutes'},
        ],
    )
    return send_templated_email(
        subject='Shortlistii email verification code',
        template_name='smartInterview/emails/generic_notification',
        context=context,
        to=[recipient],
        raise_on_failure=raise_on_failure,
    )
