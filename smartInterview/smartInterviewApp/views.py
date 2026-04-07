import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import serializers
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import transaction

from .forms import LoginForm
from django.shortcuts import render, redirect, get_object_or_404

from .models import CompanyProfile, Interview
from .commonViews import (
    candidateDashboard,
    candidateLogin,
    get_accessible_interviews,
    get_accessible_interviewer_profiles,
    publicJobsPortal,
    send_existing_candidate_sms,
)
from .services.company_enrichment import ensure_company_profile_for_user
from .templatetags.host_links import build_host_link


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


def resolve_login_identifier(identifier: str) -> str:
    value = (identifier or '').strip()
    if '@' in value:
        matched_user = User.objects.filter(email__iexact=value).first()
        if matched_user:
            return matched_user.username
    return value


def get_post_login_redirect_url(request, user) -> str:
    try:
        profile = getattr(user, 'profile', None)
    except Exception:
        profile = None

    try:
        if profile and profile.role == 'candidate':
            return build_host_link(request, 'candidates')
    except Exception:
        return '/dashboard/'

    return '/dashboard/'


def home(request):
    subdomain = getattr(request, 'subdomain', 'main')
    profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None
    if subdomain == 'jobs':
        if profile and profile.role == 'candidate':
            return redirect(build_host_link(request, 'candidates'))
        if profile and profile.role in {'admin', 'recruiter', 'interviewer'}:
            return redirect('/dashboard/')
        return publicJobsPortal(request)
    if subdomain == 'candidates':
        if profile and profile.role == 'candidate':
            return candidateDashboard(request)
        if request.user.is_authenticated:
            return redirect('/dashboard/')
        return candidateLogin(request)

    if request.method == 'POST':
        post_data = request.POST.copy()
        post_data['username'] = resolve_login_identifier(post_data.get('username', ''))
        form = LoginForm(request, data=post_data)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect(get_post_login_redirect_url(request, user))
    else:
        if request.user.is_authenticated:
            return redirect(get_post_login_redirect_url(request, request.user))
        form = LoginForm()
    return render(request, 'smartInterview/index.html', {'form': form})


def _get_error_page_actions(request) -> tuple[dict[str, str], dict[str, str]]:
    subdomain = getattr(request, 'subdomain', 'main')
    home_url = build_host_link(request, 'home')
    jobs_url = build_host_link(request, 'jobs')
    candidates_url = build_host_link(request, 'candidates')

    if subdomain == 'jobs':
        return (
            {'label': 'Open jobs portal', 'url': jobs_url},
            {'label': 'Go to homepage', 'url': home_url},
        )

    if subdomain == 'candidates':
        return (
            {'label': 'Open candidate portal', 'url': candidates_url},
            {'label': 'Go to homepage', 'url': home_url},
        )

    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and getattr(profile, 'role', '') == 'candidate':
            return (
                {'label': 'Open candidate portal', 'url': candidates_url},
                {'label': 'Go to homepage', 'url': home_url},
            )
        return (
            {'label': 'Back to dashboard', 'url': '/dashboard/'},
            {'label': 'Open jobs portal', 'url': jobs_url},
        )

    return (
        {'label': 'Go to homepage', 'url': home_url},
        {'label': 'Open jobs portal', 'url': jobs_url},
    )


def _build_error_page_context(request, *, variant: str) -> dict:
    primary_action, secondary_action = _get_error_page_actions(request)

    if variant == 'technical':
        return {
            'status_code': '500',
            'status_label': 'Technical issue',
            'accent_label': 'Service interruption',
            'title': 'Something went wrong while processing this request.',
            'description': 'The application is still online, but this page could not be delivered correctly. Reload the page or return to a stable area of the product.',
            'icon_class': 'ph-warning-circle',
            'tips': [
                'Reload the page to retry the request.',
                'Return to the dashboard or portal home if you need to continue working immediately.',
                'If the issue persists, note the failing URL and action for debugging.',
            ],
            'page_variant': 'technical',
            'primary_action': primary_action,
            'secondary_action': secondary_action,
            'show_reload_action': True,
        }

    return {
        'status_code': '404',
        'status_label': 'Page not found',
        'accent_label': 'Route mismatch',
        'title': 'We could not find the page you were looking for.',
        'description': 'The link may be outdated, incomplete, or pointing to a route that is no longer available in this workspace.',
        'icon_class': 'ph-magnifying-glass-minus',
        'tips': [
            'Return to a known page and continue from the main navigation.',
            'If this came from a bookmark or shared link, refresh it after opening the correct page.',
            'Double-check the path if you typed the address manually.',
        ],
        'page_variant': 'not-found',
        'primary_action': primary_action,
        'secondary_action': secondary_action,
        'show_reload_action': False,
    }


