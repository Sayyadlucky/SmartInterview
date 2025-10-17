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


def home(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('dashboard')  # or role-based redirect
    else:
        if request.user.is_authenticated:
            return redirect('/dashboard')
        form = LoginForm()
    return render(request, 'smartInterview/index.html', {'form': form})

@login_required(login_url='home')
def dashboard(request):
    print(request.user.is_authenticated)
    return render(request, 'smartInterview/dashboard.html')

@csrf_exempt
def ajax_login(request):
    username = request.POST.get('username')
    password = request.POST.get('password')

    user = authenticate(request, username=username, password=password)

    if user is not None:
        login(request, user)
        return JsonResponse({'success': True, 'message': 'Login successful'})
    else:
        return JsonResponse({'success': False, 'message': 'Invalid username or password'})

class MyLogoutView(View):
    def get(self, request):
        logout(request)
        return redirect('home')
@login_required
def dashboardData(request):
    try:
        admin = get_object_or_404(User, username=request.user.username)
        candidates_data = Interview.objects.filter(hr=admin)
        candidate_list = []
        for candidate in candidates_data:
            candidate_details = {}
            candidate_details['id'] = candidate.id
            candidate_details['name'] = (candidate.candidate.first_name + " " + candidate.candidate.last_name).title()
            candidate_details['email'] = candidate.candidate.email
            candidate_details['recruiter'] = (candidate.recruiter.first_name + " " + candidate.recruiter.last_name).title()
            candidate_details['status'] = candidate.status
            candidate_details['score'] = candidate.score
            candidate_details['recording_url'] = candidate.recording_url
            candidate_details['notes'] = candidate.notes
            candidate_details['date'] = candidate.date
            candidate_details['role'] = candidate.role.role
            candidate_details['role_id'] = candidate.role.id

            candidate_list.append(candidate_details)
        # login_user = serializers.serialize("json", [admin])
        login_user = {'name': (admin.first_name).title() + " " + (admin.last_name).title()}
        data = {'login_user':login_user, 'candidate_data': candidate_list }
        data = {"Success": True, "Error": None, "Data":data}

        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({"Success":False, "Data":"Something Went Wrong"})

@csrf_exempt
@login_required
def updateCandidateStatus(request):
    try:
        candidate_id = request.POST.get('candidateId')
        status = request.POST.get('newStatus')
        candidate = Interview.objects.get(id=candidate_id)
        candidate.status = status
        candidate.save()
        return JsonResponse({"Success":True, "Error":None})
    except Exception as e:
        return JsonResponse({"Success":False, "Error":str(e)})