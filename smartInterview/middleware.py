from __future__ import annotations

from .subdomains import classify_subdomain


class SubdomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.subdomain = classify_subdomain(request.get_host())
        return self.get_response(request)