def error_404(request, exception):
    return render(request, '404.html', _build_error_page_context(request, variant='not-found'), status=404)


def error_500(request):
    return render(request, '500.html', _build_error_page_context(request, variant='technical'), status=500)

@login_required(login_url='home')
def dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'candidate':
        return redirect(build_host_link(request, 'candidates'))
    ensure_company_profile_for_user(request.user)
    return render(request, 'smartInterview/dashboard.html')

import traceback

@csrf_exempt
def ajax_login(request):
    try:
        username = resolve_login_identifier(request.POST.get('username'))
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            redirect_url = get_post_login_redirect_url(request, user)
            return JsonResponse({
                'success': True,
                'message': 'Login successful',
                'redirect_url': redirect_url,
            })

        return JsonResponse({
            'success': False,
            'message': 'Invalid username or password'
        })
    except Exception as e:
        print("LOGIN ERROR:", repr(e))
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': str(e),
        }, status=500)

class MyLogoutView(View):
    def get(self, request):
        logout(request)
        return redirect('home')
@login_required
def dashboardData(request):
    try:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role not in {'admin', 'recruiter', 'interviewer'}:
            return JsonResponse({"Success": False, "Error": "Dashboard access is restricted."}, status=403)
        admin = get_object_or_404(User, username=request.user.username)
        candidates_data = get_accessible_interviews(admin)
        candidate_list = []
        for candidate in candidates_data:
            candidate_details = {}
            candidate_details['id'] = candidate.id
            candidate_details['name'] = (candidate.candidate.first_name + " " + candidate.candidate.last_name).title()
            candidate_details['email'] = candidate.candidate.email
            candidate_details['phone'] = getattr(getattr(candidate.candidate, 'profile', None), 'phone', '') or ''
            candidate_details['candidate_id'] = candidate.candidate_id
            candidate_details['recruiter'] = (candidate.recruiter.first_name + " " + candidate.recruiter.last_name).title() if candidate.recruiter else ''
            candidate_details['recruiter_id'] = candidate.recruiter_id
            candidate_details['interviewer'] = (candidate.interviewer.first_name + " " + candidate.interviewer.last_name).title() if candidate.interviewer else ''
            candidate_details['interviewer_id'] = candidate.interviewer_id
            candidate_details['interview_type'] = getattr(candidate, 'interview_type', 'manual')
            candidate_details['status'] = normalize_interview_status(candidate.status)
            candidate_details['score'] = candidate.score
            candidate_details['recording_url'] = candidate.recording_url
            candidate_details['notes'] = candidate.notes
            candidate_details['date'] = candidate.date
            candidate_details['role'] = candidate.role.role if candidate.role else ''
            candidate_details['role_id'] = candidate.role.id if candidate.role else None

            candidate_list.append(candidate_details)
        # login_user = serializers.serialize("json", [admin])
        company_profile = getattr(admin, 'company_profile', None)
        login_user = {
            'name': (admin.first_name).title() + " " + (admin.last_name).title(),
            'role': getattr(getattr(admin, 'profile', None), 'role', ''),
        }
        company_data = None
        if company_profile:
            resolved_logo_url = company_profile.logo_url
            if getattr(company_profile, 'logo', None):
                try:
                    resolved_logo_url = request.build_absolute_uri(company_profile.logo.url)
                except Exception:
                    resolved_logo_url = company_profile.logo_url
            company_data = {
                'legal_name': company_profile.legal_name,
                'display_name': company_profile.display_name,
                'description': company_profile.description,
                'industry': company_profile.industry,
                'sub_industry': company_profile.sub_industry,
                'company_type': company_profile.company_type,
                'company_stage': company_profile.company_stage,
                'company_size': company_profile.company_size,
                'employee_count': company_profile.employee_count,
                'founded_year': company_profile.founded_year,
                'website': company_profile.website,
                'careers_page': company_profile.careers_page,
                'linkedin_url': company_profile.linkedin_url,
                'twitter_url': company_profile.twitter_url,
                'logo_url': resolved_logo_url,
                'contact_email': company_profile.contact_email,
                'contact_phone': company_profile.contact_phone,
                'alternate_phone': company_profile.alternate_phone,
                'address_line_1': company_profile.address_line_1,
                'address_line_2': company_profile.address_line_2,
                'landmark': company_profile.landmark,
                'city': company_profile.city,
                'state': company_profile.state,
                'postal_code': company_profile.postal_code,
                'country': company_profile.country,
                'headquarters': company_profile.headquarters,
                'registration_number': company_profile.registration_number,
                'tax_identifier': company_profile.tax_identifier,
                'currency_code': company_profile.currency_code,
                'timezone': company_profile.timezone,
                'updated_at': company_profile.updated_at.isoformat() if company_profile.updated_at else '',
            }
        data = {'login_user':login_user, 'candidate_data': candidate_list, 'company_profile': company_data }
        data = {"Success": True, "Error": None, "Data":data}

        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({"Success":False, "Data":"Something Went Wrong"})


