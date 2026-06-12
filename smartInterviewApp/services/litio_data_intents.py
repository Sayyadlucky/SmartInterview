from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re

from django.contrib.auth.models import User
from django.utils import timezone

from smartInterviewApp.models import (
    Interview,
    AptitudeTestResult,
    AptitudeTestAssignment,
    AptitudeTestResult,
    AutoInterviewEvaluationResult,
    CandidateInsightSnapshot,
    Vacancies,
)
from django.db import DatabaseError, transaction


@dataclass
class LitioDataIntentResult:
    handled: bool
    answer: str = ""
    intent_key: str = ""
    needs_clarification: bool = False
    clarification: str = ""


def _get_company_for_user(user: User):
    try:
        return getattr(user.profile, 'company', None)
    except Exception:
        return None


def _find_candidate_by_name_or_id(user: User, name: str | None = None, candidate_id: int | None = None):
    from django.contrib.auth.models import User as DjangoUser

    qs = DjangoUser.objects.filter(profile__role='candidate')
    company = _get_company_for_user(user)
    if company and not getattr(user, 'is_staff', False):
        qs = qs.filter(profile__company=company)

    if candidate_id:
        return qs.filter(id=candidate_id).first(), None

    if not name:
        return None, None

    parts = name.strip().split()
    # simple match: first or last or username contains
    candidates = qs.filter(
        first_name__icontains=name
    ) | qs.filter(last_name__icontains=name) | qs.filter(username__icontains=name)
    candidates = candidates.distinct()
    matches = list(candidates[:10])
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        clar = 'Multiple candidates matched: ' + ', '.join([f'{u.first_name} {u.last_name}'.strip() or u.username for u in matches[:5]])
        return None, clar
    return None, None


def _latest_candidate_score_summary(user: User, candidate: User):
    # Search latest among aptitude result, auto interview evaluation, interview.score, insight snapshot
    latest_item = None
    latest_time = None
    summary = None

    # AptitudeTestResult via assignment (optional; tolerant of missing schema)
    try:
        with transaction.atomic():
            apt_result = (
                AptitudeTestResult.objects
                .filter(assignment__candidate=candidate)
                .order_by('-updated_at')
                .first()
            )
    except DatabaseError:
        apt_result = None
    if apt_result:
        latest_item = ('aptitude', apt_result)
        latest_time = apt_result.updated_at

    # Auto interview evaluation
    try:
        with transaction.atomic():
            auto_eval = (
                AutoInterviewEvaluationResult.objects
                .filter(interview__candidate=candidate)
                .order_by('-updated_at')
                .first()
            )
    except DatabaseError:
        auto_eval = None
    if auto_eval and (latest_time is None or auto_eval.updated_at and auto_eval.updated_at > latest_time):
        latest_item = ('auto_interview', auto_eval)
        latest_time = auto_eval.updated_at

    # Interview score
    interview_score = (
        Interview.objects
        .filter(candidate=candidate, score__isnull=False)
        .order_by('-date')
        .first()
    )
    if interview_score and (latest_time is None or interview_score.date and interview_score.date > latest_time):
        latest_item = ('interview', interview_score)
        latest_time = interview_score.date

    # Candidate insight snapshot
    try:
        insight = candidate.insight_snapshot
    except Exception:
        insight = None
    if insight and (latest_time is None or insight.updated_at and insight.updated_at > latest_time):
        latest_item = ('insight', insight)
        latest_time = insight.updated_at

    if not latest_item:
        return None

    typ, obj = latest_item
    name = f"{candidate.first_name} {candidate.last_name or ''}".strip()
    if typ == 'aptitude':
        pct = float(obj.score_percent)
        date = obj.updated_at.date().isoformat() if obj.updated_at else None
        role = None
        try:
            role = obj.assignment.vacancy.role if getattr(obj.assignment, 'vacancy', None) else (obj.assignment.interview.role.role if getattr(obj.assignment, 'interview', None) and getattr(obj.assignment.interview, 'role', None) else None)
        except Exception:
            role = None
        return f"{name}'s latest aptitude score is {pct}% for {role or 'N/A'}{', completed on ' + date if date else ''}. Recommendation: {'Pass' if getattr(obj, 'passed', False) else 'Review'}. Use the report evidence before making the final hiring decision."

    if typ == 'auto_interview':
        score = obj.score
        date = obj.updated_at.date().isoformat() if obj.updated_at else None
        role = None
        try:
            role = obj.interview.role.role if getattr(obj, 'interview', None) and getattr(obj.interview, 'role', None) else None
        except Exception:
            role = None
        rec = getattr(obj, 'recommendation', None) or getattr(obj, 'decision', None) or ''
        return f"{name}'s latest auto-interview score is {score} for {role or 'N/A'}{', completed on ' + date if date else ''}. Recommendation: {rec or 'See report'}. Use the report evidence before making the final hiring decision."

    if typ == 'interview':
        score = obj.score
        date = obj.date.date().isoformat() if getattr(obj, 'date', None) else None
        role = obj.role.role if getattr(obj, 'role', None) else None
        return f"{name}'s interview score is {score} for {role or 'N/A'}{', on ' + date if date else ''}. Use the report evidence before making the final hiring decision."

    if typ == 'insight':
        rs = getattr(obj, 'resume_score', None)
        rf = getattr(obj, 'role_fit_score', None)
        date = obj.updated_at.date().isoformat() if obj.updated_at else None
        parts = []
        if rs is not None:
            parts.append(f"resume score {rs}")
        if rf is not None:
            parts.append(f"role fit score {rf}")
        if not parts:
            return None
        return f"{name} has {', '.join(parts)}{', updated on ' + date if date else ''}. Use the report evidence before making the final hiring decision."


