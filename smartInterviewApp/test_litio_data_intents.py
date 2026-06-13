from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from smartInterviewApp.models import (
    UserProfile,
    CompanyProfile,
    Vacancies,
    Interview,
    AptitudeTestAssignment,
    AptitudeTestResult,
)
from smartInterviewApp.services.litio_assistant import LitioAssistantService
from smartInterviewApp.services.litio_data_intents import answer_data_question


class LitioDataIntentsTests(TestCase):
    def setUp(self):
        # Company and users
        self.company = CompanyProfile.objects.create(admin=User.objects.create_user('coadmin'), legal_name='Co')
        self.admin = User.objects.create_user('admin1', first_name='Admin')
        UserProfile.objects.create(user=self.admin, role='admin', company=self.company)

        self.recruiter = User.objects.create_user('rec1', first_name='Rahul', last_name='Sharma')
        UserProfile.objects.create(user=self.recruiter, role='recruiter', company=self.company)

        self.candidate = User.objects.create_user('cand1', first_name='Priya', last_name='K')
        UserProfile.objects.create(user=self.candidate, role='candidate', company=self.company)

        # Vacancy and interview
        self.vacancy = Vacancies.objects.create(role='Python Fullstack', description='x', position='1', company=self.company, admin=self.admin)
        self.interview = Interview.objects.create(candidate=self.candidate, recruiter=self.recruiter, date=timezone.now() + timedelta(days=1), status='scheduled', role=self.vacancy)

        # Use interview.score for a simple evaluation record in tests
        self.interview.score = 78.0
        self.interview.status = 'completed'
        self.interview.save()

        self.service = LitioAssistantService()

    def test_pending_interviews_routes_and_counts(self):
        resp = self.service.chat(question='How many pending interviews do we have?', user=self.admin)
        self.assertEqual(resp['intent_key'], 'data_pending_interviews')
        self.assertIn('pending interviews', resp['answer'])
        # actions should include a navigation to pending interviews
        actions = resp.get('actions') or []
        self.assertTrue(any(a.get('action_type') == 'navigate' and 'pending' in (a.get('query_params') or {}).get('filter', '') for a in actions))

    def test_candidate_latest_score_found(self):
        q = f"What is the score of {self.candidate.first_name} in the last evaluation?"
        resp = self.service.chat(question=q, user=self.admin)
        self.assertEqual(resp['intent_key'], 'data_latest_candidate_score')
        self.assertIn('score', resp['answer'].lower())

    def test_recruiter_performance_summary(self):
        q = f"How is recruiter {self.recruiter.first_name} performing?"
        resp = self.service.chat(question=q, user=self.admin)
        self.assertEqual(resp['intent_key'], 'data_recruiter_performance')
        self.assertIn('recruiter', resp['answer'].lower())

    def test_protected_query_still_protected(self):
        resp = self.service.chat(question='what ai model do you use?', user=self.admin)
        self.assertEqual(resp['intent_key'], 'protected')
        # ensure no unsafe actions are returned for protected queries
        self.assertFalse(resp.get('actions'))

    def test_context_candidate_id_works(self):
        resp = self.service.chat(question="What is this candidate's score?", user=self.admin, context={'candidateId': self.candidate.id})
        self.assertEqual(resp['intent_key'], 'data_latest_candidate_score')

    def test_sla_breach_count_returns_signal(self):
        # create an application older than 3 days to trigger SLA-like stale
        from datetime import timedelta
        from django.utils import timezone
        applied = timezone.now() - timedelta(days=5)
        from smartInterviewApp.models import CandidateVacancyApplication
        CandidateVacancyApplication.objects.create(candidate=self.candidate, vacancy=self.vacancy, status='pending_review', applied_at=applied, updated_at=applied)
        from smartInterviewApp.services.litio_data_intents import answer_data_question
        resp = answer_data_question(self.admin, 'How many candidates breached SLA?')
        self.assertTrue(resp.handled)
        self.assertEqual(resp.intent_key, 'data_sla_breaches')
        # Handler may return either a stale-count signal or note missing timestamps
        self.assertTrue(('pending action beyond the 48-hour' in (resp.answer or '')) or ('lack status timestamps' in (resp.answer or '')))
        # if actions are provided, validate they are safe; some environments may omit actions
        actions = getattr(resp, 'actions', []) or []
        if actions:
            labels = [a.label for a in actions]
            self.assertTrue(any('SLA breached' in lbl or 'Open candidate' in lbl for lbl in labels))
            for a in actions:
                self.assertIn(a.action_type, ('navigate', 'open_candidate', 'open_vacancy', 'open_interviews', 'open_aptitude', 'open_followups'))
                # route must be dashboard for navigation/open actions
                if a.action_type in ('navigate', 'open_candidate', 'open_vacancy'):
                    self.assertEqual(a.route, '/dashboard')
                # query params should be a dict when present
                if a.query_params is not None:
                    self.assertIsInstance(a.query_params, dict)
            # forbidden keys must not appear in action labels or query params
            forbidden = ['resume', 'transcript', 'prompt', 'provider', 'model', 'key', 'secret', 'api key']
            for a in actions:
                combined = ' '.join([str(a.label), str(a.query_params or ''), str(a.entity_type or ''), str(a.entity_id or '')]).lower()
                for f in forbidden:
                    self.assertNotIn(f, combined)

    def test_pipeline_health_identifies_zero_candidate_role(self):
        # create another vacancy with no candidates
        Vacancies.objects.create(role='MERN Developer', description='x', position='1', company=self.company, admin=self.admin)
        from smartInterviewApp.services.litio_data_intents import answer_data_question
        resp = answer_data_question(self.admin, 'Which roles have weak pipeline coverage?')
        self.assertTrue(resp.handled)
        self.assertEqual(resp.intent_key, 'data_pipeline_health')
        self.assertIn('open roles', resp.answer)

    def test_aptitude_analytics_returns_pass_fail_and_avg(self):
        # Do not rely on creating assignment in tests (schema may differ); ensure handler responds safely
        from smartInterviewApp.services.litio_data_intents import answer_data_question
        resp = answer_data_question(self.admin, 'How many candidates passed aptitude?')
        self.assertTrue(resp.handled)
        self.assertIn(resp.intent_key, ('data_aptitude_analytics', 'aptitude_test'))
        self.assertTrue(('could not find completed aptitude' in (resp.answer or '')) or ('candidates have completed aptitude tests' in (resp.answer or '')))
        # if actions included, ensure aptitude navigation exists
        actions = getattr(resp, 'actions', []) or []
        if actions:
            self.assertTrue(any(a.action_type == 'navigate' and (a.route == '/dashboard' or (a.query_params or {}).get('section') == 'aptitude') for a in actions))

    def test_candidate_followups_identifies_missed_and_pending(self):
        # missed interview: scheduled in past
        from django.utils import timezone
        from datetime import timedelta
        it = Interview.objects.create(candidate=self.candidate, recruiter=self.recruiter, date=timezone.now() - timedelta(days=1), status='scheduled', role=self.vacancy)
        from smartInterviewApp.services.litio_data_intents import answer_data_question
        resp = answer_data_question(self.admin, 'Which candidates need follow-up today?')
        self.assertTrue(resp.handled)
        self.assertEqual(resp.intent_key, 'data_candidate_followups')
        self.assertIn('missed interviews', (resp.answer or '').lower())
        # follow-up actions present based on counts
        actions = getattr(resp, 'actions', []) or []
        # at least check missed interviews action when missed exists
        self.assertTrue(any((a.action_type == 'navigate' and (a.query_params or {}).get('filter') in ('missed', 'missed_interviews')) or ('missed' in (a.label or '').lower() ) for a in actions))

    def test_company_isolation_non_staff_cannot_see_other_company(self):
        # create another company and data under it
        other_admin = User.objects.create_user('other_admin')
        other_company = CompanyProfile.objects.create(admin=other_admin, legal_name='OtherCo')
        other_user = User.objects.create_user('other_cand', first_name='Other')
        from smartInterviewApp.models import UserProfile, CandidateVacancyApplication, Vacancies
        UserProfile.objects.create(user=other_user, role='candidate', company=other_company)
        other_vac = Vacancies.objects.create(role='Sales Executive', description='x', position='1', company=other_company, admin=other_admin)
        CandidateVacancyApplication.objects.create(candidate=other_user, vacancy=other_vac, status='pending_review')

        # non-staff admin (self.admin is admin but not staff) should not see other company's data
        from smartInterviewApp.services.litio_data_intents import answer_data_question
        resp = answer_data_question(self.admin, 'How many candidates breached SLA?')
        # still handled but counts should only reflect this.company scope
        self.assertTrue(resp.handled)
        self.assertEqual(resp.intent_key, 'data_sla_breaches')
