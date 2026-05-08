import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from smartInterviewApp.commonViews import sanitize_resume_builder_payload
from smartInterviewApp.models import CandidateResumeBuilderDraft, UserProfile


class ResumeBuilderViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='builder-admin', password='pass1234', email='builder-admin@example.com')
        self.candidate = User.objects.create_user(username='builder-candidate', password='pass1234', email='builder-candidate@example.com')
        UserProfile.objects.create(user=self.admin, role='admin', phone='919111111100', gender='other')
        UserProfile.objects.create(user=self.candidate, role='candidate', phone='919111111101', gender='female', hr=self.admin)
        self.client.login(username='builder-candidate', password='pass1234')

    def test_candidate_resume_builder_page_renders(self):
        response = self.client.get(reverse('candidate-resume-builder'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Resume Builder')

    def test_candidate_resume_builder_save_persists_draft_payload(self):
        payload = {
            'basics': {
                'name': 'Builder Candidate',
                'email': 'builder-candidate@example.com',
                'phone': '919111111101',
                'headline': 'Backend Engineer',
                'summary': 'Builds reliable Django systems.',
            },
            'skills': ['Python', 'Django'],
            'experience': [{'title': 'Backend Engineer', 'company': 'Shortlistii', 'details': ['Built APIs']}],
            'projects': [],
            'education': [],
            'certifications': [],
            'achievements': [],
            'languages': [],
        }

        response = self.client.post(reverse('candidate-resume-builder'), {
            'payload': json.dumps(payload),
        })

        self.assertEqual(response.status_code, 200)
        draft = CandidateResumeBuilderDraft.objects.get(candidate=self.candidate)
        self.assertEqual(draft.payload['basics']['headline'], 'Backend Engineer')
        self.assertEqual(draft.payload['skills'], ['Python', 'Django'])

    @patch('smartInterviewApp.commonViews.render_word_document_from_rtf', return_value=b'word-document')
    def test_candidate_resume_builder_word_download_uses_saved_draft(self, render_word_mock):
        CandidateResumeBuilderDraft.objects.create(
            candidate=self.candidate,
            payload={
                'basics': {'name': 'Builder Candidate', 'headline': 'Backend Engineer'},
                'skills': ['Python'],
                'experience': [{'title': 'Backend Engineer', 'company': 'Shortlistii', 'details': ['Built APIs']}],
                'projects': [],
                'education': [],
                'certifications': [],
                'achievements': [],
                'languages': [],
            },
        )

        response = self.client.get(reverse('candidate-resume-builder-word'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'word-document')
        self.assertEqual(response['Content-Type'], 'application/msword')
        render_word_mock.assert_called_once()

    @patch('smartInterviewApp.commonViews.render_pdf_with_chrome', return_value=(b'%PDF-test', 'chrome'))
    def test_candidate_resume_builder_pdf_download_uses_saved_draft(self, render_pdf_mock):
        CandidateResumeBuilderDraft.objects.create(
            candidate=self.candidate,
            payload={
                'basics': {'name': 'Builder Candidate', 'headline': 'Backend Engineer'},
                'skills': ['Python'],
                'experience': [{'title': 'Backend Engineer', 'company': 'Shortlistii', 'details': ['Built APIs']}],
                'projects': [],
                'education': [],
                'certifications': [],
                'achievements': [],
                'languages': [],
            },
        )

        response = self.client.get(reverse('candidate-resume-builder-pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'%PDF-test')
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['X-Resume-PDF-Renderer'], 'chrome')
        render_pdf_mock.assert_called_once()

    def test_candidate_dashboard_contains_resume_builder_link(self):
        response = self.client.get(reverse('candidate-dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('candidate-resume-builder'))

    def test_public_resume_builder_renders_signup_prompt(self):
        self.client.logout()

        response = self.client.get(reverse('candidate-resume-builder'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Resume For Free')
        self.assertContains(response, reverse('candidate-signup'))
        self.assertContains(response, reverse('candidate-login'))

    def test_public_resume_builder_save_is_blocked(self):
        self.client.logout()

        response = self.client.post(reverse('candidate-resume-builder'), {
            'payload': json.dumps({'basics': {'name': 'Public User'}}),
        })

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data['Success'])
        self.assertEqual(data['redirect_url'], reverse('candidate-login'))

    def test_sanitize_resume_builder_payload_drops_project_entries_without_project_identity(self):
        serialized_project = (
            "{'title': '', 'degree': '', 'label': '', 'value': '', 'company': '', "
            "'institution': '', 'issuer': '', 'location': '', 'role': 'Salesforce Developer', "
            "'description': '', 'duration': '', 'duration_text': '', 'start_date': '', "
            "'end_date': '', 'employment_type': '', 'is_current': False, 'tech_stack': "
            "['Salesforce.com', 'Apex'], 'details': ['Built custom Lightning components.'], 'notes': []}"
        )

        payload = sanitize_resume_builder_payload(
            {
                'basics': {
                    'name': 'Builder Candidate',
                    'email': 'builder-candidate@example.com',
                    'phone': '919111111101',
                },
                'projects': [{'description': serialized_project}],
            },
            user=self.candidate,
            profile=self.candidate.profile,
        )

        self.assertEqual(payload['projects'], [])