@csrf_exempt
@login_required
def updateCompanyProfile(request):
    if request.method != 'POST':
        return JsonResponse({"Success": False, "Error": "Only POST is allowed."}, status=405)

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'admin':
        return JsonResponse({"Success": False, "Error": "Admin access is required."}, status=403)

    company_profile = get_object_or_404(CompanyProfile, admin=request.user)

    def clean_text(name: str) -> str:
        return (request.POST.get(name) or '').strip()

    def clean_optional_int(name: str):
        raw = clean_text(name)
        if not raw:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    valid_company_types = set(CompanyProfile.CompanyType.values)
    valid_company_stages = set(CompanyProfile.CompanyStage.values)
    valid_company_sizes = set(CompanyProfile.CompanySize.values)

    company_profile.legal_name = clean_text('legal_name') or company_profile.legal_name or 'TBD'
    company_profile.display_name = clean_text('display_name') or company_profile.display_name or company_profile.legal_name
    company_profile.description = clean_text('description')
    company_profile.industry = clean_text('industry')
    company_profile.sub_industry = clean_text('sub_industry')

    company_type = clean_text('company_type')
    company_stage = clean_text('company_stage')
    company_size = clean_text('company_size')
    if company_type in valid_company_types:
        company_profile.company_type = company_type
    if company_stage in valid_company_stages:
        company_profile.company_stage = company_stage
    if company_size in valid_company_sizes:
        company_profile.company_size = company_size

    company_profile.employee_count = clean_optional_int('employee_count')
    company_profile.founded_year = clean_optional_int('founded_year')
    company_profile.website = clean_text('website')
    company_profile.careers_page = clean_text('careers_page')
    company_profile.linkedin_url = clean_text('linkedin_url')
    company_profile.twitter_url = clean_text('twitter_url')
    company_profile.contact_email = clean_text('contact_email')
    company_profile.contact_phone = clean_text('contact_phone')
    company_profile.alternate_phone = clean_text('alternate_phone')
    company_profile.address_line_1 = clean_text('address_line_1')
    company_profile.address_line_2 = clean_text('address_line_2')
    company_profile.landmark = clean_text('landmark')
    company_profile.city = clean_text('city')
    company_profile.state = clean_text('state')
    company_profile.postal_code = clean_text('postal_code')
    company_profile.country = clean_text('country') or company_profile.country or 'India'
    company_profile.headquarters = clean_text('headquarters')
    company_profile.registration_number = clean_text('registration_number')
    company_profile.tax_identifier = clean_text('tax_identifier')
    company_profile.currency_code = clean_text('currency_code') or company_profile.currency_code or 'INR'
    company_profile.timezone = clean_text('timezone') or company_profile.timezone or 'Asia/Kolkata'

    uploaded_logo = request.FILES.get('logo')
    if uploaded_logo:
        company_profile.logo = uploaded_logo

    company_profile.save()

    if uploaded_logo and getattr(company_profile, 'logo', None):
        company_profile.logo_url = request.build_absolute_uri(company_profile.logo.url)
        company_profile.save(update_fields=['logo_url', 'updated_at'])

    resolved_logo_url = company_profile.logo_url
    if getattr(company_profile, 'logo', None):
        try:
            resolved_logo_url = request.build_absolute_uri(company_profile.logo.url)
        except Exception:
            resolved_logo_url = company_profile.logo_url

    return JsonResponse({
        "Success": True,
        "Error": None,
        "Data": {
            'legal_name': company_profile.legal_name,
            'display_name': company_profile.display_name,
            'description': company_profile.description,
            'industry': company_profile.industry,
            'sub_industry': company_profile.sub_industry,
            'company_type': company_profile.company_type,
            'company_stage': company_profile.company_stage,
            'company_size': company_profile.company_size,
            'employee_count': company_profile.employee_count,
            'founded_year': company_profile.founded_year,
            'website': company_profile.website,
            'careers_page': company_profile.careers_page,
            'linkedin_url': company_profile.linkedin_url,
            'twitter_url': company_profile.twitter_url,
            'logo_url': resolved_logo_url,
            'contact_email': company_profile.contact_email,
            'contact_phone': company_profile.contact_phone,
            'alternate_phone': company_profile.alternate_phone,
            'address_line_1': company_profile.address_line_1,
            'address_line_2': company_profile.address_line_2,
            'landmark': company_profile.landmark,
            'city': company_profile.city,
            'state': company_profile.state,
            'postal_code': company_profile.postal_code,
            'country': company_profile.country,
            'headquarters': company_profile.headquarters,
            'registration_number': company_profile.registration_number,
            'tax_identifier': company_profile.tax_identifier,
            'currency_code': company_profile.currency_code,
            'timezone': company_profile.timezone,
            'updated_at': company_profile.updated_at.isoformat() if company_profile.updated_at else '',
        }
    })

