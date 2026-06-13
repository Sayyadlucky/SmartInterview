from __future__ import annotations

from dataclasses import dataclass, field
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
from smartInterviewApp.models import CandidateVacancyApplication, RecruiterNote, Notification
from django.db import DatabaseError, transaction


@dataclass
class LitioAssistantAction:
    label: str
    action_type: str
    route: str = ""
    query_params: dict | None = None
    entity_type: str = ""
    entity_id: int | str | None = None
    payload: dict | None = None


@dataclass
class LitioDataIntentResult:
    handled: bool
    answer: str = ""
    intent_key: str = ""
    needs_clarification: bool = False
    clarification: str = ""
    actions: list[LitioAssistantAction] = field(default_factory=list)


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
    # include an action to open the candidate in the dashboard
    actions: list[LitioAssistantAction] = []
    try:
        actions.append(LitioAssistantAction(
            label=f"Open candidate: {candidate.first_name or candidate.username}",
            action_type='open_candidate',
            route='/dashboard',
            entity_type='candidate',
            entity_id=candidate.id,
            query_params={'candidateId': candidate.id},
        ))
    except Exception:
        actions = []
    return LitioDataIntentResult(True, answer=summary, intent_key='data_latest_candidate_score', actions=actions)


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
    actions: list[LitioAssistantAction] = []
    try:
        actions.append(LitioAssistantAction(
            label='View pending interviews',
            action_type='navigate',
            route='/dashboard',
            query_params={'section': 'interviews', 'filter': 'pending'},
        ))
        if today_count:
            actions.append(LitioAssistantAction(
                label="View today's interviews",
                action_type='navigate',
                route='/dashboard',
                query_params={'section': 'interviews', 'filter': 'today'},
            ))
        if total and total - today_count > 0:
            # overdue if any scheduled before now
            overdue = qs.filter(date__lt=timezone.now()).count()
            if overdue:
                actions.append(LitioAssistantAction(
                    label='View overdue interviews',
                    action_type='navigate',
                    route='/dashboard',
                    query_params={'section': 'interviews', 'filter': 'overdue'},
                ))
    except Exception:
        actions = []
    return LitioDataIntentResult(True, answer=answer, intent_key='data_pending_interviews', actions=actions)


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
        # include safe navigation actions for recruiter drill-down
        actions: list[LitioAssistantAction] = []
        try:
            actions.append(LitioAssistantAction(
                label=f"View recruiter activity",
                action_type='open_recruiter_activity',
                route='/dashboard',
                query_params={'section': 'recruiters', 'filter': 'activity', 'recruiterId': recruiter.id},
            ))
            actions.append(LitioAssistantAction(
                label="View recruiter's pending interviews",
                action_type='open_interviews',
                route='/dashboard',
                query_params={'section': 'interviews', 'filter': 'pending', 'recruiterId': recruiter.id},
            ))
        except Exception:
            actions = []
        return LitioDataIntentResult(True, answer=answer, intent_key='data_recruiter_performance', actions=actions)

    # overall summary
    interviews_scheduled = Interview.objects.filter(date__gte=start).count()
    interviews_completed = Interview.objects.filter(status='completed', date__gte=start).count()
    answer = f"Across recruiters in the last 7 days: {interviews_scheduled} interviews scheduled and {interviews_completed} completed."
    # add a conservative action to view overall recruiter activity
    actions: list[LitioAssistantAction] = []
    try:
        actions.append(LitioAssistantAction(
            label='View recruiter activity',
            action_type='open_recruiter_activity',
            route='/dashboard',
            query_params={'section': 'recruiters', 'filter': 'activity'},
        ))
    except Exception:
        actions = []
    return LitioDataIntentResult(True, answer=answer, intent_key='data_recruiter_performance', actions=actions)


