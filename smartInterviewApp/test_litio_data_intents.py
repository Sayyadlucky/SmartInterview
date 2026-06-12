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

    def test_context_candidate_id_works(self):
        resp = self.service.chat(question="What is this candidate's score?", user=self.admin, context={'candidateId': self.candidate.id})
        self.assertEqual(resp['intent_key'], 'data_latest_candidate_score')
