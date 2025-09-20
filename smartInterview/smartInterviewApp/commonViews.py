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
from .models import UserProfile
from django.db import transaction

@csrf_exempt
@login_required
def addUser(request):
    try:
        with transaction.atomic():
            email = request.POST.get('email','')
            name = request.POST.get('name','')
            phone = request.POST.get('phone','')
            role = request.POST.get('profile','')
            user_type = request.POST.get('role','')
            if email:
                obj, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "username": name.split(" ")[0],
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
                            'role': user_type,
                            'phone': phone
                        }
                    )
                    if not created_profile:
                        profile.role = user_type
                        profile.save()

                    # Add the created user profile to the Interview model if needed
                    recruiter = User.objects.get(username='TBD')
                    hr = User.objects.get(username=request.user.username)
                    candidate = Interview.objects.create(candidate=obj, recruiter=recruiter, hr=hr, status='assessment_Pending', role=role)
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
                    candidate_details['role'] = candidate.role
                else:
                    return JsonResponse({"Success":False, "Error":'User already exists'})
            else:
                return JsonResponse({"Success":False, "Error":'Add user failed'})
            return JsonResponse({"Success":True, "Error":None, "CandidateDetails": candidate_details})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})

@login_required
def getEvaluator(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        recruiter_data = UserProfile.objects.filter(hr=admin)
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
            interview_details['role'] = interview.role
            interview_list.append(interview_details)
            
        return JsonResponse({"Success": True, "Error": None, "Interviews": interview_list})
    except Exception as e:
        return JsonResponse({"Success": False, "Error": str(e)})
    