def _handle_sla_breaches(user: User, question: str, context: dict | None):
    """Identify applications pending recruiter action beyond a safe default review window.

    Default rule: application is considered pending action if `status` is Pending Review
    and its latest status timestamp (reviewed_at, hiring_started_at, updated_at, applied_at)
    is older than 48 hours. This is an operational signal, not an official SLA breach.
    """
    company = _get_company_for_user(user)
    qs = CandidateVacancyApplication.objects.filter(status=CandidateVacancyApplication.Status.PENDING_REVIEW)
    if company and not getattr(user, 'is_staff', False):
        qs = qs.filter(vacancy__company=company)

    now = timezone.now()
    # threshold: 48 hours
    threshold = timedelta(hours=48)
    stale = []
    for app in qs.select_related('candidate', 'vacancy')[:500]:
        ts = app.reviewed_at or app.hiring_started_at or app.updated_at or app.applied_at
        if not ts:
            continue
        if now - ts > threshold:
            age_days = (now - ts).days
            stale.append((app, age_days))

    if not stale:
        # If no items or timestamps missing, be careful
        if qs.exists():
            return LitioDataIntentResult(True, answer=("There are applications with status 'Pending Review' but many lack status timestamps; "
                                                       "I can report SLA-like breaches once review/hiring timestamps are available."), intent_key='data_sla_breaches')
        return LitioDataIntentResult(True, answer="I do not see pending applications beyond the 48-hour review window.", intent_key='data_sla_breaches')

    total = len(stale)
    stale_sorted = sorted(stale, key=lambda x: -x[1])
    top = stale_sorted[:5]
    items = ', '.join([f"{s[0].candidate.first_name or s[0].candidate.username} ({s[1]} days)" for s in top])
    oldest = stale_sorted[0][1]
    answer = (f"You currently have {total} candidates that appear to be pending action beyond the 48-hour review window. "
              f"The oldest pending item is {oldest} days old. Treat this as an operational follow-up signal. Top items: {items}.")
    actions: list[LitioAssistantAction] = []
    try:
        actions.append(LitioAssistantAction(
            label='View SLA breached candidates',
            action_type='navigate',
            route='/dashboard',
            query_params={'section': 'candidates', 'filter': 'sla_breached'},
        ))
        # add top candidate open action
        if top:
            top_app = top[0][0]
            cand = getattr(top_app, 'candidate', None)
            if cand:
                actions.append(LitioAssistantAction(
                    label=f"Open candidate: {cand.first_name or cand.username}",
                    action_type='open_candidate',
                    route='/dashboard',
                    entity_type='candidate',
                    entity_id=cand.id,
                    query_params={'candidateId': cand.id},
                ))
    except Exception:
        actions = []
    return LitioDataIntentResult(True, answer=answer, intent_key='data_sla_breaches', actions=actions)


def _handle_pipeline_health(user: User, question: str, context: dict | None):
    company = _get_company_for_user(user)
    qs = Vacancies.objects.filter(status='active')
    if company and not getattr(user, 'is_staff', False):
        qs = qs.filter(company=company)

    # compute simple metrics
    roles = []
    for v in qs.select_related('company'):
        apps_count = v.candidate_applications.count()
        interviews_count = v.interviews.count()
        # last activity: latest application or interview
        last_app = v.candidate_applications.order_by('-updated_at').first()
        last_interview = v.interviews.order_by('-date').first()
        last_ts = None
        if last_app and last_app.updated_at:
            last_ts = last_app.updated_at
        if last_interview and getattr(last_interview, 'date', None):
            if not last_ts or last_interview.date > last_ts:
                last_ts = last_interview.date
        roles.append((v, apps_count, interviews_count, last_ts))

    if not roles:
        return LitioDataIntentResult(True, answer="No active vacancies found for your scope.", intent_key='data_pipeline_health')

    zero_candidate = [r for r in roles if r[1] == 0]
    no_interview = [r for r in roles if r[1] > 0 and r[2] == 0]
    inactive = []
    from django.utils import timezone as _tz
    now = _tz.now()
    for r in roles:
        last = r[3]
        if not last or (now - last).days >= 7:
            inactive.append(r)

    parts = []
    if zero_candidate:
        sample = ', '.join([f"{r[0].role}" for r in zero_candidate[:5]])
        parts.append(f"{len(zero_candidate)} open roles have zero candidates (e.g. {sample})")
    if no_interview:
        sample = ', '.join([f"{r[0].role} ({r[1]} candidates)" for r in no_interview[:5]])
        parts.append(f"{len(no_interview)} roles have candidates but no scheduled interviews (e.g. {sample})")
    if inactive:
        sample = ', '.join([f"{r[0].role}" for r in inactive[:5]])
        parts.append(f"{len(inactive)} roles with no activity in 7+ days (e.g. {sample})")

    answer = "Based on available vacancy, application and interview counts: " + '; '.join(parts)
    actions: list[LitioAssistantAction] = []
    try:
        actions.append(LitioAssistantAction(
            label='Open pipeline health',
            action_type='navigate',
            route='/dashboard',
            query_params={'section': 'pipeline'},
        ))
        if zero_candidate or no_interview or inactive:
            actions.append(LitioAssistantAction(
                label='View roles needing attention',
                action_type='navigate',
                route='/dashboard',
                query_params={'section': 'pipeline', 'filter': 'needs_attention'},
            ))
        # optionally include top vacancy open action
        if no_interview:
            v = no_interview[0][0]
            if getattr(v, 'id', None):
                actions.append(LitioAssistantAction(
                    label=f"Open role: {v.role}",
                    action_type='open_vacancy',
                    route='/dashboard',
                    entity_type='vacancy',
                    entity_id=v.id,
                    query_params={'vacancyId': v.id},
                ))
    except Exception:
        actions = []
    return LitioDataIntentResult(True, answer=answer, intent_key='data_pipeline_health', actions=actions)


