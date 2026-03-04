import random
import string

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
from django.db.models import Count, Case, When, CharField, Value


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
                        candidate_details['role-id'] = candidate.role.id
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
                        candidate_details['role-id'] = candidate.role.id
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
            recruiter = request.POST.get('recruiter', '')
            user = User.objects.get(username=request.user.username)
            recruiter_obj = User.objects.get(id=recruiter)
            if user.profile.role == 'admin':
                obj = Vacancies(
                        role= name,
                        description= description,
                        position= int(vacancies) if vacancies.isdigit() else 0,
                        status= status,
                        admin= user,
                )
                obj.save()
                obj.recruiter.add(recruiter_obj)
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
        recruiter_data = UserProfile.objects.filter(hr=admin, role='recruiter')
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
        return JsonResponse({"Success":True, "Error":None, "RecruiterData":recruiter_list})
    except Exception as e:
        pass

@csrf_exempt
@login_required
def evaluatorSearch(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        name = request.POST.get('name')
        recruiter_data = UserProfile.objects.filter(hr=admin, user__first_name__icontains=name) | UserProfile.objects.filter(hr=admin, user__last_name__icontains=name)
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
            return JsonResponse({"Success": True, "Error": None, "Data": {"RecruiterData": recruiter_list}})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e), "Data": None})

@csrf_exempt
@login_required
def getInterviewsForProfile(request):
    try:
        recruiter = get_object_or_404(User, email=request.POST.get('recruiter'))
        hr = get_object_or_404(User, username=request.user.username)
        interviews = Interview.objects.filter(recruiter=recruiter, hr=hr)
        interview_list = []

        for interview in interviews:
            interview_details = {}
            interview_details['id'] = interview.id
            interview_details['candidate'] = f"{interview.candidate.first_name} {interview.candidate.last_name}".title()
            interview_details['status'] = interview.status
            interview_details['score'] = interview.score
            interview_details['role'] = interview.role.role
            interview_details['date'] = interview.date
            interview_list.append(interview_details)
            
        return JsonResponse({"Success": True, "Error": None, "Interviews": interview_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e)})

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

