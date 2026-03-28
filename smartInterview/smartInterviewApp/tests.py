from __future__ import annotations

import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile

from smartInterviewApp.integrations.providers.contracts import ProviderResult
from smartInterviewApp.models import Notification, NotificationAttempt, OtpRequest, UserProfile, Vacancies, Interview, CandidateSavedVacancy, CandidateVacancyApplication
from smartInterviewApp.notifications.services import NotificationService
from smartInterviewApp.otp.services import OtpService
from smartInterviewApp.commonViews import SIGNUP_TOKEN_SALT


@override_settings(
    MSG91_OTP_EXPIRY_SECONDS=300,
    MSG91_OTP_RESEND_COOLDOWN_SECONDS=0,
    MSG91_OTP_MAX_VERIFY_ATTEMPTS=5,
    NOTIFICATION_RETRY_LIMIT=1,
    NOTIFICATION_RETRY_BACKOFF_SECONDS=0,
)
class NotificationSystemTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ops', password='pass1234', email='ops@example.com')
        self.client.login(username='ops', password='pass1234')

    @patch('smartInterviewApp.integrations.providers.msg91.Msg91OtpProvider.request_otp')
    def test_otp_request_and_verify_flow(self, request_otp_mock):
        request_otp_mock.return_value = ProviderResult(
            success=True,
            status='sent',
            provider_request_id='req-1',
            response_payload={'request_id': 'req-1'},
        )
        service = OtpService()
        with patch.object(OtpService, '_generate_otp', return_value='123456'):
            req = service.request_otp(phone='9876543210', purpose='login', user=self.user)
        self.assertTrue(req['success'])

        verify = service.verify_otp(phone='9876543210', otp='123456', purpose='login')
        self.assertTrue(verify['success'])
        self.assertEqual(OtpRequest.objects.count(), 1)
        self.assertEqual(OtpRequest.objects.first().status, OtpRequest.Status.VERIFIED)

    @patch('smartInterviewApp.integrations.providers.meta_whatsapp.MetaWhatsappProvider.send_template_message')
    @patch('smartInterviewApp.integrations.providers.msg91.Msg91SmsProvider.send_sms')
    def test_notification_routing_medium_fallback_to_sms(self, sms_mock, whatsapp_mock):
        whatsapp_mock.return_value = ProviderResult(success=False, status='failed', response_payload={'error': 'wa'})
        sms_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='sms-1', response_payload={'ok': True})

        notification = NotificationService().send_notification(
            event_type='interview_reminder',
            severity=Notification.Severity.MEDIUM,
            user=self.user,
            payload={'to': '919876543210', 'template_name': 'reminder', 'sms_message': 'Reminder'},
        )

        attempts = list(notification.attempts.order_by('attempted_at'))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0].channel, NotificationAttempt.Channel.WHATSAPP)
        self.assertEqual(attempts[0].status, NotificationAttempt.Status.FAILED)
        self.assertEqual(attempts[1].channel, NotificationAttempt.Channel.SMS)
        self.assertEqual(attempts[1].status, NotificationAttempt.Status.SENT)
        self.assertEqual(notification.final_channel, NotificationAttempt.Channel.SMS)

    @patch('smartInterviewApp.integrations.providers.meta_whatsapp.MetaWhatsappProvider.send_template_message')
    @patch('smartInterviewApp.integrations.providers.msg91.Msg91SmsProvider.send_sms')
    @patch('smartInterviewApp.integrations.providers.exotel.ExotelVoiceProvider.trigger_voice_alert')
    def test_critical_escalation_to_voice(self, voice_mock, sms_mock, whatsapp_mock):
        whatsapp_mock.return_value = ProviderResult(success=False, status='failed', response_payload={'error': 'wa'})
        sms_mock.return_value = ProviderResult(success=False, status='failed', response_payload={'error': 'sms'})
        voice_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='voice-1', response_payload={'Call': {'Sid': 'voice-1'}})

        notification = NotificationService().send_notification(
            event_type='critical_outage',
            severity=Notification.Severity.CRITICAL,
            user=self.user,
            payload={'to': '919876543210', 'template_name': 'critical_alert', 'sms_message': 'Critical', 'alert_type': 'critical_outage'},
        )

        channels = list(notification.attempts.values_list('channel', flat=True))
        self.assertEqual(channels, [NotificationAttempt.Channel.WHATSAPP, NotificationAttempt.Channel.SMS, NotificationAttempt.Channel.VOICE])
        self.assertEqual(notification.final_channel, NotificationAttempt.Channel.VOICE)
        self.assertEqual(notification.status, Notification.Status.SENT)

    def test_meta_webhook_updates_status(self):
        notification = Notification.objects.create(
            user=self.user,
            event_type='interview_reminder',
            severity=Notification.Severity.LOW,
            status=Notification.Status.SENT,
            payload={},
        )
        NotificationAttempt.objects.create(
            notification=notification,
            channel=NotificationAttempt.Channel.WHATSAPP,
            provider='meta_whatsapp',
            provider_message_id='wamid123',
            status=NotificationAttempt.Status.SENT,
        )

        payload = {
            'entry': [
                {
                    'changes': [
                        {
                            'value': {
                                'statuses': [
                                    {'id': 'wamid123', 'status': 'delivered'},
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        response = self.client.post(
            reverse('api-webhook-meta-whatsapp'),
            data=payload,
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        attempt = notification.attempts.first()
        self.assertEqual(attempt.status, NotificationAttempt.Status.DELIVERED)
        self.assertEqual(notification.status, Notification.Status.DELIVERED)


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class CandidateOnboardingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin1', password='pass1234', email='admin@example.com')
        self.admin.first_name = 'Admin'
        self.admin.last_name = 'User'
        self.admin.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.admin, role='admin', phone='919999999999', gender='other')

        self.recruiter = User.objects.create_user(username='recruiter1', password='pass1234', email='recruiter@example.com')
        self.recruiter.first_name = 'Recruiter'
        self.recruiter.last_name = 'One'
        self.recruiter.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.recruiter, role='recruiter', phone='918888888888', gender='male', hr=self.admin)

        self.role = Vacancies.objects.create(
            role='Python Developer',
            description='Backend role',
            position='2',
            status='active',
            admin=self.admin,
        )
        self.role.recruiter.add(self.recruiter)
        self.client.login(username='admin1', password='pass1234')

    @patch('smartInterviewApp.commonViews.send_template_message')
    @patch('smartInterviewApp.commonViews.send_sms')
    def test_add_user_sends_signup_sms_for_new_candidate(self, send_sms_mock, send_whatsapp_mock):
        send_sms_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='sms-new')
        send_whatsapp_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='wa-new')

        response = self.client.post(reverse('add-user'), data={
            'email': 'newcandidate@example.com',
            'name': 'New Candidate',
            'phone': '+91 9876543210',
            'role': 'Candidate',
            'profile': str(self.role.id),
            'gender': 'female',
            'recruiter': str(self.recruiter.id),
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['Success'])
        self.assertTrue(payload['SignupRequired'])
        self.assertFalse(payload['CandidateExists'])
        self.assertIn('candidate/signup/?token=', payload['Notification']['signup_url'])
        self.assertTrue(payload['Notification']['channels']['sms']['sent'])
        self.assertTrue(payload['Notification']['channels']['whatsapp']['sent'])
        self.assertTrue(send_sms_mock.called)
        self.assertTrue(send_whatsapp_mock.called)

    @patch('smartInterviewApp.commonViews.send_template_message')
    @patch('smartInterviewApp.commonViews.send_sms')
    def test_add_user_sends_interview_sms_for_existing_candidate(self, send_sms_mock, send_whatsapp_mock):
        send_sms_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='sms-existing')
        send_whatsapp_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='wa-existing')
        candidate = User.objects.create_user(username='cand1', password='pass1234', email='existing@example.com')
        candidate.first_name = 'Existing'
        candidate.last_name = 'Candidate'
        candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=candidate, role='candidate', phone='919876543210', gender='female', hr=self.admin)

        response = self.client.post(reverse('add-user'), data={
            'email': 'existing@example.com',
            'name': 'Existing Candidate',
            'phone': '9876543210',
            'role': 'Candidate',
            'profile': str(self.role.id),
            'gender': 'female',
            'recruiter': str(self.recruiter.id),
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['Success'])
        self.assertFalse(payload['SignupRequired'])
        self.assertTrue(payload['CandidateExists'])
        self.assertIn('Python Developer', payload['Notification']['message'])
        self.assertTrue(payload['Notification']['channels']['sms']['sent'])
        self.assertTrue(payload['Notification']['channels']['whatsapp']['sent'])
        self.assertTrue(send_sms_mock.called)
        self.assertTrue(send_whatsapp_mock.called)

    def test_candidate_signup_completes_profile(self):
        candidate = User.objects.create_user(username='cand2', email='signup@example.com')
        candidate.set_unusable_password()
        candidate.first_name = 'Signup'
        candidate.last_name = 'Candidate'
        candidate.save()
        profile = UserProfile.objects.create(user=candidate, role='candidate', phone='919123456789', gender='female', hr=self.admin)
        interview = Interview.objects.create(candidate=candidate, recruiter=self.recruiter, hr=self.admin, status='assessment_pending', role=self.role)

        token = signing.dumps({
            'user_id': candidate.id,
            'interview_id': interview.id,
            'name': 'Signup Candidate',
            'email': candidate.email,
            'phone': profile.phone,
            'gender': profile.gender,
            'role_id': self.role.id,
            'role_name': self.role.role,
        }, salt=SIGNUP_TOKEN_SALT)

        get_response = self.client.get(reverse('candidate-signup'), {'token': token})
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'Signup Candidate')
        self.assertContains(get_response, 'Upload Resume')

        resume = SimpleUploadedFile('resume.pdf', b'%PDF-1.4 fake content', content_type='application/pdf')
        profile_photo = SimpleUploadedFile(
            'profile.jpg',
            (
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
                b'\xff\xdb\x00C\x00'
            ),
            content_type='image/jpeg',
        )
        post_response = self.client.post(reverse('candidate-signup'), data={
            'token': token,
            'password': 'StrongPass123!',
            'confirm_password': 'StrongPass123!',
            'profile_picture': profile_photo,
            'resume': resume,
        })

        self.assertEqual(post_response.status_code, 200)
        candidate.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(candidate.has_usable_password())
        self.assertTrue(profile.profile_picture.name.endswith('profile.jpg'))
        self.assertTrue(profile.resume.name.endswith('resume.pdf'))

    @patch('smartInterviewApp.commonViews.ResumeProcessingService.process_profile_resume')
    def test_candidate_signup_allows_manual_profile_creation_without_token(self, process_resume_mock):
        get_response = self.client.get(reverse('candidate-signup'))

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'Create your candidate profile manually')
        self.assertContains(get_response, 'First Name')

        resume = SimpleUploadedFile('manual_resume.pdf', b'%PDF-1.4 fake content', content_type='application/pdf')
        profile_photo = SimpleUploadedFile(
            'manual_profile.jpg',
            (
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
                b'\xff\xdb\x00C\x00'
            ),
            content_type='image/jpeg',
        )
        post_response = self.client.post(reverse('candidate-signup'), data={
            'first_name': 'Manual',
            'last_name': 'Candidate',
            'email': 'manual@example.com',
            'phone': '9876543210',
            'gender': 'male',
            'password': 'StrongPass123!',
            'confirm_password': 'StrongPass123!',
            'profile_picture': profile_photo,
            'resume': resume,
        })

        self.assertEqual(post_response.status_code, 200)
        candidate = User.objects.get(email='manual@example.com')
        profile = candidate.profile
        self.assertEqual(candidate.first_name, 'Manual')
        self.assertEqual(candidate.last_name, 'Candidate')
        self.assertTrue(candidate.has_usable_password())
        self.assertEqual(profile.role, 'candidate')
        self.assertEqual(profile.phone, '9876543210')
        self.assertEqual(profile.gender, 'male')
        self.assertTrue(profile.profile_picture.name.endswith('manual_profile.jpg'))
        self.assertTrue(profile.resume.name.endswith('manual_resume.pdf'))
        process_resume_mock.assert_called_once_with(candidate, profile, interview=None)

    def test_candidate_signup_invalid_token_falls_back_to_manual_form(self):
        response = self.client.get(reverse('candidate-signup'), {'token': 'bad-token'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalid or has expired')
        self.assertContains(response, 'First Name')


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class PublicJobsPortalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin-jobs', password='pass1234', email='admin.jobs@example.com')
        self.admin.first_name = 'Admin'
        self.admin.last_name = 'Jobs'
        self.admin.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.admin, role='admin', phone='919999999991', gender='other')

        self.recruiter = User.objects.create_user(username='recruiter-jobs', password='pass1234', email='recruiter.jobs@example.com')
        self.recruiter.first_name = 'Riya'
        self.recruiter.last_name = 'Singh'
        self.recruiter.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.recruiter, role='recruiter', phone='919999999992', gender='female', hr=self.admin)

        self.candidate = User.objects.create_user(username='candidate-jobs', password='pass1234', email='candidate.jobs@example.com')
        self.candidate.first_name = 'Test'
        self.candidate.last_name = 'Candidate'
        self.candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.candidate, role='candidate', phone='919999999993', gender='male', hr=self.admin)

        self.vacancy = Vacancies.objects.create(
            role='Backend Python Developer',
            description='Build Django APIs\nWork with recruiters\nImprove hiring workflows',
            position='3',
            status='active',
            admin=self.admin,
        )
        self.vacancy.recruiter.add(self.recruiter)

    def test_jobs_portal_is_public_and_shows_login_cta_for_apply(self):
        response = self.client.get(reverse('jobs-portal'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Backend Python Developer')
        self.assertContains(response, 'Login to Apply')

    def test_candidate_login_honors_next_for_jobs_portal(self):
        response = self.client.post(reverse('candidate-login'), data={
            'username': self.candidate.email,
            'password': 'pass1234',
            'next': reverse('jobs-portal'),
        })

        self.assertRedirects(response, reverse('jobs-portal'))

    def test_jobs_portal_shows_candidate_application_state(self):
        CandidateVacancyApplication.objects.create(
            candidate=self.candidate,
            vacancy=self.vacancy,
            status=CandidateVacancyApplication.Status.PENDING_REVIEW,
        )
        self.client.login(username='candidate-jobs', password='pass1234')

        response = self.client.get(reverse('jobs-portal'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pending Review')
        self.assertContains(response, 'Withdraw')

    def test_candidate_can_save_vacancy_and_see_saved_section(self):
        self.client.login(username='candidate-jobs', password='pass1234')

        save_response = self.client.post(reverse('candidate-save-vacancy'), data={'vacancy_id': self.vacancy.id})

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_response.json()['Success'])
        self.assertTrue(CandidateSavedVacancy.objects.filter(candidate=self.candidate, vacancy=self.vacancy).exists())

        page_response = self.client.get(reverse('jobs-portal'))

        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, 'Saved Postings')
        self.assertContains(page_response, 'Remove Saved')
