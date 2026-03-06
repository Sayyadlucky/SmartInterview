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
]