def _handle_latest_candidate_score(user: User, question: str, context: dict | None):
    # Extract candidate id from context or name from question
    candidate_id = None
    candidate_name = None
    if context:
        candidate_id = context.get('candidateId') or context.get('candidate_id') or context.get('candidateId')
    # Try to parse name in question: heuristic: words after 'of' or between 'score of' and 'in'
    m = re.search(r"score of ([A-Za-z\s]+)|score for ([A-Za-z\s]+)|latest evaluation for ([A-Za-z\s]+)", question, re.I)
    if m:
        candidate_name = next((g for g in m.groups() if g), None)
    # Fallback: pick capitalized tokens (simple name heuristic)
    if not candidate_name:
        caps = re.findall(r"\b[A-Z][a-z]{1,}\b", question)
        caps_filtered = [t for t in caps if t.lower() not in {'what', 'how', 'show', 'which', 'who', 'when', 'is', 'this', 'the', 'what\'s'}]
        if caps_filtered:
            candidate_name = ' '.join(caps_filtered[:2])

    candidate, clar = _find_candidate_by_name_or_id(user, name=candidate_name, candidate_id=candidate_id)
    if clar:
        return LitioDataIntentResult(True, needs_clarification=True, clarification=clar)
    if not candidate:
        return LitioDataIntentResult(False)

    summary = _latest_candidate_score_summary(user, candidate)
    if not summary:
        return LitioDataIntentResult(True, answer=f"I found the candidate, but I could not find a completed evaluation or test score yet.", intent_key='data_latest_candidate_score')
    return LitioDataIntentResult(True, answer=summary, intent_key='data_latest_candidate_score')


def _handle_pending_interviews(user: User, question: str, context: dict | None):
    now = timezone.now()
    company = _get_company_for_user(user)
    qs = Interview.objects.filter(status='scheduled')
    if company and not getattr(user, 'is_staff', False):
        qs = qs.filter(role__company=company)

    # date filters
    if re.search(r'\btoday\b', question, re.I):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        qs = qs.filter(date__gte=start, date__lt=end)
    if re.search(r'\bthis week\b|\bweek\b', question, re.I):
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        qs = qs.filter(date__gte=start, date__lt=end)
    if re.search(r'\boverdue\b|\bmissed\b', question, re.I):
        qs = qs.filter(date__lt=now)

    total = qs.count()
    today_count = 0
    try:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        today_count = qs.filter(date__gte=start, date__lt=end).count()
    except Exception:
        today_count = 0

    answer = f"You currently have {total} pending interviews."
    if today_count:
        answer += f" {today_count} are scheduled for today." 
    return LitioDataIntentResult(True, answer=answer, intent_key='data_pending_interviews')


