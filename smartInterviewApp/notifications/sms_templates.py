from __future__ import annotations

from typing import Any


def build_sms_message(event_type: str, context: dict[str, Any] | None = None) -> str:
    data = context or {}
    event_key = (event_type or '').strip().lower()

    if event_key == 'candidate_interview_created':
        candidate_name = data.get('candidate_name') or 'Candidate'
        role_name = data.get('role_name') or 'the role'
        recruiter_name = data.get('recruiter_name') or 'our team'
        return (
            f"Hello {candidate_name},\n\n"
            f"Your profile has been added for the {role_name} role on Shortlistii.com.\n\n"
            f"Our recruiter {recruiter_name} will connect with you shortly regarding the interview process and next steps.\n\n"
            f"Please keep an eye on your phone and email for further updates.\n\n"
            f"Regards,\n"
            f"Team Shortlistii.com"
        )

    if event_key == 'candidate_signup_invite':
        candidate_name = data.get('candidate_name') or 'Candidate'
        role_name = data.get('role_name') or 'the role'
        signup_url = data.get('signup_url') or ''
        return (
            f"Hello {candidate_name},\n\n"
            f"You have been shortlisted for the {role_name} opportunity through Shortlistii.com.\n\n"
            f"To continue, please complete your candidate profile using the secure link below:\n"
            f"{signup_url}\n\n"
            f"Once your profile is completed, you can set your password, upload your resume, and proceed with the next steps in the hiring process.\n\n"
            f"Thank you,\n"
            f"Team Shortlistii.com"
        ).strip()

    if event_key == 'candidate_vacancy_application':
        candidate_name = data.get('candidate_name') or 'A candidate'
        vacancy_role = data.get('vacancy_role') or 'the open role'
        return (
            f"Candidate application alert: {candidate_name} applied for {vacancy_role}. "
            f"Please review the candidate profile and decide the next hiring step."
        )

    if event_key == 'interview_reminder':
        subject = data.get('subject') or 'Interview reminder'
        starts_at = data.get('starts_at') or data.get('time') or ''
        extra = f" at {starts_at}" if starts_at else ''
        return f"{subject}{extra}."

    if event_key == 'critical_outage':
        incident = data.get('incident_name') or 'Critical alert'
        action = data.get('action') or 'Check the dashboard immediately'
        return f"{incident}. {action}."

    return str(
        data.get('sms_message')
        or data.get('message')
        or f"Alert: {event_type}"
    )