def _handle_aptitude_analytics(user: User, question: str, context: dict | None):
    company = _get_company_for_user(user)
    # optional role filter
    role_filter = None
    m = re.search(r'for ([A-Za-z\s]+)$', question.strip(), re.I)
    if m:
        role_filter = m.group(1).strip()

    results_qs = AptitudeTestResult.objects.all()
    if role_filter:
        # try to filter by vacancy role title via assignment
        results_qs = results_qs.filter(assignment__vacancy__role__icontains=role_filter)
    if company and not getattr(user, 'is_staff', False):
        results_qs = results_qs.filter(assignment__vacancy__company=company)

    try:
        total = results_qs.count()
    except Exception:
        return LitioDataIntentResult(True, answer="Aptitude analytics are not available in this environment.", intent_key='data_aptitude_analytics')
    if total == 0:
        return LitioDataIntentResult(True, answer="I could not find completed aptitude results for the requested scope.", intent_key='data_aptitude_analytics')

    passed = results_qs.filter(passed=True).count()
    failed = results_qs.filter(passed=False).count()
    avg = None
    try:
        from django.db.models import Avg
        avg = float(results_qs.aggregate(avg=Avg('score_percent'))['avg'] or 0)
    except Exception:
        avg = None

    top = []
    try:
        top_qs = results_qs.select_related('assignment__candidate').order_by('-score_percent')[:5]
        for r in top_qs:
            cand = getattr(r.assignment, 'candidate', None)
            if cand:
                top.append(f"{cand.first_name or cand.username} ({float(r.score_percent)}%)")
    except Exception:
        top = []

    answer = f"{total} candidates have completed aptitude tests. {passed} passed and {failed} did not pass. "
    if avg is not None:
        answer += f"The average score is {round(avg, 1)}%. "
    if top:
        answer += "Top scorers: " + ', '.join(top[:5]) + "."
    actions: list[LitioAssistantAction] = []
    try:
        actions.append(LitioAssistantAction(
            label='Open aptitude results',
            action_type='navigate',
            route='/dashboard',
            query_params={'section': 'aptitude'},
        ))
        if passed:
            actions.append(LitioAssistantAction(
                label='View passed candidates',
                action_type='navigate',
                route='/dashboard',
                query_params={'section': 'aptitude', 'filter': 'passed'},
            ))
        if top:
            # use first top candidate if available
            # best-effort: try to get candidate id
            try:
                first_r = top_qs[0]
                cand = getattr(first_r.assignment, 'candidate', None)
                if cand:
                    actions.append(LitioAssistantAction(
                        label=f"Open candidate: {cand.first_name or cand.username}",
                        action_type='open_candidate',
                        route='/dashboard',
                        entity_type='candidate',
                        entity_id=cand.id,
                        query_params={'candidateId': cand.id},
                    ))
            except Exception:
                pass
    except Exception:
        actions = []
    return LitioDataIntentResult(True, answer=answer, intent_key='data_aptitude_analytics', actions=actions)


