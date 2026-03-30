from django.shortcuts import render
from django.views import View

from smartInterviewApp.services.company_enrichment import ensure_company_profile_for_user


class RedirectToAngular(View):

    def get(self, request, *args, **kwargs):
        ensure_company_profile_for_user(request.user)
        return render(request, 'angular_index.html')