def _handle_recruiter_performance(user: User, question: str, context: dict | None):
    # try to extract recruiter name
    m = re.search(r'recruiter\s+([A-Za-z\s]+)', question, re.I)
    recruiter_name = None
    if m:
        recruiter_name = m.group(1).strip().split()[0]
    if not recruiter_name:
        caps = re.findall(r"\b[A-Z][a-z]{1,}\b", question)
        caps_filtered = [t for t in caps if t.lower() not in {'what', 'how', 'show', 'which', 'who', 'when', 'is', 'this', 'the'}]
        if caps_filtered:
            recruiter_name = caps_filtered[0]

    from django.contrib.auth.models import User as DjangoUser
    qs = DjangoUser.objects.filter(profile__role='recruiter')
    company = _get_company_for_user(user)
    if company and not getattr(user, 'is_staff', False):
        qs = qs.filter(profile__company=company)

    if recruiter_name:
        matches = qs.filter(first_name__icontains=recruiter_name) | qs.filter(last_name__icontains=recruiter_name) | qs.filter(username__icontains=recruiter_name)
        matches = matches.distinct()
        matches_list = list(matches[:10])
        if len(matches_list) == 0:
            return LitioDataIntentResult(False)
        if len(matches_list) > 1:
            clar = 'Multiple recruiters matched: ' + ', '.join([f"{u.first_name} {u.last_name}".strip() or u.username for u in matches_list[:5]])
            return LitioDataIntentResult(True, needs_clarification=True, clarification=clar)
        recruiter = matches_list[0]
    else:
        # No recruiter specified: provide overall activity summary if safe
        recruiter = None

    # default range: last 7 days
    now = timezone.now()
    start = now - timedelta(days=7)

    if recruiter:
        interviews_scheduled = Interview.objects.filter(recruiter=recruiter, date__gte=start).count()
        interviews_completed = Interview.objects.filter(recruiter=recruiter, status='completed', date__gte=start).count()
        unique_candidates = Interview.objects.filter(recruiter=recruiter, date__gte=start).values_list('candidate', flat=True).distinct().count()
        pending = Interview.objects.filter(recruiter=recruiter, status='scheduled').count()
        answer = (
            f"Recruiter {recruiter.first_name} {recruiter.last_name or ''} handled {unique_candidates} candidates in the last 7 days, "
            f"scheduled {interviews_scheduled} interviews, and has {pending} pending interviews. This is an activity summary, not a performance rating."
        )
        return LitioDataIntentResult(True, answer=answer, intent_key='data_recruiter_performance')

    # overall summary
    interviews_scheduled = Interview.objects.filter(date__gte=start).count()
    interviews_completed = Interview.objects.filter(status='completed', date__gte=start).count()
    answer = f"Across recruiters in the last 7 days: {interviews_scheduled} interviews scheduled and {interviews_completed} completed."
    return LitioDataIntentResult(True, answer=answer, intent_key='data_recruiter_performance')


def answer_data_question(user: User | None, question: str, context: dict | None = None) -> LitioDataIntentResult:
    """Detect and answer simple safe data intents. Returns handled=False if not matched.

    Uses ORM only and filters by `user.profile.company` when available (non-staff users).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return LitioDataIntentResult(False)

    q = (question or '').strip()
    if not q:
        return LitioDataIntentResult(False)

    # Protected/internal queries should be handled elsewhere; keep this conservative.
    if re.search(r'api\s*key|openai|what model|which model|provider', q, re.I):
        return LitioDataIntentResult(False)

    # Candidate latest score intent
    if re.search(r'\bscore\b|evaluation|test score|aptitude', q, re.I):
        # Quick heuristic: try to find a candidate token in the question (first name)
        tokens = re.findall(r"\b[A-Za-z]{2,}\b", q)
        stop = {'what', 'is', 'the', 'show', 'how', 'many', 'this', 'last', 'latest', 'in', 'of', 'on', 'for', 'score', 'evaluation', 'test'}
        for t in tokens:
            if t.lower() in stop:
                continue
            cand, clar = _find_candidate_by_name_or_id(user, name=t)
            if cand:
                summary = _latest_candidate_score_summary(user, cand)
                if summary:
                    return LitioDataIntentResult(True, answer=summary, intent_key='data_latest_candidate_score')
        return _handle_latest_candidate_score(user, q, context)

    # Pending interviews intent
    if re.search(r'pending interviews|how many interviews|scheduled interviews|pending today|pending this week|pending', q, re.I):
        return _handle_pending_interviews(user, q, context)

    # Recruiter performance
    if re.search(r'\brecruiter\b|recruiter performance|recruiter activity|how is recruiter', q, re.I):
        return _handle_recruiter_performance(user, q, context)

    return LitioDataIntentResult(False)