@csrf_exempt
@login_required
def updateCandidateStatus(request):
    try:
        candidate_id = request.POST.get('candidateId')
        status = normalize_interview_status(request.POST.get('newStatus'))
        valid_statuses = {choice[0] for choice in Interview.STATUS_CHOICES}
        if status not in valid_statuses:
            return JsonResponse({"Success": False, "Error": f"Invalid status '{status}'"})
        candidate = Interview.objects.get(id=candidate_id)
        candidate.status = status
        candidate.date = timezone.now()
        update_fields = ['status', 'date']
        if status in {'hired', 'completed'} and not candidate.hired_at:
            # Preserve the first known hire/completion timestamp as the canonical
            # analytics event time. `date` remains available for legacy UI flows.
            candidate.hired_at = candidate.date
            update_fields.append('hired_at')
        candidate.save(update_fields=update_fields)
        return JsonResponse({
            "Success": True,
            "Error": None,
            "Data": {
                "candidate_id": candidate.id,
                "status": candidate.status,
                "date": candidate.date.isoformat() if candidate.date else '',
            }
        })
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})


@csrf_exempt
@login_required
def updateInterviewWorkflow(request):
    if request.method != 'POST':
        return JsonResponse({"Success": False, "Error": "Only POST is allowed."}, status=405)

    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in {'admin', 'recruiter'}:
        return JsonResponse({"Success": False, "Error": "Admin or recruiter access is required."}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({"Success": False, "Error": "Invalid request payload."}, status=400)

    interview_ids = payload.get('interview_ids') or []
    if not isinstance(interview_ids, list):
        return JsonResponse({"Success": False, "Error": "Interview selection is invalid."}, status=400)

    cleaned_ids: list[int] = []
    for value in interview_ids:
        try:
            cleaned_ids.append(int(value))
        except (TypeError, ValueError):
            continue

    if not cleaned_ids:
        return JsonResponse({"Success": False, "Error": "Select at least one candidate."}, status=400)

    accessible_qs = get_accessible_interviews(request.user).filter(id__in=cleaned_ids)
    interviews = list(accessible_qs.select_related('interviewer'))
    if len(interviews) != len(set(cleaned_ids)):
        return JsonResponse({"Success": False, "Error": "One or more selected candidates are not accessible."}, status=403)

    interviewer_id = payload.get('interviewer_id')
    interview_type = str(payload.get('interview_type') or 'manual').strip().lower()
    if interview_type not in {'manual', 'auto'}:
        return JsonResponse({"Success": False, "Error": "Please select a valid interview type."}, status=400)

    interviewer_user = None
    if interview_type == 'manual' and interviewer_id not in (None, '', 'null'):
        try:
            interviewer_id = int(interviewer_id)
        except (TypeError, ValueError):
            return JsonResponse({"Success": False, "Error": "Please select a valid evaluator."}, status=400)

        interviewer_profile = (
            get_accessible_interviewer_profiles(request.user)
            .select_related('user')
            .filter(user_id=interviewer_id)
            .first()
        )
        if not interviewer_profile:
            return JsonResponse({"Success": False, "Error": "The selected evaluator is not available to this account."}, status=400)
        interviewer_user = interviewer_profile.user

    scheduled_at_raw = str(payload.get('scheduled_at') or '').strip()
    scheduled_at = None
    if scheduled_at_raw:
        scheduled_at = parse_datetime(scheduled_at_raw)
        if not scheduled_at:
            return JsonResponse({"Success": False, "Error": "Please provide a valid interview date and time."}, status=400)
        if timezone.is_naive(scheduled_at):
            scheduled_at = timezone.make_aware(scheduled_at, timezone.get_current_timezone())

    mode = (payload.get('mode') or '').strip().lower()
    if mode == 'schedule' and not scheduled_at:
        return JsonResponse({"Success": False, "Error": "Interview schedule time is required."}, status=400)
    if mode == 'bulk-assign' and not interviewer_user:
        return JsonResponse({"Success": False, "Error": "Please select an evaluator."}, status=400)
    if mode == 'schedule' and interview_type == 'manual' and not interviewer_user:
        return JsonResponse({"Success": False, "Error": "Please select an evaluator for a manual interview."}, status=400)

    updated_items = []
    notifications = []
    with transaction.atomic():
        for interview in interviews:
            update_fields: list[str] = []

            if mode == 'schedule' and interview.interview_type != interview_type:
                interview.interview_type = interview_type
                update_fields.append('interview_type')

            if interview_type == 'auto':
                if interview.interviewer_id is not None:
                    interview.interviewer = None
                    update_fields.append('interviewer')
            elif interviewer_user and interview.interviewer_id != interviewer_user.id:
                interview.interviewer = interviewer_user
                update_fields.append('interviewer')

            if scheduled_at:
                interview.date = scheduled_at
                if mode == 'schedule':
                    interview.status = 'scheduled'
                    update_fields.append('status')
                elif interview.status != 'scheduled':
                    interview.status = 'scheduled'
                    update_fields.append('status')
                update_fields.append('date')

            if update_fields:
                interview.save(update_fields=list(dict.fromkeys(update_fields)))

            updated_items.append({
                "id": interview.id,
                "interviewer_id": interview.interviewer_id,
                "interviewer": (
                    f"{interview.interviewer.first_name} {interview.interviewer.last_name}".strip().title()
                    if interview.interviewer else ''
                ),
                "interview_type": getattr(interview, 'interview_type', 'manual'),
                "status": normalize_interview_status(interview.status),
                "date": interview.date.isoformat() if interview.date else '',
            })

            if mode == 'schedule':
                try:
                    notifications.append({
                        "interview_id": interview.id,
                        "result": send_existing_candidate_sms(interview.candidate, interview),
                    })
                except Exception as exc:
                    notifications.append({
                        "interview_id": interview.id,
                        "result": {
                            "sent": False,
                            "reason": str(exc),
                        },
                    })

    return JsonResponse({
        "Success": True,
        "Error": None,
        "Data": {
            "updated_count": len(updated_items),
            "items": updated_items,
            "notifications": notifications,
        }
    })
