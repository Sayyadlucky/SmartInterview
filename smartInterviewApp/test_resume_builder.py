import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from smartInterviewApp.commonViews import sanitize_resume_builder_payload
from smartInterviewApp.services.resume_ai import rank_top_skills, score_resume
from smartInterviewApp.models import (
    AptitudeTestAssignment,
    CandidatePublicResume,
    CandidateResume,
    CandidateResumeBuilderDraft,
    CandidateResumeSection,
    Interview,
    ResumeAiFeedback,
    ResumeAiLearningPattern,
    ResumeAiProfessionalReview,
    ResumeAiSuggestion,
    UserProfile,
    Vacancies,
)


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
        self.assertContains(response, 'Create a professional resume that opens doors.')
        self.assertContains(response, 'id="previewButton"')
        self.assertContains(response, 'Save Draft')
        self.assertContains(response, 'Download Word')
        self.assertContains(response, 'Download PDF')
        self.assertContains(response, 'resume-layout')
        self.assertContains(response, 'resume-progress-sidebar')
        self.assertContains(response, 'resume-editor-panel')
        self.assertContains(response, 'resume-preview-panel')
        self.assertContains(response, 'id="mobileStepList"')
        self.assertContains(response, 'ph ph-eye')
        self.assertContains(response, 'ph ph-file-pdf')
        self.assertContains(response, 'Add Education')
        self.assertContains(response, 'Education Entry')
        self.assertContains(response, 'Live Preview')
        self.assertContains(response, 'ai-beta-pill')
        self.assertContains(response, 'Beta')
        self.assertContains(response, 'id="aiSuggestButton"')
        self.assertContains(response, 'id="aiSuggestionsPanel"')
        self.assertContains(response, 'ai-drawer')
        self.assertContains(response, 'ai-drawer-backdrop')
        self.assertContains(response, 'ai-drawer-panel')
        self.assertContains(response, 'id="aiDrawerCloseButton"')
        self.assertContains(response, 'openAiSuggestionsDrawer')
        self.assertContains(response, 'closeAiSuggestionsDrawer')
        self.assertContains(response, 'ai-loading')
        self.assertContains(response, 'ai-provider-chip')
        self.assertContains(response, 'ai-section-chip')
        self.assertContains(response, 'ai-confidence-chip')
        self.assertContains(response, 'data-ai-action="apply"')
        self.assertContains(response, 'data-ai-action="view-guidance"')
        self.assertContains(response, 'data-ai-professional-prompt')
        self.assertContains(response, 'Get professional review')
        self.assertContains(response, 'resolveStepFromApplyTarget')
        self.assertContains(response, 'resolveFieldElementFromApplyTarget')
        self.assertContains(response, 'scrollToAndHighlightField')
        self.assertContains(response, 'ai-field-highlight')
        self.assertContains(response, 'rbAiFieldPulse')
        self.assertContains(response, 'is-active')
        self.assertContains(response, 'id="viewFullPreviewButton"')

    def test_candidate_resume_builder_renders_saved_payload_for_ui(self):
        CandidateResumeBuilderDraft.objects.create(
            candidate=self.candidate,
            payload={
                'basics': {'name': 'Builder Candidate', 'headline': 'Backend Engineer'},
                'skills': ['Python', 'Django'],
                'experience': [{'title': 'Backend Engineer', 'company': 'Shortlistii'}],
                'projects': [{'title': 'Hiring Dashboard'}],
                'education': [{'degree': 'B.Tech', 'institution': 'Pune University'}],
                'certifications': [],
                'achievements': [],
                'languages': [],
            },
        )

        response = self.client.get(reverse('candidate-resume-builder'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Builder Candidate')
        self.assertContains(response, 'B.Tech')
        self.assertContains(response, 'Pune University')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'id="viewFullPreviewButton"')

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

    @patch('smartInterviewApp.commonViews.render_pdf_from_html', return_value=(b'%PDF-html-fallback', 'xhtml2pdf'))
    @patch('smartInterviewApp.commonViews.render_pdf_with_chrome', side_effect=RuntimeError('Chrome is unavailable'))
    def test_candidate_resume_builder_pdf_download_uses_html_fallback_before_text(
        self,
        render_pdf_mock,
        render_html_mock,
    ):
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
        self.assertEqual(response.content, b'%PDF-html-fallback')
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['X-Resume-PDF-Renderer'], 'xhtml2pdf')
        render_pdf_mock.assert_called_once()
        render_html_mock.assert_called_once()

        fallback_html = render_html_mock.call_args.args[0]
        self.assertIn('Backend Engineer', fallback_html)
        self.assertIn('Built APIs', fallback_html)

    @patch('smartInterviewApp.commonViews.render_pdf_from_html', side_effect=RuntimeError('HTML renderer is unavailable'))
    @patch('smartInterviewApp.commonViews.render_pdf_with_chrome', side_effect=RuntimeError('Chrome is unavailable'))
    @patch('smartInterviewApp.commonViews.get_cupsfilter_binary', return_value='')
    def test_public_resume_pdf_download_uses_pure_python_fallback_without_system_renderers(
        self,
        cupsfilter_mock,
        render_pdf_mock,
        render_html_mock,
    ):
        CandidatePublicResume.objects.create(candidate=self.candidate, short_code='bb555etz')
        resume = CandidateResume.objects.create(
            candidate=self.candidate,
            status=CandidateResume.ParseStatus.COMPLETED,
            is_active=True,
            headline='Backend Engineer',
            summary='Builds reliable Django systems.',
            current_title='Backend Engineer',
            structured_data={'skills': ['Python', 'Django']},
            processed_at=timezone.now(),
        )
        CandidateResumeSection.objects.create(
            resume=resume,
            section_key='experience',
            title='Experience',
            display_order=1,
            content={'items': [{'title': 'Backend Engineer', 'company': 'Shortlistii', 'details': ['Built APIs']}]},
            raw_text='Backend Engineer at Shortlistii\nBuilt APIs',
        )

        response = self.client.get(reverse('public-candidate-resume-pdf', args=['bb555etz']))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['X-Resume-PDF-Renderer'], 'fallback-text')
        self.assertTrue(response.content.startswith(b'%PDF-1.4'))
        render_pdf_mock.assert_called_once()
        render_html_mock.assert_called_once()
        cupsfilter_mock.assert_called_once()

    def test_candidate_dashboard_contains_resume_builder_link(self):
        response = self.client.get(reverse('candidate-dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('candidate-resume-builder'))

    def test_candidate_secure_resume_streams_uploaded_source_file(self):
        profile = self.candidate.profile
        profile.resume.name = 'resumes/current_resume.pdf'
        profile.save(update_fields=['resume'])
        storage = UserProfile._meta.get_field('resume').storage

        with (
            patch.object(storage, 'exists', return_value=True),
            patch.object(storage, 'open', return_value=BytesIO(b'%PDF-current-resume')),
        ):
            response = self.client.get(reverse('candidate-secure-resume'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], 'inline; filename="current_resume.pdf"')
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-current-resume')

    def test_candidate_secure_resume_redirects_to_generated_pdf_when_source_file_is_missing(self):
        profile = self.candidate.profile
        profile.resume.name = 'resumes/missing_resume.pdf'
        profile.save(update_fields=['resume'])
        storage = UserProfile._meta.get_field('resume').storage

        with patch.object(storage, 'exists', return_value=False):
            response = self.client.get(reverse('candidate-secure-resume'))

        self.assertRedirects(
            response,
            reverse('candidate-resume-builder-pdf'),
            fetch_redirect_response=False,
        )

    def test_candidate_dashboard_shows_next_interview_link(self):
        role = Vacancies.objects.create(
            role='Python Developer',
            description='Backend role',
            position='1',
            status='active',
            admin=self.admin,
        )
        interview = Interview.objects.create(
            candidate=self.candidate,
            hr=self.admin,
            role=role,
            status='scheduled',
            date=timezone.now() + timedelta(days=1),
        )

        response = self.client.get(reverse('candidate-dashboard'))

        interview.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Join Interview')
        self.assertContains(response, f'https://litio.shortlistii.com/i/{interview.litio_interview_token}')

    def create_dashboard_interview(self, *, status='scheduled', date=None):
        role = Vacancies.objects.create(
            role='Python Developer',
            description='Backend role',
            position='1',
            status='active',
            admin=self.admin,
        )
        return Interview.objects.create(
            candidate=self.candidate,
            hr=self.admin,
            role=role,
            status=status,
            date=date if date is not None else timezone.now() + timedelta(days=1),
        )

    def assign_aptitude(self, interview, status):
        return AptitudeTestAssignment.objects.create(
            candidate=self.candidate,
            interview=interview,
            vacancy=interview.role,
            title='Aptitude Assessment',
            status=status,
            scheduled_at=timezone.now() + timedelta(hours=2),
        )

    def get_candidate_dashboard_context(self):
        response = self.client.get(reverse('candidate-dashboard'))
        self.assertEqual(response.status_code, 200)
        return response, response.context

    def test_candidate_dashboard_timeline_without_aptitude_uses_interview_action(self):
        interview = self.create_dashboard_interview()

        response, context = self.get_candidate_dashboard_context()
        item = context['timeline'][0]

        interview.refresh_from_db()
        self.assertEqual(item['action_link_type'], 'interview')
        self.assertEqual(item['action_link_label'], 'Join Interview')
        self.assertEqual(item['action_link_icon'], 'ph-video-camera')
        self.assertEqual(item['action_link'], item['interview_link'])
        self.assertContains(response, f'https://litio.shortlistii.com/i/{interview.litio_interview_token}')

    def test_candidate_dashboard_timeline_assigned_aptitude_uses_start_action(self):
        interview = self.create_dashboard_interview()
        assignment = self.assign_aptitude(interview, AptitudeTestAssignment.Status.ASSIGNED)

        response, context = self.get_candidate_dashboard_context()
        item = context['timeline'][0]

        self.assertEqual(item['aptitude_assignment_id'], assignment.id)
        self.assertEqual(item['aptitude_status'], AptitudeTestAssignment.Status.ASSIGNED)
        self.assertTrue(item['aptitude_pending'])
        self.assertEqual(item['action_link_type'], 'aptitude')
        self.assertEqual(item['action_link_label'], 'Start Aptitude Test')
        self.assertEqual(item['action_link_icon'], 'ph-clipboard-text')
        self.assertEqual(item['action_link_status_label'], 'Assessment Pending')
        self.assertIn(f'/aptitude/{assignment.public_token}/', item['action_link'])
        self.assertContains(response, 'Start Aptitude Test')

    def test_candidate_dashboard_timeline_in_progress_aptitude_uses_resume_action(self):
        interview = self.create_dashboard_interview()
        self.assign_aptitude(interview, AptitudeTestAssignment.Status.IN_PROGRESS)

        response, context = self.get_candidate_dashboard_context()
        item = context['timeline'][0]

        self.assertEqual(item['action_link_type'], 'aptitude')
        self.assertEqual(item['action_link_label'], 'Resume Aptitude Test')
        self.assertEqual(item['action_link_status_label'], 'Assessment In Progress')
        self.assertContains(response, 'Resume Aptitude Test')

    def test_candidate_dashboard_timeline_submitted_aptitude_uses_interview_action(self):
        interview = self.create_dashboard_interview()
        self.assign_aptitude(interview, AptitudeTestAssignment.Status.SUBMITTED)

        _response, context = self.get_candidate_dashboard_context()
        item = context['timeline'][0]

        self.assertFalse(item['aptitude_pending'])
        self.assertEqual(item['aptitude_status'], AptitudeTestAssignment.Status.SUBMITTED)
        self.assertEqual(item['action_link_type'], 'interview')
        self.assertEqual(item['action_link_label'], 'Join Interview')
        self.assertEqual(item['action_link'], item['interview_link'])

    def test_candidate_dashboard_timeline_expired_aptitude_uses_interview_action(self):
        interview = self.create_dashboard_interview()
        self.assign_aptitude(interview, AptitudeTestAssignment.Status.EXPIRED)

        _response, context = self.get_candidate_dashboard_context()
        item = context['timeline'][0]

        self.assertFalse(item['aptitude_pending'])
        self.assertEqual(item['aptitude_status'], AptitudeTestAssignment.Status.EXPIRED)
        self.assertEqual(item['action_link_type'], 'interview')
        self.assertEqual(item['action_link_label'], 'Join Interview')
        self.assertEqual(item['action_link'], item['interview_link'])

    def test_candidate_dashboard_timeline_preview_and_full_timeline_include_action_fields(self):
        now = timezone.now()
        for index in range(6):
            self.create_dashboard_interview(date=now + timedelta(days=index + 1))

        _response, context = self.get_candidate_dashboard_context()

        self.assertEqual(len(context['timeline']), 6)
        self.assertEqual(len(context['timeline_preview']), 5)
        for item in [*context['timeline'], *context['timeline_preview']]:
            self.assertIn('action_link', item)
            self.assertIn('action_link_type', item)
            self.assertIn('action_link_label', item)
            self.assertIn('action_link_icon', item)
            self.assertIn('action_link_status_label', item)

    def test_candidate_dashboard_next_action_uses_pending_aptitude_but_keeps_interview_link(self):
        interview = self.create_dashboard_interview(date=timezone.now() + timedelta(days=1))
        assignment = self.assign_aptitude(interview, AptitudeTestAssignment.Status.ASSIGNED)

        _response, context = self.get_candidate_dashboard_context()
        analytics = context['analytics']

        interview.refresh_from_db()
        self.assertEqual(analytics['next_action_type'], 'aptitude')
        self.assertEqual(analytics['next_action_label'], 'Start Aptitude Test')
        self.assertEqual(analytics['next_action_icon'], 'ph-clipboard-text')
        self.assertIn(f'/aptitude/{assignment.public_token}/', analytics['next_action_link'])
        self.assertEqual(
            analytics['next_interview_link'],
            f'https://litio.shortlistii.com/i/{interview.litio_interview_token}',
        )

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

    def _ai_payload(self):
        return {
            'basics': {
                'name': 'Builder Candidate',
                'email': 'builder-candidate@example.com',
                'phone': '919111111101',
                'location': 'Pune',
                'headline': 'Python Developer',
                'summary': 'Hardworking developer responsible for backend work.',
            },
            'skills': ['Python', 'Django'],
            'experience': [{'title': 'Python Developer', 'company': 'Shortlistii', 'details': ['Responsible for APIs']}],
            'projects': [],
            'education': [{'degree': 'B.Tech', 'institution': 'Pune University'}],
            'certifications': [],
            'achievements': [],
            'languages': [],
        }

    def _create_ai_suggestion(self):
        draft, _ = CandidateResumeBuilderDraft.objects.get_or_create(candidate=self.candidate)
        return ResumeAiSuggestion.objects.create(
            candidate=self.candidate,
            draft=draft,
            section_key='basics',
            step_key='basics',
            role_family='software_it',
            resume_type='technical',
            suggestion_type='summary_improvement',
            local_suggestion_title='Strengthen summary',
            local_suggestion_text='Add role, skills, and outcome.',
            local_suggestion_payload={
                'apply_target': 'basics.summary',
                'apply_mode': 'replace',
                'recommended_text': 'Python Developer with Django experience.',
            },
        )

    def _experienced_software_payload(self):
        return {
            'basics': {
                'name': 'Builder Candidate',
                'email': 'builder-candidate@example.com',
                'phone': '919111111101',
                'location': 'Pune',
                'headline': 'Software Engineer with 6 Years Experience in Python and Fullstack Development | Python, Django, Angular',
                'summary': 'Hardworking software engineer responsible for Python and fullstack development for finance applications.',
                'github': '',
                'portfolio': '',
                'website': '',
            },
            'skills': [
                'Python 3.x', 'Angular', 'C', 'C++', 'Django', 'Django REST Framework',
                'REST API', 'MySQL', 'Flask', 'Postman', 'PyCharm', 'Windows',
                'JavaScript', 'HTML', 'CSS', 'Git'
            ],
            'experience': [
                {
                    'title': 'Software Engineer',
                    'company': 'Finance Systems',
                    'duration': '2022 - Present',
                    'description': 'Python, Django, Angular and REST API development for finance workflows.',
                    'details': ['Responsible for backend APIs and Angular interfaces.'],
                    'tech_stack': ['Python', 'Django', 'Django REST Framework', 'Angular', 'MySQL'],
                },
                {
                    'title': 'Python Developer',
                    'company': 'Banking Apps',
                    'duration': '2020 - 2022',
                    'description': 'Worked on Flask and REST API services for banking workflows.',
                    'details': ['Responsible for Flask services and production fixes.'],
                    'tech_stack': ['Python', 'Flask', 'REST API', 'MySQL'],
                },
                {
                    'title': 'Junior Developer',
                    'company': 'Enterprise Tools',
                    'duration': '2018 - 2020',
                    'details': ['Responsible for Django modules.'],
                    'tech_stack': ['Python', 'Django', 'JavaScript'],
                },
                {
                    'title': 'Trainee Developer',
                    'company': 'Training Team',
                    'duration': '2017 - 2018',
                    'details': ['Responsible for internal tools.'],
                    'tech_stack': ['Python', 'SQL'],
                },
            ],
            'projects': [],
            'education': [{'degree': 'B.Tech', 'institution': 'Pune University', 'duration': '2013 - 2017'}],
            'certifications': [],
            'achievements': [],
            'languages': [],
        }

    def test_resume_ai_suggestions_endpoint_requires_authentication(self):
        self.client.logout()

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': self._ai_payload(), 'current_step': 'basics'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 302)

    def test_resume_ai_suggestions_returns_local_provider_and_persists_rows(self):
        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': self._ai_payload(), 'current_step': 'basics'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['provider'], 'local')
        self.assertGreater(len(data['suggestions']), 0)
        self.assertEqual(ResumeAiSuggestion.objects.filter(candidate=self.candidate).count(), len(data['suggestions']))
        self.assertIn('suggestion_id', data['suggestions'][0])

    def test_resume_ai_feedback_applied_updates_status_and_creates_feedback(self):
        suggestion = self._create_ai_suggestion()

        response = self.client.post(
            reverse('candidate-resume-builder-ai-feedback'),
            data=json.dumps({'suggestion_id': suggestion.id, 'feedback': 'applied', 'reason': ''}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, ResumeAiSuggestion.Status.APPLIED)
        self.assertTrue(ResumeAiFeedback.objects.filter(suggestion=suggestion, feedback='applied').exists())

    def test_resume_ai_feedback_not_useful_offers_professional_review(self):
        suggestion = self._create_ai_suggestion()

        response = self.client.post(
            reverse('candidate-resume-builder-ai-feedback'),
            data=json.dumps({'suggestion_id': suggestion.id, 'feedback': 'not_useful'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['offer_professional_review'])
        self.assertEqual(data['message'], 'Do you want a more professional review?')

    @override_settings(RESUME_AI_OPENAI_REVIEW_ENABLED=False, OPENAI_API_KEY='test-key')
    @patch('smartInterviewApp.services.resume_ai.call_openai_professional_review')
    def test_resume_ai_professional_review_rejects_when_disabled(self, openai_mock):
        suggestion = self._create_ai_suggestion()

        response = self.client.post(
            reverse('candidate-resume-builder-ai-professional-review'),
            data=json.dumps({'suggestion_id': suggestion.id, 'payload': self._ai_payload()}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error_code'], 'professional_review_disabled')
        self.assertFalse(ResumeAiProfessionalReview.objects.exists())
        openai_mock.assert_not_called()

    @override_settings(RESUME_AI_OPENAI_REVIEW_ENABLED=True, OPENAI_API_KEY='test-key', RESUME_AI_OPENAI_MODEL='gpt-test')
    @patch('smartInterviewApp.services.resume_ai.call_openai_professional_review')
    def test_resume_ai_professional_review_calls_openai_when_enabled_and_stores_review(self, openai_mock):
        openai_mock.return_value = {
            'title': 'Sharper summary',
            'message': 'Use a tighter summary.',
            'recommended_text': 'Python Developer with Django and API experience. Add one verified delivery outcome.',
            'apply_target': 'basics.summary',
            'apply_mode': 'replace',
            'reason': 'The current summary is generic.',
            'reusable_pattern': {
                'pattern_type': 'summary_template',
                'template_text': '{role} with {top_skills}. Add one verified delivery outcome.',
                'keywords': ['APIs', 'Django'],
                'role_family': 'software_it',
                'section_key': 'basics',
            },
        }
        suggestion = self._create_ai_suggestion()

        response = self.client.post(
            reverse('candidate-resume-builder-ai-professional-review'),
            data=json.dumps({'suggestion_id': suggestion.id, 'payload': self._ai_payload()}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['provider'], 'openai')
        openai_mock.assert_called_once()
        review = ResumeAiProfessionalReview.objects.get()
        self.assertEqual(review.openai_model, 'gpt-test')
        self.assertNotIn('test-key', response.content.decode())
        pattern = ResumeAiLearningPattern.objects.get()
        self.assertEqual(pattern.status, ResumeAiLearningPattern.Status.CANDIDATE)
        self.assertEqual(pattern.source_count, 1)

    @override_settings(RESUME_AI_OPENAI_REVIEW_ENABLED=True, OPENAI_API_KEY='test-key')
    @patch('smartInterviewApp.services.resume_ai.call_openai_professional_review')
    def test_resume_ai_learning_pattern_sanitizes_identifiers(self, openai_mock):
        openai_mock.return_value = {
            'title': 'Sharper summary',
            'message': 'Use a tighter summary.',
            'recommended_text': 'Rahul Sharma improved work at Acme Client. Email rahul@example.com phone +91 98765 43210.',
            'apply_target': 'basics.summary',
            'apply_mode': 'replace',
            'reason': 'The current summary is generic.',
            'reusable_pattern': {
                'pattern_type': 'summary_template',
                'template_text': 'Rahul Sharma improved work at Acme Client. Email rahul@example.com phone +91 98765 43210.',
                'keywords': ['Rahul Sharma', 'https://private.example.com'],
                'role_family': 'software_it',
                'section_key': 'basics',
            },
        }
        suggestion = self._create_ai_suggestion()

        self.client.post(
            reverse('candidate-resume-builder-ai-professional-review'),
            data=json.dumps({'suggestion_id': suggestion.id, 'payload': self._ai_payload()}),
            content_type='application/json',
        )

        pattern = ResumeAiLearningPattern.objects.get()
        self.assertNotIn('rahul@example.com', pattern.template_text.lower())
        self.assertNotIn('98765', pattern.template_text)
        self.assertNotIn('https://private.example.com', pattern.keywords_json)
        self.assertEqual(pattern.status, ResumeAiLearningPattern.Status.CANDIDATE)

    def test_resume_ai_professional_review_feedback_applied_increases_confidence(self):
        suggestion = self._create_ai_suggestion()
        review = ResumeAiProfessionalReview.objects.create(
            suggestion=suggestion,
            candidate=self.candidate,
            professional_payload={
                'reusable_pattern': {
                    'pattern_type': 'summary_template',
                },
            },
        )
        pattern = ResumeAiLearningPattern.objects.create(
            role_family='software_it',
            resume_type='technical',
            section_key='basics',
            suggestion_type='summary_improvement',
            pattern_type='summary_template',
            template_text='{role} with {top_skills}.',
            confidence_score=0.52,
            status=ResumeAiLearningPattern.Status.CANDIDATE,
        )

        response = self.client.post(
            reverse('candidate-resume-builder-ai-professional-review-feedback'),
            data=json.dumps({'professional_review_id': review.id, 'feedback': 'applied'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        pattern.refresh_from_db()
        self.assertTrue(review.user_applied)
        self.assertEqual(pattern.applied_count, 1)
        self.assertGreater(pattern.confidence_score, 0.52)

    def test_resume_ai_local_suggestions_use_trusted_learning_pattern(self):
        ResumeAiLearningPattern.objects.create(
            role_family='software_it',
            resume_type='technical',
            section_key='basics',
            suggestion_type='summary_improvement',
            pattern_type='summary_template',
            template_text='Trusted pattern for {role} using {top_skills}.',
            confidence_score=0.91,
            status=ResumeAiLearningPattern.Status.TRUSTED,
        )
        payload = self._ai_payload()
        payload['basics']['summary'] = ''

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        suggestions = response.json()['suggestions']
        self.assertTrue(any('Trusted pattern' in (item.get('recommended_text') or '') for item in suggestions))

    def test_resume_ai_score_not_excellent_for_generic_resume_with_missing_proof(self):
        payload = self._ai_payload()
        payload['basics']['summary'] = 'Motivated individual seeking a position to leverage my skills and contribute to success.'
        payload['projects'] = []
        payload['certifications'] = []
        payload['achievements'] = []

        score = score_resume(payload, role_family='software_it', resume_type='technical')

        self.assertLess(score, 90)
        self.assertLessEqual(score, 78)

    def test_resume_ai_experienced_software_resume_with_gaps_scores_decent(self):
        score = score_resume(self._experienced_software_payload(), role_family='software_it', resume_type='technical')

        self.assertGreaterEqual(score, 70)
        self.assertLessEqual(score, 84)

    def test_resume_ai_incomplete_resume_scores_below_45(self):
        payload = {
            'basics': {'name': 'Builder Candidate'},
            'skills': [],
            'experience': [],
            'projects': [],
            'education': [],
            'certifications': [],
            'achievements': [],
            'languages': [],
        }

        self.assertLess(score_resume(payload), 45)

    def test_resume_ai_excellent_resume_scores_89_plus(self):
        payload = self._experienced_software_payload()
        payload['basics']['headline'] = 'Software Engineer | Python, Django, REST API, Angular | 6 years experience'
        payload['basics']['summary'] = (
            'Software Engineer with 6 years of experience building web applications with Python, Django, '
            'Django REST Framework, Angular, and MySQL. Built and maintained backend APIs, responsive '
            'frontend workflows, production fixes, and Agile delivery for finance-domain applications.'
        )
        payload['projects'] = [{
            'title': 'Finance Workflow Dashboard',
            'description': 'Built a Django and Angular dashboard for finance workflow tracking.',
            'tech_stack': ['Python', 'Django', 'Angular', 'MySQL'],
        }]
        payload['achievements'] = [{'label': 'Production Reliability', 'description': 'Improved production issue resolution and release stability.'}]
        payload['certifications'] = [{'label': 'Python Certification', 'issuer': 'Training Provider'}]
        payload['experience'][0]['details'] = ['Built Django REST APIs and Angular interfaces, improving reliability for finance workflows by 20%.']
        payload['experience'][1]['details'] = ['Improved Flask API response handling and reduced recurring production issues by 15%.']
        payload['experience'][2]['details'] = ['Built Django modules used by internal teams, improving maintainability by 10%.']
        payload['experience'][3]['details'] = ['Automated SQL reporting checks, reducing manual review time by 10%.']

        self.assertGreaterEqual(score_resume(payload, role_family='software_it', resume_type='technical'), 89)

    def test_resume_ai_current_step_basics_returns_basics_first_for_weak_basics(self):
        payload = self._ai_payload()
        payload['basics']['headline'] = 'Developer'
        payload['basics']['summary'] = 'Hardworking team player seeking a position.'

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        suggestions = response.json()['suggestions']
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]['section_key'], 'basics')
        self.assertIn(suggestions[0]['suggestion_type'], {'headline_improvement', 'summary_improvement'})

    def test_resume_ai_weak_summary_returns_one_actionable_summary_suggestion(self):
        payload = self._experienced_software_payload()

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        summary_suggestions = [
            item for item in response.json()['suggestions']
            if item['suggestion_type'] == 'summary_improvement' and item.get('apply_target') == 'basics.summary'
        ]
        self.assertEqual(len(summary_suggestions), 1)
        self.assertTrue(summary_suggestions[0]['actionable'])
        self.assertEqual(summary_suggestions[0]['apply_mode'], 'replace')

    def test_resume_ai_generic_summary_phrases_produce_summary_improvement(self):
        payload = self._ai_payload()
        payload['basics']['summary'] = 'Motivated individual seeking a position in a growth-oriented company for personal development.'

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item['suggestion_type'] == 'summary_improvement' for item in response.json()['suggestions']))

    def test_resume_ai_generated_summary_is_clean_and_prioritizes_recent_stack(self):
        payload = self._experienced_software_payload()

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        summary = next(
            item['recommended_text'] for item in response.json()['suggestions']
            if item['suggestion_type'] == 'summary_improvement' and item['apply_target'] == 'basics.summary'
        )
        self.assertNotIn('|', summary)
        self.assertEqual(summary.lower().count('6 years'), 1)
        self.assertNotIn('with 6 years of experience with', summary.lower())
        self.assertIn('Python', summary)
        self.assertIn('Django', summary)
        self.assertIn('Angular', summary)
        self.assertIn('REST', summary)
        self.assertNotIn('C++', summary)

    def test_resume_ai_headline_suggestion_is_role_aware(self):
        payload = self._ai_payload()
        payload['basics']['headline'] = ''

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        headline = next(item for item in response.json()['suggestions'] if item['suggestion_type'] == 'headline_improvement')
        self.assertIn('Python', headline['recommended_text'])
        self.assertIn('|', headline['recommended_text'])

    def test_resume_ai_experienced_resume_ranks_weak_basics_before_missing_projects(self):
        payload = self._ai_payload()
        payload['basics']['headline'] = 'Developer'
        payload['basics']['summary'] = 'Responsible for backend work.'
        payload['projects'] = []

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        suggestions = response.json()['suggestions']
        project_index = next((index for index, item in enumerate(suggestions) if item['section_key'] == 'projects'), 99)
        basics_index = next((index for index, item in enumerate(suggestions) if item['section_key'] == 'basics'), 99)
        self.assertLess(basics_index, project_index)

    def test_resume_ai_fresher_resume_prioritizes_projects_for_projects_step(self):
        payload = self._ai_payload()
        payload['basics']['headline'] = 'Fresher Data Analyst'
        payload['basics']['summary'] = 'Entry level candidate with SQL and Excel coursework.'
        payload['experience'] = []
        payload['projects'] = []
        payload['skills'] = ['SQL', 'Excel']

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'projects'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['suggestions'][0]['section_key'], 'projects')

    def test_resume_ai_non_technical_role_gets_relevant_suggestions(self):
        payload = self._ai_payload()
        payload['basics']['headline'] = 'HR Recruiter'
        payload['basics']['summary'] = ''
        payload['skills'] = ['Sourcing', 'Screening']
        payload['experience'] = [{'title': 'HR Recruiter', 'company': 'Talent Team', 'details': ['Responsible for hiring coordination']}]

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        summary = next(item for item in response.json()['suggestions'] if item['suggestion_type'] == 'summary_improvement')
        self.assertIn('sourcing', summary['recommended_text'].lower())
        self.assertIn('screening', summary['recommended_text'].lower())

    def test_resume_ai_non_actionable_guidance_is_not_applyable(self):
        payload = self._ai_payload()
        payload['basics']['email'] = ''
        payload['basics']['phone'] = ''

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        guidance = next(item for item in response.json()['suggestions'] if not item.get('recommended_text'))
        self.assertFalse(guidance['actionable'])
        self.assertEqual(guidance['primary_action_label'], 'View guidance')

    def test_resume_ai_actionable_suggestions_include_target_and_text(self):
        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': self._ai_payload(), 'current_step': 'basics'}),
            content_type='application/json',
        )

        actionable = [item for item in response.json()['suggestions'] if item['actionable']]
        self.assertTrue(actionable)
        self.assertTrue(all(item['apply_target'] and item['recommended_text'] for item in actionable))

    def test_resume_ai_returns_max_five_suggestions(self):
        payload = self._ai_payload()
        payload['basics'] = {'name': 'Builder Candidate'}
        payload['skills'] = []
        payload['experience'] = [{'title': '', 'company': '', 'details': []}]
        payload['projects'] = []
        payload['education'] = []

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'review'}),
            content_type='application/json',
        )

        self.assertLessEqual(len(response.json()['suggestions']), 5)

    def test_resume_ai_software_top_skills_exclude_c_cpp_when_recent_stack_is_stronger(self):
        skills = rank_top_skills(self._experienced_software_payload(), 'software_it', limit=4)

        self.assertIn('Python', skills)
        self.assertTrue(any(skill in skills for skill in ['Django', 'Django REST Framework']))
        self.assertIn('Angular', skills)
        self.assertNotIn('C', skills)
        self.assertNotIn('C++', skills)

    def test_resume_ai_hr_top_skills_prioritize_recruiting_terms(self):
        payload = {
            'basics': {'headline': 'HR Recruiter', 'summary': 'HR recruiter handling sourcing, screening and ATS updates.'},
            'skills': ['MS Office', 'Sourcing', 'Screening', 'ATS', 'Interview Coordination'],
            'experience': [{'title': 'HR Recruiter', 'tech_stack': ['Sourcing', 'Screening', 'ATS']}],
        }

        skills = rank_top_skills(payload, 'hr_recruitment', limit=3)

        self.assertEqual(skills, ['Sourcing', 'Screening', 'ATS'])

    def test_resume_ai_sales_top_skills_prioritize_sales_terms(self):
        payload = {
            'basics': {'headline': 'Sales Executive', 'summary': 'Sales executive handling lead generation, CRM updates, and client handling.'},
            'skills': ['Excel', 'Lead Generation', 'CRM', 'Client Handling', 'Email'],
            'experience': [{'title': 'Sales Executive', 'tech_stack': ['Lead Generation', 'CRM', 'Client Handling']}],
        }

        skills = rank_top_skills(payload, 'sales_marketing', limit=3)

        self.assertEqual(skills, ['Lead Generation', 'CRM', 'Client Handling'])

    def test_resume_ai_candidate_learning_pattern_is_not_used_as_trusted(self):
        ResumeAiLearningPattern.objects.create(
            role_family='software_it',
            resume_type='technical',
            section_key='basics',
            suggestion_type='summary_improvement',
            pattern_type='summary_template',
            template_text='Candidate-only pattern should not appear.',
            confidence_score=0.99,
            status=ResumeAiLearningPattern.Status.CANDIDATE,
        )
        payload = self._ai_payload()
        payload['basics']['summary'] = ''

        response = self.client.post(
            reverse('candidate-resume-builder-ai-suggestions'),
            data=json.dumps({'payload': payload, 'current_step': 'basics'}),
            content_type='application/json',
        )

        self.assertFalse(any('Candidate-only pattern' in (item.get('recommended_text') or '') for item in response.json()['suggestions']))
