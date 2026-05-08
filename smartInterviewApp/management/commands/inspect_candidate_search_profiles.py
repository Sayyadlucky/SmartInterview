from __future__ import annotations

import json

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from smartInterviewApp.models import CandidateResume
from smartInterviewApp.services.ai_talent_pool.pgvector_retrieval import _infer_inactive_reason


class Command(BaseCommand):
    help = 'Inspect candidate -> resume -> search profile state for AI Talent Pool indexing.'

    def add_arguments(self, parser):
        parser.add_argument('--candidate-id', type=int, default=None)

    def handle(self, *args, **options):
        qs = User.objects.filter(profile__role='candidate').select_related('search_profile')
        candidate_id = options.get('candidate_id')
        if candidate_id:
            qs = qs.filter(id=candidate_id)

        rows = []
        for candidate in qs.order_by('id'):
            resume = (
                CandidateResume.objects
                .filter(candidate=candidate, is_active=True)
                .order_by('-processed_at', '-updated_at', '-id')
                .first()
            )
            profile = getattr(candidate, 'search_profile', None)
            rows.append({
                'candidate_id': candidate.id,
                'username': candidate.username,
                'active_resume_found': bool(resume),
                'active_resume_id': resume.id if resume else None,
                'resume_status': resume.status if resume else '',
                'resume_title': resume.current_title if resume else '',
                'search_profile_exists': bool(profile),
                'search_profile_active': bool(profile.is_active) if profile else False,
                'inactive_reason': _infer_inactive_reason(profile) if profile else 'no_search_profile',
                'searchable_profile_built': bool(profile.searchable_profile_built) if profile else False,
                'missing_fields_summary': list(profile.missing_fields_summary or []) if profile else [],
                'normalized_title': profile.normalized_title if profile else '',
                'role_family': profile.role_family if profile else '',
            })

        self.stdout.write(json.dumps(rows, indent=2))
