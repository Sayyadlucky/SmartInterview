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
    path('get-evaluator/', commonViews.getEvaluator, name='get-evaluator'),
    path('get-evaluator-profile/', commonViews.getInterviewsForProfile, name='get-evaluator-profile'),
]