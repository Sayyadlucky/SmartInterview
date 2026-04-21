from __future__ import annotations

from datetime import timedelta
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from smartInterviewApp.integrations.providers.contracts import ProviderResult
from smartInterviewApp.api.serializers import ExotelWebhookSerializer
from smartInterviewApp.integrations.providers.msg91 import Msg91OtpProvider, Msg91SmsProvider
from smartInterviewApp.models import AutoInterviewEvaluationResult, Notification, NotificationAttempt, OtpRequest, UserProfile, Vacancies, Interview, InterviewCallSession, InterviewReminderDelivery, CandidateSavedVacancy, CandidateVacancyApplication
from smartInterviewApp.notifications.services import NotificationService
from smartInterviewApp.otp.services import OtpService
from smartInterviewApp.commonViews import (
    SIGNUP_TOKEN_SALT,
    build_candidate_signup_link,
    build_litio_interview_link,
    ensure_candidate_signup_token,
    send_existing_candidate_sms,
)
from smartInterviewApp.notifications.sms_templates import build_sms_message
from smartInterviewApp.integrations.providers.meta_whatsapp import MetaWhatsappProvider
from smartInterviewApp.integrations.providers.exotel import ExotelVoiceProvider
from smartInterviewApp.services.interview_calls import InterviewCallService
from smartInterviewApp.services.interview_reminders import (
    InterviewReminderService,
    build_reminder_message,
    build_whatsapp_parameters,
    clean_value,
)


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

    def test_exotel_error_parser_extracts_rest_exception_message(self):
        provider = ExotelVoiceProvider()
        message = provider._extract_error_message(
            {'RestException': {'Message': 'CallerId is invalid', 'Code': 1234}},
            'fallback',
        )
        self.assertEqual(message, 'CallerId is invalid')

    @override_settings(
        EXOTEL_STATUS_CALLBACK_URL='https://example.com/api/webhooks/exotel/',
        EXOTEL_WEBHOOK_TOKEN='secret-token',
    )
    def test_exotel_status_callback_url_includes_webhook_token_query(self):
        provider = ExotelVoiceProvider()
        self.assertEqual(
            provider._status_callback_url(),
            'https://example.com/api/webhooks/exotel/?token=secret-token',
        )

    def test_exotel_webhook_serializer_accepts_answered_event_without_call_status(self):
        serializer = ExotelWebhookSerializer(data={
            'CallSid': 'call-123',
            'EventType': 'answered',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['provider_message_id'], 'call-123')
        self.assertEqual(serializer.validated_data['event_status'], 'answered')

    @override_settings(MSG91_AUTH_KEY='auth-key', MSG91_SENDER_ID='SLISTI', MSG91_ROUTE='4')
    @patch('smartInterviewApp.integrations.providers.msg91.post_json')
    def test_msg91_flow_sms_uses_recipients_mobiles_payload(self, post_json_mock):
        post_json_mock.return_value = (200, {'type': 'success', 'message': 'success'})

        provider = Msg91SmsProvider()
        result = provider.send_sms(
            to='919876543210',
            message='Hello test',
            metadata={
                'msg91_template_id': 'flow-123',
                'msg91_flow_variables': {'name': 'Altamash', 'role': 'Python Fullstack', 'recruiter': 'Recruiter'},
            },
        )

        self.assertTrue(result.success)
        called_payload = post_json_mock.call_args.args[1]
        self.assertEqual(called_payload['flow_id'], 'flow-123')
        self.assertEqual(called_payload['recipients'][0]['mobiles'], '919876543210')
        self.assertEqual(called_payload['recipients'][0]['name'], 'Altamash')

    @override_settings(MSG91_AUTH_KEY='auth-key', MSG91_OTP_TEMPLATE_ID='otp-template-1')
    @patch('smartInterviewApp.integrations.providers.msg91.post_json')
    def test_msg91_otp_provider_treats_invalid_template_response_as_failure(self, post_json_mock):
        post_json_mock.return_value = (200, {'type': 'error', 'message': 'Template ID Missing or Invalid Template'})

        provider = Msg91OtpProvider()
        result = provider.request_otp(phone='919876543210', otp='123456', purpose='verify_phone', expires_in_seconds=300)

        self.assertFalse(result.success)
        self.assertEqual(result.status, 'failed')

    @override_settings(MSG91_AUTH_KEY='auth-key', MSG91_OTP_TEMPLATE_ID='otp-template-1', MSG91_SENDER_ID='SLISTI', MSG91_ROUTE='4')
    @patch('smartInterviewApp.integrations.providers.msg91.post_json')
    def test_msg91_otp_provider_uses_flow_payload_with_otp_variable(self, post_json_mock):
        post_json_mock.return_value = (200, {'type': 'success', 'message': 'success'})

        provider = Msg91OtpProvider()
        result = provider.request_otp(phone='919876543210', otp='123456', purpose='verify_phone', expires_in_seconds=300)

        self.assertTrue(result.success)
        called_payload = post_json_mock.call_args.args[1]
        self.assertEqual(called_payload['flow_id'], 'otp-template-1')
        self.assertEqual(called_payload['recipients'][0]['mobiles'], '919876543210')
        self.assertEqual(called_payload['recipients'][0]['OTP'], '123456')

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

    @patch('smartInterviewApp.integrations.providers.meta_whatsapp.MetaWhatsappProvider.send_authentication_message')
    @patch('smartInterviewApp.integrations.providers.msg91.Msg91OtpProvider.request_otp')
    def test_otp_request_uses_whatsapp_authentication_template(self, request_otp_mock, whatsapp_auth_mock):
        request_otp_mock.return_value = ProviderResult(
            success=True,
            status='sent',
            provider_request_id='req-2',
            response_payload={'request_id': 'req-2'},
        )
        whatsapp_auth_mock.return_value = ProviderResult(
            success=True,
            status='sent',
            provider_message_id='wa-auth-1',
            response_payload={'messages': [{'id': 'wa-auth-1'}]},
        )

        service = OtpService()
        with patch.object(OtpService, '_generate_otp', return_value='123456'):
            req = service.request_otp(phone='9876543210', purpose='verify_phone', user=self.user)

        self.assertTrue(req['success'])
        whatsapp_auth_mock.assert_called_once_with(
            to='919876543210',
            template_name='verify_phone_otp',
            language_code='en',
            code='123456',
            metadata={'purpose': 'verify_phone', 'channel': 'whatsapp_authentication_otp'},
        )

    def test_meta_whatsapp_authentication_template_payload(self):
        provider = MetaWhatsappProvider()
        with patch.object(provider, '_send_template_payload', return_value=ProviderResult(success=True, status='sent')) as payload_mock:
            provider.send_authentication_message(
                to='919876543210',
                template_name='verify_phone_otp',
                language_code='en',
                code='123456',
            )

        payload = payload_mock.call_args.args[0]
        self.assertEqual(payload['template']['name'], 'verify_phone_otp')
        self.assertEqual(payload['template']['language']['code'], 'en')
        self.assertEqual(
            payload['template']['components'],
            [{'type': 'body', 'parameters': [{'type': 'text', 'text': '123456'}]}],
        )

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
        self.assertEqual(sms_mock.call_args.args[1], 'Interview reminder.')

    @patch('smartInterviewApp.signals.queue_candidate_reindex')
    def test_interview_save_queues_candidate_search_reindex_after_commit(self, queue_reindex_mock):
        queue_reindex_mock.return_value = {'queued': True, 'mode': 'cloud_tasks'}
        candidate = User.objects.create_user(username='cand-index', password='pass1234', email='candindex@example.com')
        UserProfile.objects.create(user=candidate, role='candidate', phone='919812345678', gender='female', hr=self.user)

        with self.captureOnCommitCallbacks(execute=True):
            Interview.objects.create(candidate=candidate, hr=self.user, status='shortlisted')

        queue_reindex_mock.assert_called_once_with(candidate.id)

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
        self.assertEqual(sms_mock.call_args.args[1], 'Critical alert. Check the dashboard immediately.')

    def test_build_sms_message_templates(self):
        self.assertIn(
            'Python Developer',
            build_sms_message('candidate_signup_invite', {
                'candidate_name': 'Asha',
                'role_name': 'Python Developer',
                'signup_url': 'https://example.com/signup',
            }),
        )
        self.assertIn(
            'Recruiter One',
            build_sms_message('candidate_interview_created', {
                'candidate_name': 'Asha',
                'role_name': 'Python Developer',
                'recruiter_name': 'Recruiter One',
            }),
        )

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


@override_settings(
    MEDIA_ROOT=tempfile.gettempdir(),
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='no-reply@example.com',
    CONTACT_SUPPORT_EMAIL='support@example.com',
)
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

        self.interviewer = User.objects.create_user(username='interviewer1', password='pass1234', email='interviewer@example.com')
        self.interviewer.first_name = 'Interviewer'
        self.interviewer.last_name = 'One'
        self.interviewer.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(
            user=self.interviewer,
            role='interviewer',
            phone='917777777777',
            gender='male',
            hr=self.admin,
            recruiter=self.recruiter,
        )

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
        self.assertIn('/s/', payload['Notification']['signup_url'])
        self.assertLessEqual(len(payload['Notification']['signup_token']), 16)
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

    @patch('smartInterviewApp.commonViews.send_template_message')
    @patch('smartInterviewApp.commonViews.send_sms')
    def test_existing_candidate_whatsapp_interview_template_uses_three_body_parameters(self, send_sms_mock, send_whatsapp_mock):
        send_sms_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='sms-existing')
        send_whatsapp_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='wa-existing')

        candidate = User.objects.create_user(username='cand-wa', password='pass1234', email='candwa@example.com')
        candidate.first_name = 'Existing'
        candidate.last_name = 'Candidate'
        candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=candidate, role='candidate', phone='919876543210', gender='female', hr=self.admin)

        interview = Interview.objects.create(
            candidate=candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
        )

        result = send_existing_candidate_sms(candidate, interview)

        self.assertTrue(send_whatsapp_mock.called)
        interview.refresh_from_db()
        self.assertTrue(result['interview_token'])
        self.assertEqual(interview.litio_interview_token, result['interview_token'])
        self.assertLessEqual(len(result['interview_token']), 16)
        self.assertTrue(result['interview_link'].startswith('https://litio.shortlistii.com/i/'))
        components = send_whatsapp_mock.call_args.kwargs['components']
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]['type'], 'body')
        parameters = components[0]['parameters']
        self.assertEqual(len(parameters), 3)
        self.assertEqual(
            [item['text'] for item in parameters],
            ['Existing', 'Python Developer', 'Recruiter One']
        )
        self.assertEqual(len(mail.outbox), 1)
        sent_message = mail.outbox[0]
        self.assertEqual(sent_message.to, ['candwa@example.com'])
        self.assertEqual(sent_message.subject, 'Interview Scheduled: Python Developer | Shortlistii')
        self.assertIn('https://litio.shortlistii.com/i/', sent_message.body)
        self.assertEqual(sent_message.alternatives[0][1], 'text/html')
        self.assertIn('Open Interview Link', sent_message.alternatives[0][0])

    @patch('smartInterviewApp.commonViews.send_template_message')
    @patch('smartInterviewApp.commonViews.send_sms')
    def test_existing_candidate_rescheduled_interview_email_includes_previous_schedule(self, send_sms_mock, send_whatsapp_mock):
        send_sms_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='sms-existing')
        send_whatsapp_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='wa-existing')

        candidate = User.objects.create_user(username='cand-reschedule', password='pass1234', email='candreschedule@example.com')
        candidate.first_name = 'Existing'
        candidate.last_name = 'Candidate'
        candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=candidate, role='candidate', phone='919876543210', gender='female', hr=self.admin)

        previous_time = timezone.now() + timedelta(days=1)
        interview = Interview.objects.create(
            candidate=candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
            date=previous_time + timedelta(hours=2),
        )

        result = send_existing_candidate_sms(
            candidate,
            interview,
            request=None,
            notification_kind='rescheduled',
            previous_scheduled_at=previous_time,
        )

        self.assertTrue(result['channels']['email']['sent'])
        self.assertEqual(len(mail.outbox), 1)
        sent_message = mail.outbox[0]
        self.assertEqual(sent_message.subject, 'Interview Rescheduled: Python Developer | Shortlistii')
        self.assertIn('Previous Schedule:', sent_message.body)

    def test_build_litio_interview_link_normalizes_old_token_and_uses_public_domain(self):
        interview = Interview.objects.create(
            candidate=self.candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
            litio_interview_token='BDF7rdBltZdxYUXPxzrH0DyjvboVqNNr',
        )

        token, link = build_litio_interview_link(None, interview)

        self.assertNotEqual(token, 'BDF7rdBltZdxYUXPxzrH0DyjvboVqNNr')
        self.assertLessEqual(len(token), 16)
        self.assertTrue(link.startswith('https://litio.shortlistii.com/i/'))
        interview.refresh_from_db()
        self.assertEqual(interview.litio_interview_token, token)

    def test_build_candidate_signup_link_uses_short_candidate_domain_path(self):
        interview = Interview.objects.create(
            candidate=self.candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='assessment_pending',
        )

        token, link = build_candidate_signup_link(None, interview)

        self.assertLessEqual(len(token), 16)
        self.assertTrue(link.startswith('https://candidates.shortlistii.com/s/'))
        interview.refresh_from_db()
        self.assertEqual(interview.candidate_signup_token, token)
        self.assertIsNotNone(interview.candidate_signup_token_created_at)

    @patch('smartInterviewApp.commonViews.exotel_voice_provider.connect_agent_to_candidate')
    def test_candidate_profile_call_connects_workspace_user_and_candidate(self, call_mock):
        call_mock.return_value = ProviderResult(
            success=True,
            status='sent',
            provider_message_id='call-123',
            response_payload={'Call': {'Sid': 'call-123'}},
        )

        candidate = User.objects.create_user(username='cand-call', password='pass1234', email='candcall@example.com')
        candidate.first_name = 'Call'
        candidate.last_name = 'Candidate'
        candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=candidate, role='candidate', phone='919876543210', gender='female', hr=self.admin)

        interview = Interview.objects.create(
            candidate=candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
        )

        response = self.client.post(reverse('candidate-profile-call', args=[interview.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['Success'])
        self.assertEqual(payload['Data']['call_sid'], 'call-123')
        self.assertTrue(payload['Data']['session']['id'])
        session = InterviewCallSession.objects.get(id=payload['Data']['session']['id'])
        self.assertEqual(session.exotel_call_sid, 'call-123')
        self.assertEqual(session.status, InterviewCallSession.Status.DIALING_AGENT)
        call_mock.assert_called_once_with(
            agent_phone='919999999999',
            candidate_phone='919876543210',
            interview_id=interview.id,
            metadata={'TimeLimit': '900'},
        )

    def test_interview_call_service_create_session_starts_in_dialing_agent(self):
        candidate = User.objects.create_user(username='cand-call-create', password='pass1234', email='candcallcreate@example.com')
        UserProfile.objects.create(user=candidate, role='candidate', phone='919876543210', gender='female', hr=self.admin)
        interview = Interview.objects.create(
            candidate=candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
        )

        session = InterviewCallService().create_session(
            interview=interview,
            initiated_by=self.admin,
            caller_phone='919999999999',
            candidate_phone='919876543210',
            provider_result=ProviderResult(
                success=True,
                status='sent',
                provider_message_id='call-xyz',
                response_payload={'Call': {'Sid': 'call-xyz', 'Status': 'queued'}},
            ),
        )

        self.assertEqual(session.status, InterviewCallSession.Status.DIALING_AGENT)
        self.assertEqual(session.exotel_call_sid, 'call-xyz')
        self.assertIsNone(session.billing_started_at)
        self.assertIsNone(session.candidate_connected_at)

    @override_settings(
        NOTIFICATION_PROVIDER_MODE='live',
        EXOTEL_MOCK_MODE=False,
        EXOTEL_SID='sid-123',
        EXOTEL_API_KEY='api-key-123',
        EXOTEL_TOKEN='token-123',
        EXOTEL_CALLER_ID='0800000000',
        EXOTEL_SUBDOMAIN="os.getenv('EXOTEL_SUBDOMAIN', 'api.exotel.com')",
    )
    def test_candidate_profile_call_invalid_exotel_host_returns_config_error(self):
        candidate = User.objects.create_user(username='cand-call-bad-host', password='pass1234', email='candcallbadhost@example.com')
        candidate.first_name = 'Call'
        candidate.last_name = 'Candidate'
        candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=candidate, role='candidate', phone='919876543210', gender='female', hr=self.admin)

        interview = Interview.objects.create(
            candidate=candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
        )

        response = self.client.post(reverse('candidate-profile-call', args=[interview.id]))

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload['Success'])
        self.assertIn('EXOTEL_SUBDOMAIN is invalid', payload['Error'])
        self.assertEqual(InterviewCallSession.objects.count(), 0)

    @override_settings(
        NOTIFICATION_PROVIDER_MODE='live',
        EXOTEL_MOCK_MODE=False,
        EXOTEL_SID='sid-123',
        EXOTEL_API_KEY='',
        EXOTEL_TOKEN='token-123',
        EXOTEL_CALLER_ID='0800000000',
        EXOTEL_SUBDOMAIN='api.in.exotel.com',
    )
    def test_candidate_profile_call_requires_exotel_api_key(self):
        candidate = User.objects.create_user(username='cand-call-missing-key', password='pass1234', email='candcallmissingkey@example.com')
        candidate.first_name = 'Call'
        candidate.last_name = 'Candidate'
        candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=candidate, role='candidate', phone='919876543210', gender='female', hr=self.admin)

        interview = Interview.objects.create(
            candidate=candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
        )

        response = self.client.post(reverse('candidate-profile-call', args=[interview.id]))

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload['Success'])
        self.assertIn('EXOTEL_API_KEY', payload['Error'])

    def test_candidate_profile_call_session_status_returns_session(self):
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-123',
            status=InterviewCallSession.Status.DIALING_AGENT,
            caller_phone='919999999999',
            candidate_phone='919111111111',
        )

        response = self.client.get(reverse('candidate-profile-call-session', args=[self.interview.id, session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        self.assertEqual(response.json()['Data']['status'], InterviewCallSession.Status.DIALING_AGENT)

    def test_interview_call_sync_uses_top_level_call_detail_durations(self):
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-123',
            status=InterviewCallSession.Status.DIALING_AGENT,
            caller_phone='919999999999',
            candidate_phone='919876543210',
        )

        payload = {
            'Call': {
                'Sid': 'call-123',
                'Status': 'completed',
                'StartTime': '2026-04-09 09:00:00',
                'EndTime': '2026-04-09 09:05:00',
                'Duration': '300',
                'ConversationDuration': '240',
            }
        }

        synced = InterviewCallService().sync_session(session, payload=payload)

        self.assertEqual(synced.status, InterviewCallSession.Status.COMPLETED)
        self.assertEqual(synced.billable_seconds, 300)
        self.assertEqual(synced.connected_seconds, 240)
        self.assertIsNotNone(synced.billing_started_at)
        self.assertIsNotNone(synced.candidate_connected_at)

    def test_interview_call_sync_marks_connecting_candidate_when_first_leg_is_live(self):
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-124',
            status=InterviewCallSession.Status.DIALING_AGENT,
            caller_phone='919999999999',
            candidate_phone='919876543210',
        )

        payload = {
            'Call': {
                'Sid': 'call-124',
                'Status': 'in-progress',
                'StartTime': '2026-04-09 09:00:00',
                'Duration': '18',
                'ConversationDuration': '0',
            }
        }

        synced = InterviewCallService().sync_session(session, payload=payload)

        self.assertEqual(synced.status, InterviewCallSession.Status.CONNECTING_CANDIDATE)
        self.assertIsNotNone(synced.billing_started_at)
        self.assertEqual(synced.connected_seconds, 0)

    @override_settings(EXOTEL_TIMEZONE='Asia/Kolkata')
    def test_interview_call_sync_treats_exotel_naive_timestamps_as_india_time(self):
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-126',
            status=InterviewCallSession.Status.DIALING_AGENT,
            caller_phone='919999999999',
            candidate_phone='919876543210',
        )

        payload = {
            'Call': {
                'Sid': 'call-126',
                'Status': 'in-progress',
                'StartTime': '2026-04-09 12:00:00',
                'Duration': '10',
                'ConversationDuration': '0',
            }
        }

        synced = InterviewCallService().sync_session(session, payload=payload)

        self.assertIsNotNone(synced.billing_started_at)
        self.assertEqual(timezone.localtime(synced.billing_started_at).hour, 12)
        self.assertEqual(timezone.localtime(synced.billing_started_at).minute, 0)

    def test_interview_call_sync_marks_in_progress_when_candidate_leg_is_live(self):
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-127',
            status=InterviewCallSession.Status.CONNECTING_CANDIDATE,
            caller_phone='919999999999',
            candidate_phone='919876543210',
            billing_started_at=timezone.now() - timedelta(seconds=20),
            billable_seconds=20,
        )

        payload = {
            'Call': {
                'Sid': 'call-127',
                'Status': 'in-progress',
                'Leg1Status': 'in-progress',
                'Leg2Status': 'answered',
                'Duration': '20',
                'ConversationDuration': '5',
            }
        }

        synced = InterviewCallService().sync_session(session, payload=payload)

        self.assertEqual(synced.status, InterviewCallSession.Status.IN_PROGRESS)
        self.assertIsNotNone(synced.candidate_connected_at)

    def test_interview_call_webhook_debug_summary_is_serialized(self):
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-128',
            status=InterviewCallSession.Status.CONNECTING_CANDIDATE,
            caller_phone='919999999999',
            candidate_phone='919876543210',
            provider_response={
                'webhook_events': [
                    {'received_at': '2026-04-09T12:00:00+05:30', 'payload': {'EventType': 'answered', 'CallSid': 'call-128'}},
                ]
            },
        )

        payload = InterviewCallService().serialize_session(session)

        self.assertEqual(payload['webhook_event_count'], 1)
        self.assertEqual(payload['last_webhook_event_type'], 'answered')

    def test_interview_call_sync_marks_disconnected_after_billable_leg_ends_without_candidate(self):
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-125',
            status=InterviewCallSession.Status.CONNECTING_CANDIDATE,
            caller_phone='919999999999',
            candidate_phone='919876543210',
            billing_started_at=timezone.now() - timedelta(seconds=42),
            billable_seconds=42,
        )

        payload = {
            'Call': {
                'Sid': 'call-125',
                'Status': 'completed',
                'StartTime': '2026-04-09 09:00:00',
                'EndTime': '2026-04-09 09:00:42',
                'Duration': '42',
                'ConversationDuration': '0',
            }
        }

        synced = InterviewCallService().sync_session(session, payload=payload)

        self.assertEqual(synced.status, InterviewCallSession.Status.DISCONNECTED)
        self.assertEqual(synced.connected_seconds, 0)

    @patch('smartInterviewApp.commonViews.interview_call_service.provider.disconnect_call')
    def test_candidate_profile_disconnect_updates_session(self, disconnect_mock):
        disconnect_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='call-123', response_payload={'Call': {'Sid': 'call-123', 'Status': 'completed'}})
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-123',
            status=InterviewCallSession.Status.IN_PROGRESS,
            caller_phone='919999999999',
            candidate_phone='919876543210',
            billing_started_at=timezone.now(),
        )

        response = self.client.post(reverse('candidate-profile-call-disconnect', args=[self.interview.id, session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        session.refresh_from_db()
        self.assertIsNotNone(session.disconnect_requested_at)

    @patch('smartInterviewApp.commonViews.interview_call_service.provider.disconnect_call')
    def test_candidate_profile_disconnect_failure_does_not_mark_disconnect_requested(self, disconnect_mock):
        disconnect_mock.return_value = ProviderResult(
            success=False,
            status='failed',
            provider_message_id='call-123',
            response_payload={'message': 'Method not allowed'},
            error_message='Method not allowed',
        )
        session = InterviewCallSession.objects.create(
            interview=self.interview,
            initiated_by=self.admin,
            exotel_call_sid='call-123',
            status=InterviewCallSession.Status.IN_PROGRESS,
            caller_phone='919999999999',
            candidate_phone='919876543210',
            billing_started_at=timezone.now(),
        )

        response = self.client.post(reverse('candidate-profile-call-disconnect', args=[self.interview.id, session.id]))

        self.assertEqual(response.status_code, 502)
        session.refresh_from_db()
        self.assertIsNone(session.disconnect_requested_at)
        self.assertIn('does not allow ending this live call', session.error_message)

    @patch('smartInterviewApp.commonViews.ResumeProcessingService.process_profile_resume')
    def test_candidate_signup_completes_profile(self, process_resume_mock):
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
        process_resume_mock.assert_called_once_with(candidate, profile, interview=interview)
        self.assertEqual(len(mail.outbox), 1)
        sent_message = mail.outbox[0]
        self.assertEqual(sent_message.to, ['signup@example.com'])
        self.assertEqual(sent_message.subject, 'Welcome to Shortlistii, your Python Developer profile is ready')
        self.assertIn('Python Developer', sent_message.body)
        self.assertEqual(sent_message.alternatives[0][1], 'text/html')
        self.assertIn('Candidate account ready', sent_message.alternatives[0][0])

    @patch('smartInterviewApp.commonViews.ResumeProcessingService.process_profile_resume')
    def test_candidate_signup_short_link_completes_profile(self, process_resume_mock):
        candidate = User.objects.create_user(username='cand-short', email='signup.short@example.com')
        candidate.set_unusable_password()
        candidate.first_name = 'Short'
        candidate.last_name = 'Candidate'
        candidate.save()
        profile = UserProfile.objects.create(user=candidate, role='candidate', phone='919123456780', gender='female', hr=self.admin)
        interview = Interview.objects.create(candidate=candidate, recruiter=self.recruiter, hr=self.admin, status='assessment_pending', role=self.role)
        short_token = ensure_candidate_signup_token(interview)

        get_response = self.client.get(reverse('candidate-signup-short-root', args=[short_token]))
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'Short Candidate')
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
        post_response = self.client.post(reverse('candidate-signup-short-root', args=[short_token]), data={
            'token': short_token,
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
        process_resume_mock.assert_called_once_with(candidate, profile, interview=interview)

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
        self.assertEqual(len(mail.outbox), 1)
        sent_message = mail.outbox[0]
        self.assertEqual(sent_message.to, ['manual@example.com'])
        self.assertEqual(sent_message.subject, 'Welcome to Shortlistii')
        self.assertIn('manual@example.com', candidate.email)
        self.assertIn('Open your candidate portal', sent_message.body)
        self.assertEqual(sent_message.alternatives[0][1], 'text/html')

    @patch('smartInterviewApp.emailing.EmailMultiAlternatives.send', side_effect=RuntimeError('mail backend unavailable'))
    @patch('smartInterviewApp.commonViews.ResumeProcessingService.process_profile_resume')
    def test_candidate_signup_mail_failure_does_not_block_signup(self, process_resume_mock, email_send_mock):
        post_response = self.client.post(reverse('candidate-signup'), data={
            'first_name': 'Email',
            'last_name': 'Fallback',
            'email': 'email.fallback@example.com',
            'phone': '9876543210',
            'gender': 'female',
            'password': 'StrongPass123!',
            'confirm_password': 'StrongPass123!',
        })

        self.assertEqual(post_response.status_code, 200)
        candidate = User.objects.get(email='email.fallback@example.com')
        self.assertTrue(candidate.has_usable_password())
        process_resume_mock.assert_not_called()
        email_send_mock.assert_called_once()
        self.assertEqual(len(mail.outbox), 0)

    def test_candidate_signup_reopens_security_step_when_password_validation_fails(self):
        response = self.client.post(reverse('candidate-signup'), data={
            'first_name': 'Step',
            'last_name': 'Recovery',
            'email': 'step.recovery@example.com',
            'phone': '9876543210',
            'gender': 'female',
            'password': 'StrongPass123!',
            'confirm_password': 'StrongPass124!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Passwords do not match.')
        self.assertContains(response, 'data-initial-step="2"')

    def test_candidate_signup_invalid_token_falls_back_to_manual_form(self):
        response = self.client.get(reverse('candidate-signup'), {'token': 'bad-token'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalid or has expired')
        self.assertContains(response, 'First Name')


class CandidateRoutingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin-route', password='pass1234', email='admin.route@example.com')
        self.admin.first_name = 'Admin'
        self.admin.last_name = 'Route'
        self.admin.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.admin, role='admin', phone='919111111112', gender='other')

        self.recruiter = User.objects.create_user(username='recruiter-route', password='pass1234', email='recruiter.route@example.com')
        self.recruiter.first_name = 'Recruiter'
        self.recruiter.last_name = 'Route'
        self.recruiter.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.recruiter, role='recruiter', phone='919111111113', gender='male', hr=self.admin)

        self.interviewer = User.objects.create_user(username='interviewer-route', password='pass1234', email='interviewer.route@example.com')
        self.interviewer.first_name = 'Interviewer'
        self.interviewer.last_name = 'Route'
        self.interviewer.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(
            user=self.interviewer,
            role='interviewer',
            phone='919111111114',
            gender='male',
            hr=self.admin,
            recruiter=self.recruiter,
        )

        self.role = Vacancies.objects.create(
            role='Python Developer',
            description='Backend role',
            position='2',
            status='active',
            admin=self.admin,
        )
        self.role.recruiter.add(self.recruiter)

        self.candidate = User.objects.create_user(
            username='candidate-route',
            password='pass1234',
            email='candidate.route@example.com',
        )
        UserProfile.objects.create(
            user=self.candidate,
            role='candidate',
            phone='919111111111',
            gender='female',
            hr=self.admin,
        )
        self.client.login(username='admin-route', password='pass1234')

    def test_main_home_redirects_authenticated_candidate_to_candidate_domain(self):
        self.client.force_login(self.candidate)

        response = self.client.get('/', secure=True, HTTP_HOST='shortlistii.com')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://candidates.shortlistii.com/')

    def test_dashboard_redirects_candidate_to_candidate_domain(self):
        self.client.force_login(self.candidate)

        response = self.client.get('/dashboard/', secure=True, HTTP_HOST='shortlistii.com')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://candidates.shortlistii.com/')

    def test_ajax_login_returns_candidate_domain_redirect_for_candidate(self):
        response = self.client.post('/login/', data={
            'username': 'candidate.route@example.com',
            'password': 'pass1234',
        }, secure=True, HTTP_HOST='shortlistii.com')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['redirect_url'], 'https://candidates.shortlistii.com/')

    def test_hr_and_admin_dashboard_data_include_interviewer_hierarchy(self):
        candidate = User.objects.create_user(username='cand-hierarchy', password='pass1234', email='hierarchy@example.com')
        candidate.first_name = 'Hierarchy'
        candidate.last_name = 'Candidate'
        candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=candidate, role='candidate', phone='919555555555', gender='female', hr=self.admin)

        interview = Interview.objects.create(
            candidate=candidate,
            recruiter=self.recruiter,
            interviewer=self.interviewer,
            hr=self.admin,
            status='scheduled',
            role=self.role,
        )

        admin_eval_response = self.client.get(reverse('get-evaluator'))
        self.assertEqual(admin_eval_response.status_code, 200)
        admin_eval_payload = admin_eval_response.json()
        self.assertTrue(admin_eval_payload['Success'])
        self.assertEqual(admin_eval_payload['RecruiterData'][0]['email'], self.interviewer.email)

        admin_candidates_response = self.client.get(reverse('candidates-tab-data'))
        self.assertEqual(admin_candidates_response.status_code, 200)
        admin_candidates_payload = admin_candidates_response.json()
        self.assertTrue(admin_candidates_payload['Success'])
        self.assertEqual(admin_candidates_payload['Data']['candidates'][0]['interviewer'], 'Interviewer One')
        self.assertEqual(admin_candidates_payload['Data']['candidates'][0]['recruiter'], 'Recruiter One')

        self.client.logout()
        self.client.login(username='recruiter1', password='pass1234')

        hr_eval_response = self.client.get(reverse('get-evaluator'))
        self.assertEqual(hr_eval_response.status_code, 200)
        hr_eval_payload = hr_eval_response.json()
        self.assertTrue(hr_eval_payload['Success'])
        self.assertEqual(hr_eval_payload['RecruiterData'][0]['email'], self.interviewer.email)

        hr_profile_response = self.client.post(reverse('get-evaluator-profile'), data={'recruiter_id': self.interviewer.profile.id})
        self.assertEqual(hr_profile_response.status_code, 200)
        hr_profile_payload = hr_profile_response.json()
        self.assertTrue(hr_profile_payload['Success'])
        self.assertEqual(hr_profile_payload['Interviews'][0]['candidate'], 'Hierarchy Candidate')
        self.assertEqual(hr_profile_payload['Interviews'][0]['recruiter'], 'Recruiter One')


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

    def test_jobs_portal_limits_default_feed_to_top_ten_roles(self):
        for index in range(12):
            vacancy = Vacancies.objects.create(
                role=f'Backend Python Developer {index}',
                description='Performance-sensitive landing role',
                position='1',
                status='active',
                admin=self.admin,
            )
            vacancy.recruiter.add(self.recruiter)

        response = self.client.get(reverse('jobs-portal'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['job_cards']), 10)

    def test_jobs_portal_search_returns_full_matching_result_set(self):
        for index in range(12):
            vacancy = Vacancies.objects.create(
                role=f'Backend Python Developer Search {index}',
                description='Searchable role for portal filtering',
                position='1',
                status='active',
                admin=self.admin,
            )
            vacancy.recruiter.add(self.recruiter)

        response = self.client.get(reverse('jobs-portal'), {'q': 'Backend Python Developer'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['job_cards']), 13)

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

    @patch('smartInterviewApp.commonViews.verify_otp')
    @patch('smartInterviewApp.commonViews.request_otp')
    def test_candidate_password_reset_flow_updates_password(self, request_otp_mock, verify_otp_mock):
        request_otp_mock.return_value = {'success': True, 'message': 'OTP sent.'}
        verify_otp_mock.return_value = {'success': True, 'message': 'OTP verified.'}

        start_response = self.client.post(reverse('candidate-password-reset-start'), data={'email': self.candidate.email})
        self.assertEqual(start_response.status_code, 200)
        self.assertTrue(start_response.json()['Success'])
        self.assertEqual(start_response.json()['Data']['last_four'], '9993')

        phone_response = self.client.post(reverse('candidate-password-reset-verify-phone'), data={'phone': '919999999993'})
        self.assertEqual(phone_response.status_code, 200)
        self.assertTrue(phone_response.json()['Success'])
        request_otp_mock.assert_called_once()

        otp_response = self.client.post(reverse('candidate-password-reset-verify-otp'), data={'otp': '123456'})
        self.assertEqual(otp_response.status_code, 200)
        self.assertTrue(otp_response.json()['Success'])
        verify_otp_mock.assert_called_once_with(phone='919999999993', otp='123456', purpose='password_reset')

        complete_response = self.client.post(reverse('candidate-password-reset-complete'), data={
            'password': 'ResetPass#2026',
            'confirm_password': 'ResetPass#2026',
        })
        self.assertEqual(complete_response.status_code, 200)
        self.assertTrue(complete_response.json()['Success'])

        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.check_password('ResetPass#2026'))

    @patch('smartInterviewApp.commonViews.verify_otp')
    @patch('smartInterviewApp.commonViews.request_otp')
    def test_candidate_password_reset_rejects_mismatched_passwords(self, request_otp_mock, verify_otp_mock):
        request_otp_mock.return_value = {'success': True, 'message': 'OTP sent.'}
        verify_otp_mock.return_value = {'success': True, 'message': 'OTP verified.'}

        self.client.post(reverse('candidate-password-reset-start'), data={'email': self.candidate.email})
        self.client.post(reverse('candidate-password-reset-verify-phone'), data={'phone': '919999999993'})
        self.client.post(reverse('candidate-password-reset-verify-otp'), data={'otp': '123456'})

        response = self.client.post(reverse('candidate-password-reset-complete'), data={
            'password': 'ResetPass#2026',
            'confirm_password': 'MismatchPass#2026',
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['Success'])
        self.assertEqual(response.json()['Error'], 'Passwords do not match.')


@override_settings(
    CLOUD_TASKS_SHARED_SECRET='task-secret',
    GCP_PROJECT_ID='demo-project',
    GCP_LOCATION='asia-south1',
    CLOUD_TASKS_QUEUE='interview-reminders',
    CLOUD_RUN_BASE_URL='https://shortlistii.run.app',
    MSG91_INTERVIEW_REMINDER_ONE_HOUR_TEMPLATE_ID='sms_template_60',
    MSG91_INTERVIEW_REMINDER_THIRTY_MIN_TEMPLATE_ID='sms_template_30',
    MSG91_INTERVIEW_REMINDER_FIFTEEN_MIN_TEMPLATE_ID='sms_template_15',
    INTERVIEW_REMINDER_ONE_HOUR_WHATSAPP_TEMPLATE='interview_reminder_one_hour',
    INTERVIEW_REMINDER_THIRTY_MIN_WHATSAPP_TEMPLATE='interview_reminder_thirty_min',
    INTERVIEW_REMINDER_FIFTEEN_MIN_WHATSAPP_TEMPLATE='interview_reminder_fifteen_min',
)
class InterviewReminderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin-reminder', password='pass1234', email='admin.reminder@example.com')
        self.admin.first_name = 'Admin'
        self.admin.last_name = 'Reminder'
        self.admin.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.admin, role='admin', phone='919999999999', gender='other')

        self.recruiter = User.objects.create_user(username='recruiter-reminder', password='pass1234', email='recruiter.reminder@example.com')
        self.recruiter.first_name = 'Recruiter'
        self.recruiter.last_name = 'Reminder'
        self.recruiter.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.recruiter, role='recruiter', phone='918888888888', gender='male', hr=self.admin)

        self.interviewer = User.objects.create_user(username='interviewer-reminder', password='pass1234', email='interviewer.reminder@example.com')
        self.interviewer.first_name = 'Evaluator'
        self.interviewer.last_name = 'Reminder'
        self.interviewer.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(
            user=self.interviewer,
            role='interviewer',
            phone='917777777777',
            gender='male',
            hr=self.admin,
            recruiter=self.recruiter,
        )

        self.candidate = User.objects.create_user(username='candidate-reminder', password='pass1234', email='candidate.reminder@example.com')
        self.candidate.first_name = 'Asha'
        self.candidate.last_name = 'Verma'
        self.candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.candidate, role='candidate', phone='919111111111', gender='female', hr=self.admin)

        self.role = Vacancies.objects.create(
            role='Python Developer',
            description='Backend role',
            position='2',
            status='active',
            admin=self.admin,
        )
        self.role.recruiter.add(self.recruiter)
        self.interview = Interview.objects.create(
            candidate=self.candidate,
            recruiter=self.recruiter,
            interviewer=self.interviewer,
            hr=self.admin,
            role=self.role,
            status='scheduled',
            date=timezone.now() + timedelta(hours=2),
        )
        self.client.login(username='admin-reminder', password='pass1234')

    @patch('smartInterviewApp.services.interview_reminders.cloud_tasks_scheduler.create_http_task')
    def test_schedule_creates_six_reminder_records_and_tasks(self, create_task_mock):
        create_task_mock.side_effect = [f'task-{idx}' for idx in range(6)]

        deliveries = InterviewReminderService().schedule_interview_reminders(self.interview)

        self.assertEqual(len(deliveries), 6)
        self.assertEqual(InterviewReminderDelivery.objects.filter(interview=self.interview).count(), 6)
        self.assertEqual(create_task_mock.call_count, 6)
        self.assertEqual(
            InterviewReminderDelivery.objects.filter(interview=self.interview, status=InterviewReminderDelivery.Status.PENDING).count(),
            6,
        )

    @patch('smartInterviewApp.services.interview_reminders.cloud_tasks_scheduler.create_http_task')
    @patch('smartInterviewApp.services.interview_reminders.cloud_tasks_scheduler.delete_task')
    def test_reschedule_cancels_old_reminders_and_creates_new_ones(self, delete_task_mock, create_task_mock):
        create_task_mock.side_effect = [f'task-{idx}' for idx in range(12)]
        service = InterviewReminderService()
        service.schedule_interview_reminders(self.interview)

        old_time = self.interview.date
        self.interview.date = old_time + timedelta(hours=1)
        self.interview.save(update_fields=['date'])

        service.reschedule_interview_reminders(self.interview)

        self.assertEqual(delete_task_mock.call_count, 6)
        self.assertEqual(
            InterviewReminderDelivery.objects.filter(
                interview=self.interview,
                expected_interview_time=old_time,
                status=InterviewReminderDelivery.Status.CANCELLED,
            ).count(),
            6,
        )
        self.assertEqual(
            InterviewReminderDelivery.objects.filter(
                interview=self.interview,
                expected_interview_time=self.interview.date,
                status=InterviewReminderDelivery.Status.PENDING,
            ).count(),
            6,
        )

    @patch('smartInterviewApp.services.interview_reminders.send_sms')
    def test_cancelled_interview_reminder_is_not_sent(self, send_sms_mock):
        delivery = InterviewReminderDelivery.objects.create(
            interview=self.interview,
            reminder_type=InterviewReminderDelivery.ReminderType.ONE_HOUR,
            channel=InterviewReminderDelivery.Channel.SMS,
            scheduled_for=self.interview.date - timedelta(hours=1),
            expected_interview_time=self.interview.date,
            status=InterviewReminderDelivery.Status.PENDING,
        )
        self.interview.status = 'cancelled'
        self.interview.save(update_fields=['status'])

        result = InterviewReminderService().execute_interview_reminder(
            interview_id=self.interview.id,
            reminder_type=delivery.reminder_type,
            channel=delivery.channel,
            expected_interview_time=self.interview.date.isoformat(),
        )

        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'cancelled')
        send_sms_mock.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, InterviewReminderDelivery.Status.CANCELLED)

    @patch('smartInterviewApp.services.interview_reminders.send_sms')
    def test_stale_expected_interview_time_is_skipped(self, send_sms_mock):
        stale_time = timezone.now() - timedelta(hours=2)
        self.interview.date = stale_time
        self.interview.save(update_fields=['date'])
        delivery = InterviewReminderDelivery.objects.create(
            interview=self.interview,
            reminder_type=InterviewReminderDelivery.ReminderType.FIFTEEN_MIN,
            channel=InterviewReminderDelivery.Channel.SMS,
            scheduled_for=stale_time - timedelta(minutes=15),
            expected_interview_time=stale_time,
            status=InterviewReminderDelivery.Status.PENDING,
        )

        result = InterviewReminderService().execute_interview_reminder(
            interview_id=self.interview.id,
            reminder_type=delivery.reminder_type,
            channel=delivery.channel,
            expected_interview_time=stale_time.isoformat(),
        )

        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'skipped')
        send_sms_mock.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, InterviewReminderDelivery.Status.SKIPPED)

    @patch('smartInterviewApp.services.interview_reminders.send_sms')
    def test_duplicate_task_execution_does_not_duplicate_sends(self, send_sms_mock):
        send_sms_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='sms-1', response_payload={'ok': True})
        delivery = InterviewReminderDelivery.objects.create(
            interview=self.interview,
            reminder_type=InterviewReminderDelivery.ReminderType.ONE_HOUR,
            channel=InterviewReminderDelivery.Channel.SMS,
            scheduled_for=self.interview.date - timedelta(hours=1),
            expected_interview_time=self.interview.date,
            status=InterviewReminderDelivery.Status.PENDING,
        )
        service = InterviewReminderService()

        first = service.execute_interview_reminder(
            interview_id=self.interview.id,
            reminder_type=delivery.reminder_type,
            channel=delivery.channel,
            expected_interview_time=self.interview.date.isoformat(),
        )
        second = service.execute_interview_reminder(
            interview_id=self.interview.id,
            reminder_type=delivery.reminder_type,
            channel=delivery.channel,
            expected_interview_time=self.interview.date.isoformat(),
        )

        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        self.assertEqual(second['status'], 'already_sent')
        self.assertEqual(send_sms_mock.call_count, 1)
        self.assertEqual(send_sms_mock.call_args.kwargs['metadata']['msg91_template_id'], 'sms_template_60')

    @patch('smartInterviewApp.services.interview_reminders.send_template_message')
    @patch('smartInterviewApp.services.interview_reminders.send_sms')
    def test_sms_and_whatsapp_are_handled_independently(self, send_sms_mock, send_whatsapp_mock):
        send_sms_mock.return_value = ProviderResult(success=False, status='failed', response_payload={'error': 'sms'}, error_message='SMS failed')
        send_whatsapp_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='wa-1', response_payload={'messages': [{'id': 'wa-1'}]})

        sms_delivery = InterviewReminderDelivery.objects.create(
            interview=self.interview,
            reminder_type=InterviewReminderDelivery.ReminderType.THIRTY_MIN,
            channel=InterviewReminderDelivery.Channel.SMS,
            scheduled_for=self.interview.date - timedelta(minutes=30),
            expected_interview_time=self.interview.date,
            status=InterviewReminderDelivery.Status.PENDING,
        )
        whatsapp_delivery = InterviewReminderDelivery.objects.create(
            interview=self.interview,
            reminder_type=InterviewReminderDelivery.ReminderType.THIRTY_MIN,
            channel=InterviewReminderDelivery.Channel.WHATSAPP,
            scheduled_for=self.interview.date - timedelta(minutes=30),
            expected_interview_time=self.interview.date,
            status=InterviewReminderDelivery.Status.PENDING,
        )

        sms_result = InterviewReminderService().execute_interview_reminder(
            interview_id=self.interview.id,
            reminder_type=sms_delivery.reminder_type,
            channel=sms_delivery.channel,
            expected_interview_time=self.interview.date.isoformat(),
        )
        whatsapp_result = InterviewReminderService().execute_interview_reminder(
            interview_id=self.interview.id,
            reminder_type=whatsapp_delivery.reminder_type,
            channel=whatsapp_delivery.channel,
            expected_interview_time=self.interview.date.isoformat(),
        )

        self.assertFalse(sms_result['ok'])
        self.assertTrue(whatsapp_result['ok'])
        sms_delivery.refresh_from_db()
        whatsapp_delivery.refresh_from_db()
        self.assertEqual(sms_delivery.status, InterviewReminderDelivery.Status.FAILED)
        self.assertEqual(whatsapp_delivery.status, InterviewReminderDelivery.Status.SENT)

    def test_template_rendering_handles_missing_values(self):
        message = build_reminder_message(
            InterviewReminderDelivery.ReminderType.ONE_HOUR,
            clean_value('', 'Candidate'),
            clean_value('', 'your scheduled role'),
            '10:00 AM',
        )
        self.assertIn('Hello Candidate', message)
        self.assertIn('your scheduled role', message)

    def test_fifteen_min_template_includes_join_link(self):
        self.interview.litio_interview_token = 'ab23cd45'
        self.interview.save(update_fields=['litio_interview_token'])

        message = build_reminder_message(
            InterviewReminderDelivery.ReminderType.FIFTEEN_MIN,
            'Asha',
            'Python Developer',
            '10:00 AM',
            'https://litio.shortlistii.com/i/ab23cd45',
        )
        parameters = build_whatsapp_parameters(
            InterviewReminderDelivery.ReminderType.FIFTEEN_MIN,
            'Asha',
            'Python Developer',
            '10:00 AM',
            'https://litio.shortlistii.com/i/ab23cd45',
        )

        self.assertIn('https://litio.shortlistii.com/i/ab23cd45', message)
        self.assertEqual(
            parameters,
            ['Asha', 'Python Developer', '10:00 AM', 'https://litio.shortlistii.com/i/ab23cd45'],
        )

    @patch('smartInterviewApp.services.interview_reminders.send_sms')
    def test_fifteen_min_sms_uses_msg91_template_id(self, send_sms_mock):
        send_sms_mock.return_value = ProviderResult(success=True, status='sent', provider_message_id='sms-15', response_payload={'ok': True})
        delivery = InterviewReminderDelivery.objects.create(
            interview=self.interview,
            reminder_type=InterviewReminderDelivery.ReminderType.FIFTEEN_MIN,
            channel=InterviewReminderDelivery.Channel.SMS,
            scheduled_for=self.interview.date - timedelta(minutes=15),
            expected_interview_time=self.interview.date,
            status=InterviewReminderDelivery.Status.PENDING,
        )

        result = InterviewReminderService().execute_interview_reminder(
            interview_id=self.interview.id,
            reminder_type=delivery.reminder_type,
            channel=delivery.channel,
            expected_interview_time=self.interview.date.isoformat(),
        )

        self.assertTrue(result['ok'])
        self.assertEqual(send_sms_mock.call_args.kwargs['metadata']['msg91_template_id'], 'sms_template_15')

    def test_internal_endpoint_rejects_unauthorized_calls(self):
        response = self.client.post(
            reverse('internal-send-interview-reminder'),
            data=json.dumps({
                'interview_id': self.interview.id,
                'reminder_type': InterviewReminderDelivery.ReminderType.ONE_HOUR,
                'channel': InterviewReminderDelivery.Channel.SMS,
                'expected_interview_time': self.interview.date.isoformat(),
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    def test_candidate_reindex_internal_endpoint_rejects_unauthorized_calls(self):
        response = self.client.post(
            reverse('internal-rebuild-candidate-search-profile'),
            data=json.dumps({'candidate_id': self.candidate.id}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    @patch('smartInterviewApp.views.process_candidate_reindex')
    def test_candidate_reindex_internal_endpoint_processes_authorized_call(self, process_mock):
        process_mock.return_value = {'ok': True, 'status': 'processed', 'candidate_id': self.candidate.id}

        response = self.client.post(
            reverse('internal-rebuild-candidate-search-profile'),
            data=json.dumps({'candidate_id': self.candidate.id}),
            content_type='application/json',
            HTTP_X_CLOUD_TASKS_SECRET='task-secret',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        process_mock.assert_called_once_with(self.candidate.id)

    @patch('smartInterviewApp.views.send_candidate_interview_email_only')
    def test_resend_candidate_interview_email_endpoint_sends_email(self, send_email_only_mock):
        send_email_only_mock.return_value = {
            'sent': True,
            'reason': '',
            'channels': {
                'email': {'sent': True, 'reason': '', 'subject': 'Interview Scheduled: Python Developer | Shortlistii'},
            },
            'interview_token': 'abcd1234',
            'interview_link': 'https://litio.shortlistii.com/i/abcd1234',
        }

        response = self.client.post(reverse('resend-candidate-interview-email'), data={
            'interview_id': self.interview.id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        send_email_only_mock.assert_called_once()
        self.assertEqual(response.json()['Data']['channels']['email']['subject'], 'Interview Scheduled: Python Developer | Shortlistii')

    @patch('smartInterviewApp.views.send_candidate_interview_email_only')
    def test_resend_candidate_interview_email_endpoint_rejects_inaccessible_interview(self, send_email_only_mock):
        other_admin = User.objects.create_user(username='other-admin', password='pass1234', email='other-admin@example.com')
        UserProfile.objects.create(user=other_admin, role='admin', phone='919111111110', gender='other')
        other_candidate = User.objects.create_user(username='other-candidate', password='pass1234', email='other-candidate@example.com')
        UserProfile.objects.create(user=other_candidate, role='candidate', phone='919111111119', gender='female', hr=other_admin)
        other_interview = Interview.objects.create(
            candidate=other_candidate,
            recruiter=self.recruiter,
            hr=other_admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
        )

        response = self.client.post(reverse('resend-candidate-interview-email'), data={
            'interview_id': other_interview.id,
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['Success'])
        send_email_only_mock.assert_not_called()

    @patch('smartInterviewApp.views.send_existing_candidate_sms')
    @patch('smartInterviewApp.views.queue_scheduled_interview_processing')
    def test_schedule_workflow_sends_candidate_notification_and_queues_reminders(self, queue_processing_mock, send_existing_mock):
        queue_processing_mock.return_value = {'queued': True, 'count': 1, 'mode': 'cloud_tasks'}
        send_existing_mock.return_value = {
            'sent': True,
            'reason': '',
            'provider_message_id': 'sms-123',
            'channels': {
                'sms': {'sent': True, 'reason': '', 'provider_message_id': 'sms-123'},
                'whatsapp': {'sent': True, 'reason': '', 'provider_message_id': 'wa-123'},
            },
            'message': 'hello',
            'interview_token': 'abcd1234',
            'interview_link': 'https://litio.shortlistii.com/i/abcd1234',
        }
        response = self.client.post(
            reverse('update-interview-workflow'),
            data=json.dumps({
                'interview_ids': [self.interview.id],
                'mode': 'schedule',
                'interview_type': 'manual',
                'interviewer_id': self.interviewer.id,
                'scheduled_at': (timezone.now() + timedelta(days=1)).isoformat(),
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        self.assertTrue(queue_processing_mock.called)
        self.assertTrue(send_existing_mock.called)
        self.assertTrue(response.json()['Data']['notifications'][0]['result']['queued'])
        self.assertTrue(response.json()['Data']['notifications'][0]['result']['sent'])

    @patch('smartInterviewApp.views.send_existing_candidate_sms')
    @patch('smartInterviewApp.views.queue_scheduled_interview_processing')
    def test_reschedule_workflow_marks_notification_as_rescheduled(self, queue_processing_mock, send_existing_mock):
        queue_processing_mock.return_value = {'queued': True, 'count': 1, 'mode': 'cloud_tasks'}
        send_existing_mock.return_value = {
            'sent': True,
            'reason': '',
            'provider_message_id': 'sms-123',
            'channels': {
                'sms': {'sent': True, 'reason': '', 'provider_message_id': 'sms-123'},
                'whatsapp': {'sent': True, 'reason': '', 'provider_message_id': 'wa-123'},
                'email': {'sent': True, 'reason': '', 'subject': 'Interview Rescheduled: Python Developer | Shortlistii'},
            },
            'message': 'hello',
            'interview_token': 'abcd1234',
            'interview_link': 'https://litio.shortlistii.com/i/abcd1234',
        }
        old_time = self.interview.date
        new_time = old_time + timedelta(days=1)

        response = self.client.post(
            reverse('update-interview-workflow'),
            data=json.dumps({
                'interview_ids': [self.interview.id],
                'mode': 'schedule',
                'interview_type': 'manual',
                'interviewer_id': self.interviewer.id,
                'scheduled_at': new_time.isoformat(),
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        send_existing_mock.assert_called_once()
        self.assertEqual(send_existing_mock.call_args.kwargs['notification_kind'], 'rescheduled')
        self.assertEqual(send_existing_mock.call_args.kwargs['previous_scheduled_at'], old_time)

    @patch('smartInterviewApp.views.InterviewReminderService.cancel_pending_interview_reminders')
    def test_status_update_cancels_future_reminders(self, cancel_mock):
        response = self.client.post(reverse('update-candidate-status'), data={
            'candidateId': self.interview.id,
            'newStatus': 'cancelled',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        cancel_mock.assert_called_once()


class CandidateEvaluationSummaryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        existing_tables = set(connection.introspection.table_names())
        cls._created_evaluation_table = AutoInterviewEvaluationResult._meta.db_table not in existing_tables
        if cls._created_evaluation_table:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(AutoInterviewEvaluationResult)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, '_created_evaluation_table', False):
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(AutoInterviewEvaluationResult)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_user(username='eval-admin', password='pass1234', email='eval-admin@example.com')
        self.recruiter = User.objects.create_user(username='eval-recruiter', password='pass1234', email='eval-recruiter@example.com')
        self.interviewer = User.objects.create_user(username='eval-interviewer', password='pass1234', email='eval-interviewer@example.com')
        self.candidate = User.objects.create_user(username='eval-candidate', password='pass1234', email='eval-candidate@example.com')
        UserProfile.objects.create(user=self.admin, role='admin', phone='919111111100', gender='other')
        UserProfile.objects.create(user=self.recruiter, role='recruiter', phone='919111111101', gender='male', hr=self.admin)
        UserProfile.objects.create(user=self.interviewer, role='interviewer', phone='919111111102', gender='female', hr=self.admin)
        UserProfile.objects.create(user=self.candidate, role='candidate', phone='919111111103', gender='female', hr=self.admin)
        self.role = Vacancies.objects.create(role='Backend Engineer', description='Role description', skills_required='Python')
        self.interview = Interview.objects.create(
            candidate=self.candidate,
            recruiter=self.recruiter,
            interviewer=self.interviewer,
            hr=self.admin,
            role=self.role,
            interview_type='auto',
            status='assessment_completed',
        )
        self.client.login(username='eval-admin', password='pass1234')

    def test_candidate_evaluation_summary_endpoint_returns_saved_summary(self):
        AutoInterviewEvaluationResult.objects.create(
            interview_id=self.interview.id,
            interview_token='auto-eval-123',
            room_name='room-1',
            candidate_name='Eval Candidate',
            decision='STRONG_HIRE',
            recommendation='Advance to next round',
            score=86.50,
            executive_summary='Strong backend depth with clear ownership on distributed systems.',
            summary_verdict='Recommended for the next round.',
            evaluation_payload={
                'confidence': 'High',
                'interview_signal_quality': 'Strong',
                'strengths': ['Python fundamentals', 'System design'],
                'concerns': ['Could improve testing examples'],
                'gaps': ['Needs deeper Kubernetes exposure'],
                'notes': ['Validated production incident handling'],
                'follow_up_areas': ['Ask about platform observability ownership'],
                'hire_recommendation': {
                    'action': 'ADVANCE',
                    'reason': 'Clear signal for backend ownership and technical depth.',
                },
            },
        )

        response = self.client.get(reverse('candidate-evaluation-summary', args=[self.interview.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()['Data']['evaluation_summary']
        self.assertTrue(payload['available'])
        self.assertEqual(payload['decision'], 'STRONG_HIRE')
        self.assertEqual(payload['recommendation'], 'Advance to next round')
        self.assertEqual(payload['score'], 86.5)
        self.assertEqual(payload['strengths'], ['Python fundamentals', 'System design'])
        self.assertEqual(payload['hire_recommendation_action'], 'ADVANCE')

    def test_candidate_profile_data_excludes_interview_evaluation_summary(self):
        AutoInterviewEvaluationResult.objects.create(
            interview_id=self.interview.id,
            decision='HOLD',
            recommendation='Review with panel',
            score=71.00,
            executive_summary='Some positive signals, but deeper validation is still needed.',
            summary_verdict='Borderline result.',
            evaluation_payload={
                'strengths': ['Communication'],
                'concerns': ['Limited depth on APIs'],
            },
        )

        response = self.client.get(reverse('candidate-profile-data', args=[self.interview.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('evaluation_summary', response.json()['Data'])

    def test_candidate_evaluation_summary_endpoint_rejects_inaccessible_interview(self):
        other_admin = User.objects.create_user(username='eval-other-admin', password='pass1234', email='eval-other-admin@example.com')
        other_candidate = User.objects.create_user(username='eval-other-candidate', password='pass1234', email='eval-other-candidate@example.com')
        UserProfile.objects.create(user=other_admin, role='admin', phone='919111111104', gender='other')
        UserProfile.objects.create(user=other_candidate, role='candidate', phone='919111111105', gender='female', hr=other_admin)
        other_interview = Interview.objects.create(candidate=other_candidate, hr=other_admin, status='scheduled')

        response = self.client.get(reverse('candidate-evaluation-summary', args=[other_interview.id]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()['Success'])


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='no-reply@example.com',
)
class ContactViewTests(TestCase):
    def _contact_payload(self, **overrides):
        payload = {
            'full_name': 'Test User',
            'work_email': 'person@example.com',
            'company_name': 'Acme Corp',
            'inquiry_type': 'support',
            'phone_number': '1234567890',
            'team_size': '11_50',
            'message': 'Need help with the contact form.',
        }
        payload.update(overrides)
        return payload

    @override_settings(CONTACT_INBOX_EMAIL='sales@example.com', CONTACT_SUPPORT_EMAIL='support@example.com')
    def test_contact_form_sends_to_configured_inbox(self):
        response = self.client.post(reverse('contact'), data=self._contact_payload())

        self.assertRedirects(response, reverse('contact'))
        self.assertEqual(len(mail.outbox), 1)
        sent_message = mail.outbox[0]
        self.assertEqual(sent_message.to, ['sales@example.com'])
        self.assertEqual(sent_message.reply_to, ['person@example.com'])
        self.assertEqual(sent_message.from_email, 'no-reply@example.com')

    @override_settings(CONTACT_SUPPORT_EMAIL='support@example.com')
    @patch('smartInterviewApp.views.send_contact_notification_email', side_effect=RuntimeError('mail backend unavailable'))
    def test_contact_form_mail_failure_returns_form_error(self, send_mock):
        response = self.client.post(reverse('contact'), data=self._contact_payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'We could not send your message right now. Please email support@example.com directly.')
        self.assertEqual(len(mail.outbox), 0)
        send_mock.assert_called_once()

    @override_settings(CONTACT_INBOX_EMAIL='sales@example.com')
    def test_contact_form_strips_newlines_from_subject_values(self):
        response = self.client.post(
            reverse('contact'),
            data=self._contact_payload(company_name='Acme\nCorp'),
        )

        self.assertRedirects(response, reverse('contact'))
        self.assertEqual(mail.outbox[0].subject, '[Shortlistii Contact] Support - Acme Corp')

    @override_settings(CONTACT_INBOX_EMAIL='sales@example.com', DEFAULT_FROM_EMAIL=None)
    def test_contact_form_uses_fallback_from_email_when_setting_is_none(self):
        response = self.client.post(reverse('contact'), data=self._contact_payload())

        self.assertRedirects(response, reverse('contact'))
        self.assertEqual(mail.outbox[0].from_email, 'no-reply@shortlistii.com')