def _handle_candidate_followups(user: User, question: str, context: dict | None):
    company = _get_company_for_user(user)
    now = timezone.now()
    follow = {
        'missed_interviews': [],
        'pending_applications': [],
        'aptitude_pending': [],
    }

    # missed interviews: scheduled and date in past
    qs = Interview.objects.filter(status='scheduled', date__lt=now)
    if company and not getattr(user, 'is_staff', False):
        qs = qs.filter(role__company=company)
    for it in qs.select_related('candidate')[:20]:
        follow['missed_interviews'].append(it)

    # pending applications older than 48 hours
    apps = CandidateVacancyApplication.objects.filter(status=CandidateVacancyApplication.Status.PENDING_REVIEW)
    if company and not getattr(user, 'is_staff', False):
        apps = apps.filter(vacancy__company=company)
    threshold = timedelta(hours=48)
    for a in apps.select_related('candidate')[:500]:
        ts = a.reviewed_at or a.hiring_started_at or a.updated_at or a.applied_at
        if ts and now - ts > threshold:
            follow['pending_applications'].append(a)

    # aptitude assignments: assigned or in progress but no interview scheduled
    try:
        aa = AptitudeTestAssignment.objects.filter(status__in=[AptitudeTestAssignment.Status.ASSIGNED, AptitudeTestAssignment.Status.IN_PROGRESS])
        if company and not getattr(user, 'is_staff', False):
            aa = aa.filter(vacancy__company=company)
        for a in aa.select_related('candidate', 'vacancy')[:200]:
            if not getattr(a, 'interview', None):
                follow['aptitude_pending'].append(a)
    except Exception:
        # If aptitude assignment table/columns are not available in this environment, skip this signal
        pass

    parts = []
    if follow['missed_interviews']:
        parts.append(f"{len(follow['missed_interviews'])} missed interviews")
    if follow['pending_applications']:
        parts.append(f"{len(follow['pending_applications'])} applications pending review beyond 48 hours")
    if follow['aptitude_pending']:
        parts.append(f"{len(follow['aptitude_pending'])} aptitude assignments pending scheduling")

    if not parts:
        return LitioDataIntentResult(True, answer="I do not see immediate follow-up items based on interviews, applications, or aptitude assignments.", intent_key='data_candidate_followups')

    answer = "I found the following follow-up signals: " + '; '.join(parts) + "."
    actions: list[LitioAssistantAction] = []
    try:
        if follow['missed_interviews']:
            actions.append(LitioAssistantAction(
                label='View missed interviews',
                action_type='navigate',
                route='/dashboard',
                query_params={'section': 'interviews', 'filter': 'missed'},
            ))
        if follow['pending_applications']:
            actions.append(LitioAssistantAction(
                label='View pending review',
                action_type='navigate',
                route='/dashboard',
                query_params={'section': 'candidates', 'filter': 'pending_review'},
            ))
        if follow['aptitude_pending']:
            actions.append(LitioAssistantAction(
                label='View pending aptitude',
                action_type='navigate',
                route='/dashboard',
                query_params={'section': 'aptitude', 'filter': 'pending'},
            ))
    except Exception:
        actions = []
    return LitioDataIntentResult(True, answer=answer, intent_key='data_candidate_followups', actions=actions)


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

    # Aptitude analytics (check before generic 'score' to avoid false positives)
    if re.search(r'aptitude|aptitude test|passed aptitude|average aptitude|scored|top scorers', q, re.I):
        return _handle_aptitude_analytics(user, q, context)

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

    # SLA breaches
    if re.search(r'sla|breach|overdue|overdue applications|pending action|stuck for|pending action for', q, re.I):
        return _handle_sla_breaches(user, q, context)

    # Pipeline / vacancy health
    if re.search(r'pipeline health|weak pipeline|no candidates|no interviews scheduled|roles have no candidates|which job needs attention|low candidate activity|pipeline', q, re.I):
        return _handle_pipeline_health(user, q, context)

    # Aptitude analytics
    if re.search(r'aptitude|aptitude test|passed aptitude|average aptitude|scored|top scorers', q, re.I):
        return _handle_aptitude_analytics(user, q, context)

    # Candidate follow-ups
    if re.search(r'follow[- ]?up|need follow[- ]?up|missed interviews|pending recruiter action|need next step|waiting for follow', q, re.I):
        return _handle_candidate_followups(user, q, context)

    return LitioDataIntentResult(False)
