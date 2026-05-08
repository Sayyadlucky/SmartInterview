from django.conf import settings
from django.shortcuts import render, redirect
from django.views import View

from smartInterviewApp.services.company_enrichment import ensure_company_profile_for_user
from smartInterviewApp.templatetags.host_links import build_host_link


class RedirectToAngular(View):

    def get(self, request, *args, **kwargs):
        profile = getattr(request.user, 'profile', None)
        if profile and profile.role == 'candidate':
            return redirect(build_host_link(request, 'candidates'))
        ensure_company_profile_for_user(request.user)
        return render(request, 'angular_index.html', {
            'session_timeout_seconds': getattr(settings, 'SESSION_COOKIE_AGE', 1800),
            'session_warning_seconds': getattr(settings, 'SESSION_IDLE_WARNING_SECONDS', 60),
        })
