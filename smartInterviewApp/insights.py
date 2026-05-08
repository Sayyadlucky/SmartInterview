from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db import close_old_connections
from django.utils import timezone

from smartInterviewApp.models import CandidateInsightSnapshot, CandidateResume, Interview, UserProfile


class CandidateInsightService:
    endpoint = 'https://api.openai.com/v1/responses'

    def __init__(self) -> None:
        self.api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
        self.model = getattr(settings, 'OPENAI_INSIGHTS_MODEL', '').strip() or getattr(settings, 'OPENAI_RESUME_MODEL', 'gpt-4.1-mini').strip()

    def get_snapshot(self, user: User) -> CandidateInsightSnapshot:
        snapshot, _ = CandidateInsightSnapshot.objects.get_or_create(candidate=user)
        return snapshot

    def build_signature(self, user: User, profile: UserProfile, resume: CandidateResume | None, interview: Interview | None) -> str:
        signature_payload = {
            'user_id': user.id,
            'name': f'{user.first_name} {user.last_name}'.strip(),
            'email': user.email,
            'phone': profile.phone or '',
            'gender': profile.gender or '',
            'resume_id': resume.id if resume else None,
            'resume_updated_at': resume.updated_at.isoformat() if resume and resume.updated_at else '',
            'resume_status': resume.status if resume else '',
            'resume_headline': resume.headline if resume else '',
            'role_id': interview.role_id if interview else None,
            'role': interview.role.role if interview and interview.role else '',
            'interview_count': user.candidate_interviews.count(),
        }
        raw = json.dumps(signature_payload, sort_keys=True).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def mark_stale(self, user: User) -> CandidateInsightSnapshot:
        snapshot = self.get_snapshot(user)
        snapshot.status = CandidateInsightSnapshot.Status.PENDING
        snapshot.error_message = ''
        snapshot.save(update_fields=['status', 'error_message', 'updated_at'])
        return snapshot

    def should_generate(self, snapshot: CandidateInsightSnapshot, signature: str) -> bool:
        return snapshot.status in {
            CandidateInsightSnapshot.Status.NOT_STARTED,
            CandidateInsightSnapshot.Status.PENDING,
            CandidateInsightSnapshot.Status.FAILED,
        } or snapshot.source_signature != signature

    def trigger_generation(self, user: User, profile: UserProfile, resume: CandidateResume | None, interview: Interview | None) -> CandidateInsightSnapshot:
        snapshot = self.get_snapshot(user)
        signature = self.build_signature(user, profile, resume, interview)
        if snapshot.status == CandidateInsightSnapshot.Status.PROCESSING and snapshot.source_signature == signature:
            return snapshot
        if not self.should_generate(snapshot, signature):
            return snapshot

        snapshot.status = CandidateInsightSnapshot.Status.PROCESSING
        snapshot.error_message = ''
        snapshot.source_signature = signature
        snapshot.requested_at = timezone.now()
        snapshot.generated_for_role = interview.role.role if interview and interview.role else ''
        snapshot.generated_for_title = resume.current_title if resume else ''
        snapshot.model_name = self.model
        snapshot.save(update_fields=[
            'status', 'error_message', 'source_signature', 'requested_at',
            'generated_for_role', 'generated_for_title', 'model_name', 'updated_at',
        ])

        worker = threading.Thread(
            target=self._run_generation,
            args=(user.id, signature),
            daemon=True,
            name=f'candidate-insights-{user.id}',
        )
        worker.start()
        return snapshot

    def serialize_snapshot(self, snapshot: CandidateInsightSnapshot | None) -> dict[str, Any]:
        if not snapshot:
            return {
                'status': CandidateInsightSnapshot.Status.NOT_STARTED,
                'loading': False,
                'available': False,
                'error_message': '',
                'executive_summary': '',
                'resume_score': None,
                'role_fit_score': None,
                'market_demand_score': None,
                'current_skills_impact_score': None,
                'market_demand_label': '',
                'salary_range': '',
                'salary_trend_summary': '',
                'market_demand_summary': '',
                'current_skills_impact_summary': '',
                'top_strengths': [],
                'growth_areas': [],
                'recommended_skills': [],
                'recommended_roles': [],
                'generated_at': '',
                'model_name': '',
            }

        return {
            'status': snapshot.status,
            'loading': snapshot.status in {CandidateInsightSnapshot.Status.PENDING, CandidateInsightSnapshot.Status.PROCESSING},
            'available': snapshot.status == CandidateInsightSnapshot.Status.COMPLETED,
            'error_message': snapshot.error_message,
            'executive_summary': snapshot.executive_summary,
            'resume_score': snapshot.resume_score,
            'role_fit_score': snapshot.role_fit_score,
            'market_demand_score': snapshot.market_demand_score,
            'current_skills_impact_score': snapshot.current_skills_impact_score,
            'market_demand_label': snapshot.market_demand_label,
            'salary_range': snapshot.salary_range,
            'salary_trend_summary': snapshot.salary_trend_summary,
            'market_demand_summary': snapshot.market_demand_summary,
            'current_skills_impact_summary': snapshot.current_skills_impact_summary,
            'top_strengths': snapshot.top_strengths or [],
            'growth_areas': snapshot.growth_areas or [],
            'recommended_skills': snapshot.recommended_skills or [],
            'recommended_roles': snapshot.recommended_roles or [],
            'generated_at': snapshot.generated_at.isoformat() if snapshot.generated_at else '',
            'model_name': snapshot.model_name,
        }

    def _run_generation(self, user_id: int, signature: str) -> None:
        close_old_connections()
        try:
            user = User.objects.select_related('profile').get(id=user_id)
            profile = user.profile
            resume = CandidateResume.objects.filter(candidate=user, is_active=True).prefetch_related('sections').first()
            interview = Interview.objects.select_related('role').filter(candidate=user).order_by('-date', '-id').first()
            snapshot = self.get_snapshot(user)
            if snapshot.source_signature != signature:
                return

            payload = self._generate_payload(user, profile, resume, interview)
            snapshot.status = CandidateInsightSnapshot.Status.COMPLETED
            snapshot.error_message = ''
            snapshot.executive_summary = payload.get('executive_summary', '')
            snapshot.resume_score = payload.get('resume_score')
            snapshot.role_fit_score = payload.get('role_fit_score')
            snapshot.market_demand_score = payload.get('market_demand_score')
            snapshot.current_skills_impact_score = payload.get('current_skills_impact_score')
            snapshot.market_demand_label = payload.get('market_demand_label', '')
            snapshot.salary_range = payload.get('salary_range', '')
            snapshot.salary_trend_summary = payload.get('salary_trend_summary', '')
            snapshot.market_demand_summary = payload.get('market_demand_summary', '')
            snapshot.current_skills_impact_summary = payload.get('current_skills_impact_summary', '')
            snapshot.top_strengths = payload.get('top_strengths', [])
            snapshot.growth_areas = payload.get('growth_areas', [])
            snapshot.recommended_skills = payload.get('recommended_skills', [])
            snapshot.recommended_roles = payload.get('recommended_roles', [])
            snapshot.payload = payload
            snapshot.generated_for_role = interview.role.role if interview and interview.role else ''
            snapshot.generated_for_title = resume.current_title if resume else ''
            snapshot.generated_at = timezone.now()
            snapshot.model_name = self.model
            snapshot.save()
        except Exception as exc:
            try:
                user = User.objects.get(id=user_id)
                snapshot = self.get_snapshot(user)
                if snapshot.source_signature == signature:
                    snapshot.status = CandidateInsightSnapshot.Status.FAILED
                    snapshot.error_message = str(exc)
                    snapshot.generated_at = timezone.now()
                    snapshot.save(update_fields=['status', 'error_message', 'generated_at', 'updated_at'])
            except Exception:
                pass
        finally:
            close_old_connections()

    def _generate_payload(self, user: User, profile: UserProfile, resume: CandidateResume | None, interview: Interview | None) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError('OpenAI insights generation is not configured.')

        resume_sections = []
        if resume:
            for section in resume.sections.all():
                resume_sections.append({
                    'title': section.title,
                    'section_key': section.section_key,
                    'content': section.content,
                })

        prompt_input = {
            'candidate': {
                'name': f'{user.first_name} {user.last_name}'.strip(),
                'email': user.email,
                'phone': profile.phone or '',
                'gender': profile.gender or '',
            },
            'role': interview.role.role if interview and interview.role else '',
            'resume': {
                'headline': resume.headline if resume else '',
                'summary': resume.summary if resume else '',
                'candidate_type': resume.candidate_type if resume else '',
                'current_title': resume.current_title if resume else '',
                'current_company': resume.current_company if resume else '',
                'total_experience_years': float(resume.total_experience_years) if resume and resume.total_experience_years is not None else None,
                'structured_data': resume.structured_data if resume else {},
                'sections': resume_sections[:12],
            },
            'note': (
                'Generate premium dashboard insights for an AI hiring platform. '
                'Use only the candidate profile and resume data provided. '
                'For market demand and salary trend, provide directional estimates and clearly keep them approximate, not authoritative. '
                'Return concise recruiter-friendly insight summaries.'
            ),
        }

        body = json.dumps({
            'model': self.model,
            'input': json.dumps(prompt_input),
            'temperature': 0.4,
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': 'candidate_insights',
                    'strict': True,
                    'schema': self._response_schema(),
                }
            },
        }).encode('utf-8')

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f'OpenAI insights HTTP error {exc.code}: {detail[:400]}') from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f'OpenAI insights network error: {exc.reason}') from exc

        text = self._extract_output_text(payload)
        if not text:
            raise RuntimeError('OpenAI insights response did not contain usable structured output.')
        parsed = json.loads(text)
        return parsed

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        text = (payload.get('output_text') or '').strip()
        if text:
            return text
        for item in payload.get('output') or []:
            for content in item.get('content', []):
                maybe_text = content.get('text')
                if isinstance(maybe_text, str) and maybe_text.strip():
                    return maybe_text.strip()
        return ''

    def _response_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'executive_summary': {'type': 'string'},
                'resume_score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                'role_fit_score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                'market_demand_score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                'current_skills_impact_score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                'market_demand_label': {'type': 'string'},
                'salary_range': {'type': 'string'},
                'salary_trend_summary': {'type': 'string'},
                'market_demand_summary': {'type': 'string'},
                'current_skills_impact_summary': {'type': 'string'},
                'top_strengths': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 5,
                },
                'growth_areas': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 5,
                },
                'recommended_skills': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 8,
                },
                'recommended_roles': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'maxItems': 6,
                },
            },
            'required': [
                'executive_summary',
                'resume_score',
                'role_fit_score',
                'market_demand_score',
                'current_skills_impact_score',
                'market_demand_label',
                'salary_range',
                'salary_trend_summary',
                'market_demand_summary',
                'current_skills_impact_summary',
                'top_strengths',
                'growth_areas',
                'recommended_skills',
                'recommended_roles',
            ],
        }
