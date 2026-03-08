import random
import string
from collections import defaultdict
from datetime import timedelta, datetime, time
from statistics import median

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import serializers
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .forms import LoginForm
from django.shortcuts import render, redirect, get_object_or_404

from .models import Interview
from .models import UserProfile, Vacancies
from django.db import transaction
from django.db.models import Count, Case, When, CharField, Value, Q
from django.utils import timezone


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
            role_obj = Vacancies.objects.get(id=role)
            admin = get_object_or_404(User, username=request.user.username)
            if email:
                obj, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "username": generate_username(name),
                        "email": email,
                        "first_name": name.split(" ")[0],
                        "last_name": name.split(" ")[1],
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
                            'role': user_type.lower(),
                            'phone': phone,
                            'hr': admin
                        }
                    )
                    if not created_profile:
                        profile.role = user_type
                        profile.save()
                    if user_type != 'Recruiter':
                        # Add the created user profile to the Interview model if needed
                        recruiter = User.objects.get(id=recruiter)
                        hr = User.objects.get(username=request.user.username)
                        candidate = Interview.objects.create(candidate=obj, recruiter=recruiter, hr=hr, status='assessment_pending', role=role_obj)
                        candidate.save()
                        candidate_details = {}
                        candidate_details['id'] = candidate.id
                        candidate_details['name'] = (
                                    candidate.candidate.first_name + " " + candidate.candidate.last_name).title()
                        candidate_details['email'] = candidate.candidate.email
                        candidate_details['recruiter'] = (
                                    candidate.recruiter.first_name + " " + candidate.recruiter.last_name).title()
                        candidate_details['status'] = candidate.status
                        candidate_details['score'] = candidate.score
                        candidate_details['recording_url'] = candidate.recording_url
                        candidate_details['notes'] = candidate.notes
                        candidate_details['date'] = candidate.date
                        candidate_details['role'] = candidate.role.role
                        candidate_details['role_id'] = candidate.role.id
                    if user_type == 'Recruiter':
                        recruiter_list = []
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
                    profile, created_profile = UserProfile.objects.get_or_create(
                        user=obj,
                        defaults={
                            'gender': gender,
                            'role': user_type.lower(),
                            'phone': phone,
                            'hr': admin
                        }
                    )
                    if not created_profile:
                        profile.role = user_type
                        profile.save()
                    if user_type != 'Recruiter':
                        # Add the created user profile to the Interview model if needed
                        recruiter = User.objects.get(id=recruiter)
                        hr = User.objects.get(username=request.user.username)
                        candidate = Interview.objects.create(candidate=obj, recruiter=recruiter, hr=hr,
                                                             status='assessment_pending', role=role_obj)
                        candidate.save()
                        candidate_details = {}
                        candidate_details['id'] = candidate.id
                        candidate_details['name'] = (
                                candidate.candidate.first_name + " " + candidate.candidate.last_name).title()
                        candidate_details['email'] = candidate.candidate.email
                        candidate_details['recruiter'] = (
                                candidate.recruiter.first_name + " " + candidate.recruiter.last_name).title()
                        candidate_details['status'] = candidate.status
                        candidate_details['score'] = candidate.score
                        candidate_details['recording_url'] = candidate.recording_url
                        candidate_details['notes'] = candidate.notes
                        candidate_details['date'] = candidate.date
                        candidate_details['role'] = candidate.role.role
                        candidate_details['role_id'] = candidate.role.id
            else:
                    return JsonResponse({"Success":False, "Error":'Add user failed'})
            return JsonResponse({"Success":True, "Error":None, "CandidateDetails": candidate_details})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})

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
