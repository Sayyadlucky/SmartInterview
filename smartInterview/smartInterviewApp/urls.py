from django.urls import path, include
from . import views
from . import commonViews
from django.contrib.auth import views as auth_views

from .commonViews import addUser

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.ajax_login, name="login"),
    path('logout/', views.MyLogoutView.as_view(), name='logout'),
    path('dashboard/', include(('angular.urls','angular'), namespace='dashboard')),
    path('dashboard-data/', views.dashboardData, name='dashboard-data'),
    path('update-candidate-status/', views.updateCandidateStatus, name='update-candidate-status'),
    path('add-user/', commonViews.addUser, name='add-user'),
    path('add-role/', commonViews.addRole, name='add-role'),
    path('get-evaluator/', commonViews.getEvaluator, name='get-evaluator'),
    path('get-evaluator-profile/', commonViews.getInterviewsForProfile, name='get-evaluator-profile'),
    path('evaluator-search/', commonViews.evaluatorSearch, name='get-evaluator-profile'),
    path('get-hr-list/', commonViews.getHrList, name='get-hr-list'),
    path('get-role-list/', commonViews.getRoleList, name='get-role-list'),
    path('candidates-tab-data/', commonViews.candidatesTabData, name='candidates-tab-data'),
    path('activity-tab-data/', commonViews.activityTabData, name='activity-tab-data'),
    path('analytics-tab-data/', commonViews.analyticsTabData, name='analytics-tab-data'),
    path('get-role-data/<int:id>', commonViews.getRoleData, name='get-role-data'),
    path('get-vacancy-recruiters/<int:id>/', commonViews.getVacancyReruiters, name='get-vacancy-recruiters/'),
    path('lookup-user-by-phone/', commonViews.lookupUserByPhone, name='lookup-user-by-phone'),
    path('candidate/login/', commonViews.candidateLogin, name='candidate-login'),
    path('candidate/dashboard/', commonViews.candidateDashboard, name='candidate-dashboard'),
    path('candidate/request-phone-verification/', commonViews.requestCandidatePhoneVerification, name='candidate-request-phone-verification'),
    path('candidate/verify-phone-otp/', commonViews.verifyCandidatePhoneOtp, name='candidate-verify-phone-otp'),
    path('candidate/request-email-verification/', commonViews.requestCandidateEmailVerification, name='candidate-request-email-verification'),
    path('candidate/verify-email-otp/', commonViews.verifyCandidateEmailOtp, name='candidate-verify-email-otp'),
    path('candidate/insights/trigger/', commonViews.triggerCandidateInsights, name='candidate-trigger-insights'),
    path('candidate/insights/status/', commonViews.candidateInsightStatus, name='candidate-insight-status'),
    path('candidate/submit-identity-verification/', commonViews.submitCandidateIdentityVerification, name='candidate-submit-identity-verification'),
    path('candidate/apply-to-vacancy/', commonViews.applyToVacancy, name='candidate-apply-to-vacancy'),
    path('candidate/cancel-vacancy-application/', commonViews.cancelVacancyApplication, name='candidate-cancel-vacancy-application'),
    path('candidate/vacancy-not-interested/', commonViews.markVacancyNotInterested, name='candidate-vacancy-not-interested'),
    path('recruiter-application-feed/', commonViews.recruiterApplicationFeed, name='recruiter-application-feed'),
    path('candidate/signup/', commonViews.candidateSignup, name='candidate-signup'),
    path('candidate-profile-data/<int:interview_id>/', commonViews.getCandidateProfileData, name='candidate-profile-data'),
    path('candidate-profile-data/<int:interview_id>/reprocess/', commonViews.reprocessCandidateResume, name='candidate-profile-reprocess'),
    path('resume-processing-health/', commonViews.resumeProcessingHealth, name='resume-processing-health'),
    path('r/<str:short_code>/', commonViews.publicCandidateResume, name='public-candidate-resume'),
    path('r/<str:short_code>/download-word/', commonViews.publicCandidateResumeWord, name='public-candidate-resume-word'),
    path('r/<str:short_code>/download-pdf/', commonViews.publicCandidateResumePdf, name='public-candidate-resume-pdf'),
]
