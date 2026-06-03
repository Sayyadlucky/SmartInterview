from __future__ import annotations

from datetime import timedelta
from io import StringIO
import json
import os
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from smartInterviewApp.integrations.providers.contracts import ProviderResult
from smartInterviewApp.api.serializers import ExotelWebhookSerializer
from smartInterviewApp.integrations.providers.msg91 import Msg91OtpProvider, Msg91SmsProvider
from smartInterviewApp.models import AutoInterviewEvaluationResult, CandidateIdentityVerification, CodingQuestion, JobInterviewBlueprint, JobInterviewSkill, Notification, NotificationAttempt, OtpRequest, QuestionGenerationJob, Skill, SkillQuestion, UserProfile, Vacancies, Interview, InterviewCallSession, InterviewReminderDelivery, CandidateSavedVacancy, CandidateVacancyApplication
from smartInterviewApp.notifications.services import NotificationService
from smartInterviewApp.otp.services import OtpService
from smartInterviewApp.commonViews import (
    SIGNUP_TOKEN_SALT,
    build_candidate_signup_link,
    build_litio_interview_link,
    ensure_candidate_signup_token,
    send_existing_candidate_sms,
)
from smartInterviewApp.identity_verification import CandidateLiveSelfieVerificationService
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
from smartInterviewApp.services.interview_blueprints import build_job_interview_blueprint, process_job_interview_blueprint_task
from smartInterviewApp.services.blueprint_plan_signature import blueprint_plan_signature, ensure_blueprint_plan_signature
from smartInterviewApp.services.question_banks import (
    OpenAIQuestionGenerationError,
    _coding_readiness_for_blueprint,
    _select_question_generation_job_ids,
    _worker_lock_queryset,
    ensure_question_bank_for_blueprint,
    ensure_question_bank_for_skill,
    insert_skill_questions,
    process_missing_question_bank_for_interview,
    process_question_generation_queue,
    process_question_generation_task,
    resolve_equivalent_skill_ids_for_question_pool,
)


class CandidateLiveSelfieVerificationEndpointTests(TestCase):
    jpeg_bytes = b'\xff\xd8\xff\xe0' + b'live-selfie-test' + b'\xff\xd9'

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(
            MEDIA_ROOT=self.media_dir.name,
            LIVE_SELFIE_VERIFICATION_ENABLED=True,
            LIVE_SELFIE_FACE_MATCH_PROVIDER='local_face_recognition',
            LIVE_SELFIE_FACE_MATCH_THRESHOLD=0.62,
            LIVE_SELFIE_FACE_VERIFY_TIMEOUT_SECONDS=20,
        )
        self.override.enable()
        self.candidate = User.objects.create_user(
            username='candidate-live-selfie',
            email='candidate-live-selfie@example.com',
            password='pass1234',
            first_name='Candidate',
            last_name='Selfie',
        )
        self.profile = UserProfile.objects.create(
            user=self.candidate,
            role='candidate',
            gender='other',
            phone='9876543210',
        )
        self.url = reverse('candidate-live-selfie-verify')

    def tearDown(self):
        self.override.disable()
        self.media_dir.cleanup()

    def _login_candidate(self):
        self.client.login(username='candidate-live-selfie', password='pass1234')

    def _attach_profile_photo(self):
        self.profile.profile_picture.save(
            'profile.jpg',
            SimpleUploadedFile('profile.jpg', self.jpeg_bytes, content_type='image/jpeg'),
            save=True,
        )

    def _selfie_upload(self, name='selfie.jpg', content_type='image/jpeg', content=None):
        return SimpleUploadedFile(name, content or self.jpeg_bytes, content_type=content_type)

    def _quality_payload(self):
        return {
            'provider': 'facemesh_quality_check',
            'one_face_detected': True,
            'alignment_passed': True,
            'stable_face': True,
            'liveness_check': 'stable_face',
        }

    def _post_live_selfie(self, extra=None):
        data = {
            'selfie': self._selfie_upload(),
            'facemesh_quality_payload': json.dumps(self._quality_payload()),
        }
        if extra:
            data.update(extra)
        return self.client.post(self.url, data)

    def _match_result(self, matched=True, reason=None, score=None):
        return {
            'available': True,
            'matched': matched,
            'score': 0.83 if score is None and matched else (0.31 if score is None else score),
            'threshold': 0.62,
            'reason': reason or ('face_matched' if matched else 'face_mismatch'),
            'provider': 'local_face_recognition',
            'profile_face_count': 1,
            'selfie_face_count': 1,
            'message': 'Face matched successfully.' if matched else 'We could not confidently match your selfie with your profile photo.',
        }

    def test_live_selfie_verify_requires_authentication(self):
        response = self.client.post(self.url, {'selfie': self._selfie_upload()})
        self.assertEqual(response.status_code, 302)

    def test_live_selfie_verify_rejects_non_candidate(self):
        user = User.objects.create_user(username='recruiter-live-selfie', password='pass1234')
        UserProfile.objects.create(user=user, role='recruiter', gender='other', phone='9876543211')
        self.client.login(username='recruiter-live-selfie', password='pass1234')

        response = self.client.post(self.url, {'selfie': self._selfie_upload()})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'candidate_required')

    def test_live_selfie_verify_requires_profile_photo(self):
        self._login_candidate()

        response = self.client.post(self.url, {'selfie': self._selfie_upload()})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['code'], 'profile_photo_required')
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.status, CandidateIdentityVerification.Status.PROFILE_PHOTO_REQUIRED)

    def test_live_selfie_verify_rejects_invalid_image(self):
        self._login_candidate()
        self._attach_profile_photo()

        response = self.client.post(self.url, {
            'selfie': self._selfie_upload('selfie.txt', 'text/plain', b'not an image'),
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_image')

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_local_match_marks_identity_verified(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.return_value = self._match_result(matched=True, score=0.83)

        response = self._post_live_selfie()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertTrue(response.json()['verified'])
        self.assertEqual(response.json()['code'], 'face_matched')
        self.assertEqual(response.json()['status'], CandidateIdentityVerification.Status.FACE_MATCHED)
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.verification_method, CandidateIdentityVerification.Method.LIVE_SELFIE)
        self.assertEqual(record.status, CandidateIdentityVerification.Status.FACE_MATCHED)
        self.assertEqual(record.face_match_score, 0.83)
        self.assertEqual(record.face_match_threshold, 0.62)
        self.assertEqual(record.face_match_payload['provider'], 'local_face_recognition')
        self.assertEqual(record.face_match_payload['reason'], 'face_matched')
        self.assertEqual(record.face_match_payload['facemesh_quality_payload']['provider'], 'facemesh_quality_check')
        self.assertTrue(record.face_match_payload['profile_photo_match_claimed'])

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_local_mismatch_stores_face_mismatch(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.return_value = self._match_result(matched=False, score=0.31)

        response = self._post_live_selfie()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertFalse(response.json()['verified'])
        self.assertEqual(response.json()['code'], 'face_mismatch')
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.status, CandidateIdentityVerification.Status.FACE_MISMATCH)
        self.assertEqual(record.face_match_score, 0.31)
        self.assertEqual(record.face_match_payload['provider'], 'local_face_recognition')
        self.assertFalse(record.face_match_payload['profile_photo_match_claimed'])
        self.assertIn('could not confidently match', record.error_message)
        self.assertNotIn('unclear or outdated', record.error_message)

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_close_mismatch_guides_profile_photo_update(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.return_value = self._match_result(matched=False, score=0.55)

        response = self._post_live_selfie()

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload['code'], 'face_mismatch')
        self.assertIn('unclear or outdated', payload['message'])
        self.assertIn('recent, clear, front-facing profile photo', payload['message'])
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.face_match_score, 0.55)
        self.assertEqual(record.face_match_payload['score'], 0.55)
        self.assertEqual(record.face_match_payload['threshold'], 0.62)

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_profile_face_low_quality_guides_photo_upload(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.return_value = self._match_result(
            matched=False,
            reason='profile_face_low_quality',
            score=0,
        ) | {
            'message': 'Please upload a clearer front-facing profile photo before verification.',
        }

        response = self._post_live_selfie()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'profile_face_low_quality')
        self.assertEqual(response.json()['message'], 'Please upload a clearer front-facing profile photo before verification.')
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.status, CandidateIdentityVerification.Status.FACE_MISMATCH)
        self.assertEqual(record.face_match_payload['reason'], 'profile_face_low_quality')

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_facemesh_payload_alone_cannot_verify_identity(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.return_value = {
            'available': False,
            'matched': False,
            'score': 0,
            'threshold': 0.62,
            'reason': 'local_face_recognition_unavailable',
            'provider': 'local_face_recognition',
            'profile_face_count': 0,
            'selfie_face_count': 0,
            'message': 'Live selfie identity verification is temporarily unavailable.',
        }

        response = self._post_live_selfie({'facemesh_score': '0.99'})

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertFalse(payload['verified'])
        self.assertEqual(payload['code'], 'face_matching_unavailable')
        self.assertEqual(payload['status'], 'verification_unavailable')
        mock_verify.assert_called_once()
        self.assertFalse(CandidateIdentityVerification.objects.filter(candidate=self.candidate, status=CandidateIdentityVerification.Status.FACE_MATCHED).exists())

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_service_unavailable_does_not_mark_face_mismatch(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.return_value = {
            'available': False,
            'matched': False,
            'score': 0,
            'threshold': 0.62,
            'reason': 'local_face_recognition_unavailable',
            'provider': 'local_face_recognition',
            'profile_face_count': 0,
            'selfie_face_count': 0,
            'message': 'Live selfie identity verification is temporarily unavailable.',
        }

        response = self._post_live_selfie()

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertFalse(payload['verified'])
        self.assertEqual(payload['code'], 'face_matching_unavailable')
        self.assertEqual(payload['status'], 'verification_unavailable')
        self.assertEqual(payload['message'], 'Live selfie identity verification is temporarily unavailable. Please try again later.')
        self.assertEqual(payload['data'], {'verified': False})
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.status, CandidateIdentityVerification.Status.FAILED)
        self.assertNotEqual(record.status, CandidateIdentityVerification.Status.FACE_MISMATCH)

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_matcher_system_exit_returns_json_unavailable(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.side_effect = SystemExit('face_recognition import failed')

        response = self._post_live_selfie()

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['code'], 'face_matching_unavailable')
        self.assertEqual(payload['status'], 'verification_unavailable')
        self.assertEqual(payload['data'], {'verified': False})
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.status, CandidateIdentityVerification.Status.FAILED)
        self.assertNotEqual(record.status, CandidateIdentityVerification.Status.FACE_MISMATCH)

    @patch('smartInterviewApp.commonViews.CandidateLiveSelfieVerificationService.verify_local_face_match')
    def test_live_selfie_verify_selfie_face_not_detected_returns_retry_safe_failure(self, mock_verify):
        self._login_candidate()
        self._attach_profile_photo()
        mock_verify.return_value = self._match_result(
            matched=False,
            reason='selfie_face_not_detected',
            score=0,
        ) | {
            'selfie_face_count': 0,
            'message': 'We could not detect a clear face in your selfie. Please try again.',
        }

        response = self._post_live_selfie()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'selfie_face_not_detected')
        self.assertFalse(response.json()['verified'])
        record = CandidateIdentityVerification.objects.get(candidate=self.candidate)
        self.assertEqual(record.status, CandidateIdentityVerification.Status.FACE_MISMATCH)
        self.assertEqual(record.face_match_payload['reason'], 'selfie_face_not_detected')


class CandidateLiveSelfieVerificationServiceTests(TestCase):
    def test_local_face_recognition_missing_returns_unavailable(self):
        with patch.dict('sys.modules', {'face_recognition': None}):
            result = CandidateLiveSelfieVerificationService().verify_local_face_match(b'profile', b'selfie', 0.62)

        self.assertFalse(result['available'])
        self.assertFalse(result['matched'])
        self.assertEqual(result['reason'], 'local_face_recognition_unavailable')
        self.assertEqual(result['provider'], 'local_face_recognition')


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

    @override_settings(META_WHATSAPP_APP_SECRET='')
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

        self.candidate = User.objects.create_user(username='candidate1', password='pass1234', email='candidate@example.com')
        self.candidate.first_name = 'Candidate'
        self.candidate.last_name = 'One'
        self.candidate.save(update_fields=['first_name', 'last_name'])
        UserProfile.objects.create(user=self.candidate, role='candidate', phone='919111111111', gender='female', hr=self.admin)

        self.interview = Interview.objects.create(
            candidate=self.candidate,
            recruiter=self.recruiter,
            hr=self.admin,
            interviewer=self.interviewer,
            role=self.role,
            status='scheduled',
        )
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
        sms_metadata = send_sms_mock.call_args.kwargs['metadata']
        self.assertEqual(sms_metadata['msg91_flow_variables']['url'], payload['Notification']['signup_url'])
        self.assertEqual(sms_metadata['msg91_flow_variables']['signup_url'], payload['Notification']['signup_url'])
        self.assertEqual(sms_metadata['msg91_flow_variables']['link'], payload['Notification']['signup_url'])
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
        self.assertTrue(os.path.basename(profile.profile_picture.name).startswith('profile'))
        self.assertTrue(profile.profile_picture.name.endswith('.jpg'))
        self.assertTrue(os.path.basename(profile.resume.name).startswith('resume'))
        self.assertTrue(profile.resume.name.endswith('.pdf'))
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
        self.assertTrue(os.path.basename(profile.profile_picture.name).startswith('profile'))
        self.assertTrue(profile.profile_picture.name.endswith('.jpg'))
        self.assertTrue(os.path.basename(profile.resume.name).startswith('resume'))
        self.assertTrue(profile.resume.name.endswith('.pdf'))
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
        self.assertTrue(os.path.basename(profile.profile_picture.name).startswith('manual_profile'))
        self.assertTrue(profile.profile_picture.name.endswith('.jpg'))
        self.assertTrue(os.path.basename(profile.resume.name).startswith('manual_resume'))
        self.assertTrue(profile.resume.name.endswith('.pdf'))
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
        self.assertEqual(admin_candidates_payload['Data']['candidates'][0]['interviewer'], 'Interviewer Route')
        self.assertEqual(admin_candidates_payload['Data']['candidates'][0]['recruiter'], 'Recruiter Route')

        self.client.logout()
        self.client.login(username='recruiter-route', password='pass1234')

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
        self.assertEqual(hr_profile_payload['Interviews'][0]['recruiter'], 'Recruiter Route')


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
        self.assertContains(response, 'Candidate login required')
        self.assertContains(response, 'Apply Now')

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
        self.assertContains(page_response, 'Bookmarked Roles')
        self.assertContains(page_response, 'Saved')

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
        with self.captureOnCommitCallbacks(execute=True):
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
        with self.captureOnCommitCallbacks(execute=True):
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
        self.role = Vacancies.objects.create(
            role='Backend Engineer',
            description='Role description',
            position='1',
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

    def test_candidate_evaluation_summary_endpoint_returns_litio_report_payload(self):
        AutoInterviewEvaluationResult.objects.create(
            interview_id=self.interview.id,
            candidate_name='Eval Candidate',
            decision='NEEDS_MORE_DATA',
            recommendation='Review with panel',
            score=68.00,
            executive_summary='Fallback executive summary.',
            summary_verdict='Fallback verdict.',
            evaluation_payload={
                'professional_summary': (
                    'Executive Summary: Candidate showed partial backend depth.\n'
                    'Evidence Record: Answered API and testing questions with mixed specificity.\n'
                    'Hiring Signal: Needs another technical validation round.\n'
                    'Candidate Behaviour: Calm and responsive throughout the session.'
                ),
                'question_answer_records': [
                    {
                        'turn_index': 1,
                        'skill': 'Python',
                        'section_role': 'primary',
                        'question_text': 'How do you design a retry-safe API client?',
                        'candidate_answer': 'Use idempotency keys, exponential backoff, and bounded retries.',
                        'answer_quality_state': 'partial',
                        'expected_signal': 'Understands idempotency and failure handling.',
                    },
                ],
                'candidate_behavior': {
                    'status': 'attention_required',
                    'summary': 'Brief offscreen events were observed.',
                    'gaze_tracking': {
                        'event_count': 5,
                        'centered_count': 3,
                        'offscreen_or_visibility_count': 2,
                        'status': 'attention_required',
                    },
                    'voice_verification': {
                        'event_count': 4,
                        'match_count': 4,
                        'unmatch_count': 0,
                        'latest_status': 'clear',
                        'flagged_for_review': False,
                    },
                },
                'debug_trace': {'raw': 'hidden'},
            },
        )

        response = self.client.get(reverse('candidate-evaluation-summary', args=[self.interview.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()['Data']['evaluation_summary']
        self.assertEqual(payload['candidate_name'], 'Eval Candidate')
        self.assertIn('Executive Summary:', payload['professional_summary'])
        self.assertEqual(payload['question_answer_records'][0]['skill'], 'Python')
        self.assertEqual(payload['candidate_behavior']['status'], 'attention_required')
        self.assertEqual(payload['candidate_behavior']['voice_verification']['latest_status'], 'clear')
        self.assertNotIn('debug_trace', payload['evaluation_payload'])

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


@override_settings(
    INTERVIEW_BLUEPRINT_ENABLED=True,
    INTERVIEW_BLUEPRINT_OPENAI_ENABLED=False,
    INTERVIEW_BLUEPRINT_CREATE_MISSING_SKILLS=False,
    INTERVIEW_BLUEPRINT_MAX_SKILLS=5,
)
class InterviewBlueprintFoundationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='blueprint-admin', password='pass1234', email='bp-admin@example.com')
        UserProfile.objects.create(user=self.admin, role='admin', phone='919999999990', gender='other')
        self.recruiter = User.objects.create_user(username='blueprint-recruiter', password='pass1234', email='bp-recruiter@example.com')
        UserProfile.objects.create(user=self.recruiter, role='recruiter', phone='919999999991', gender='other', hr=self.admin)
        self.client.login(username='blueprint-admin', password='pass1234')

    def _add_role_payload(self):
        return {
            'name': 'Java Backend Developer',
            'description': 'Build REST APIs using JVM fundamentals, Spring Boot, and PostgreSQL joins.',
            'vacancies': '2',
            'job_type': 'full_time',
            'location': 'Remote',
            'salary_range': '10-15 LPA',
            'experience_required': '3-5 years',
            'status': 'active',
            'recruiter': str(self.recruiter.id),
        }

    def _vacancy(self, role='Full Stack Developer', description='', experience_required='0-3 years'):
        return Vacancies.objects.create(
            role=role,
            description=description or 'Build web and mobile products.',
            position='1',
            status='active',
            experience_required=experience_required,
            admin=self.admin,
        )

    def _mock_payload(self, role_title='Full Stack Developer', experience_level='Mid-level (5-10 years)', primary='JavaScript', sub_skills=None, optional_skills=None):
        return {
            'role_title': role_title,
            'experience_level': experience_level,
            'primary_skill': {
                'name': primary,
                'category': 'Programming Language',
                'confidence': 0.9,
                'reason': 'Central skill for the role.',
            },
            'primary_skill_candidates': [
                {'name': primary, 'category': 'Programming Language', 'confidence': 0.9},
                {'name': 'Python', 'category': 'Backend Development', 'confidence': 0.88},
            ],
            'sub_skills': sub_skills or [
                {'name': 'React Native', 'category': 'Mobile Development', 'confidence': 0.9},
                {'name': 'MongoDB', 'category': 'Database', 'confidence': 0.85},
                {'name': 'RESTful APIs', 'category': 'Web Services', 'confidence': 0.82},
            ],
            'optional_skills': optional_skills or [],
        }

    def _build_with_mocked_openai(self, vacancy, payload, create_missing=True):
        with override_settings(
            INTERVIEW_BLUEPRINT_OPENAI_ENABLED=True,
            OPENAI_API_KEY='test-key',
            INTERVIEW_BLUEPRINT_CREATE_MISSING_SKILLS=create_missing,
            INTERVIEW_BLUEPRINT_MAX_EXTRACTED_SKILLS=20,
        ):
            with patch('smartInterviewApp.services.interview_blueprints.extract_skills_with_openai', return_value=payload):
                return build_job_interview_blueprint(vacancy.id)

    def _skill_names_for_blueprint(self, blueprint):
        return set(JobInterviewSkill.objects.filter(blueprint=blueprint).values_list('skill__name', flat=True))

    def _blueprint_with_planned_skill(self, skill_role, interview_weight='normal', eligible_for_random_sub_skill=True):
        skill = Skill.objects.create(
            name=f'{skill_role}-{interview_weight}-{eligible_for_random_sub_skill}',
            key=f'{skill_role}-{interview_weight}-{str(eligible_for_random_sub_skill).lower()}',
            category='Programming Language',
        )
        vacancy = self._vacancy(role='Python Developer', description='Python role', experience_required='0-3 years')
        blueprint = JobInterviewBlueprint.objects.create(
            job=vacancy,
            status=JobInterviewBlueprint.Status.READY,
            role_title=vacancy.role,
            experience_level='Entry-level (0-3 years)',
            blueprint_plan={
                'primary_skill': {
                    'skill_id': skill.id,
                    'skill_key': skill.key,
                    'interview_weight': interview_weight,
                    'eligible_for_random_sub_skill': eligible_for_random_sub_skill,
                } if skill_role == JobInterviewSkill.SkillRole.PRIMARY else {},
                'primary_skill_candidates': [{
                    'skill_id': skill.id,
                    'skill_key': skill.key,
                    'interview_weight': interview_weight,
                    'eligible_for_random_sub_skill': eligible_for_random_sub_skill,
                }] if skill_role == JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE else [],
                'sub_skills': [{
                    'skill_id': skill.id,
                    'skill_key': skill.key,
                    'interview_weight': interview_weight,
                    'eligible_for_random_sub_skill': eligible_for_random_sub_skill,
                }] if skill_role == JobInterviewSkill.SkillRole.SUB_SKILL else [],
                'optional_skills': [{
                    'skill_id': skill.id,
                    'skill_key': skill.key,
                    'interview_weight': interview_weight,
                    'eligible_for_random_sub_skill': eligible_for_random_sub_skill,
                }] if skill_role == JobInterviewSkill.SkillRole.OPTIONAL else [],
            },
            minimum_ready=True,
            fully_ready=True,
        )
        JobInterviewSkill.objects.create(
            blueprint=blueprint,
            job=vacancy,
            skill=skill,
            skill_role=skill_role,
            priority=1,
            questions_to_ask=5,
            coding_questions_to_ask=0,
            difficulty_mix={'basic': 2, 'intermediate': 3, 'advanced': 0},
            coding_difficulty_mix={'easy': 0, 'medium': 1, 'hard': 0},
            is_active=True,
        )
        return blueprint, skill

    def _coding_audit_blueprint(self, *, role='Core Java Developer', coding_required=True, targets=None, primary='Core Java', sub_skills=None, optional_skills=None, quality_warnings=None):
        targets = targets if targets is not None else [primary]
        sub_skills = sub_skills or []
        optional_skills = optional_skills or []
        vacancy = self._vacancy(role=role, description=f'{role} role.', experience_required='3-5 years')
        skill_specs = [(primary, 'Programming Language', JobInterviewSkill.SkillRole.PRIMARY)]
        skill_specs.extend((name, 'Programming Language', JobInterviewSkill.SkillRole.SUB_SKILL) for name in sub_skills)
        skill_specs.extend((name, 'Soft Skills', JobInterviewSkill.SkillRole.OPTIONAL) for name in optional_skills)
        skills = {}
        plans = []
        for index, (name, category, skill_role) in enumerate(skill_specs, start=1):
            key = name.lower().replace(' / ', '-').replace(' ', '-')
            skill = Skill.objects.create(name=name, key=key, category=category)
            skills[name] = skill
            plans.append({
                'skill_id': skill.id,
                'skill_key': skill.key,
                'name': skill.name,
                'skill': skill.name,
                'skill_role': skill_role,
                'role': skill_role,
                'target_questions': 5 if skill_role == JobInterviewSkill.SkillRole.PRIMARY else 3,
                'questions_to_ask': 5 if skill_role == JobInterviewSkill.SkillRole.PRIMARY else 3,
            })
        primary_item = next(item for item in plans if item['skill_role'] == JobInterviewSkill.SkillRole.PRIMARY)
        sub_items = [item for item in plans if item['skill_role'] == JobInterviewSkill.SkillRole.SUB_SKILL]
        optional_items = [item for item in plans if item['skill_role'] == JobInterviewSkill.SkillRole.OPTIONAL]
        blueprint_plan = ensure_blueprint_plan_signature({
            'role_family': 'technical' if coding_required else 'non_technical',
            'technical_interview': bool(coding_required),
            'coding_required': bool(coding_required),
            'coding_skill_targets': targets if coding_required else [],
            'coding_questions_to_ask': 3 if coding_required else 0,
            'primary_skill': primary_item,
            'sub_skills': sub_items,
            'optional_skills': optional_items,
            'runtime_sections': [primary_item, *sub_items],
            'interview_sections': [primary_item, *sub_items],
            'quality_warnings': quality_warnings or [],
        })
        blueprint = JobInterviewBlueprint.objects.create(
            job=vacancy,
            status=JobInterviewBlueprint.Status.READY,
            role_title=vacancy.role,
            experience_level='Mid-level (3-5 years)',
            blueprint_plan=blueprint_plan,
            minimum_ready=True,
            fully_ready=True,
        )
        for index, item in enumerate(plans, start=1):
            skill = skills[item['name']]
            JobInterviewSkill.objects.create(
                blueprint=blueprint,
                job=vacancy,
                skill=skill,
                skill_role=item['skill_role'],
                priority=index,
                questions_to_ask=item['questions_to_ask'],
                coding_questions_to_ask=3 if coding_required and skill.name in targets else 0,
                difficulty_mix={'basic': 1, 'intermediate': 2, 'advanced': 0},
                coding_difficulty_mix={'easy': 0, 'medium': 1, 'hard': 0},
                is_active=True,
            )
        return blueprint, vacancy, skills

    def _coding_question(self, skill, suffix):
        return CodingQuestion.objects.create(
            skill=skill,
            title=f'{skill.name} coding {suffix}',
            slug=f'{skill.key}-coding-{suffix}',
            prompt=f'Solve {skill.name} problem {suffix}.',
            prompt_hash=f'{skill.key}-{suffix}',
            difficulty=CodingQuestion.Difficulty.MEDIUM,
            question_type=CodingQuestion.QuestionType.ALGORITHM,
            family_key=f'{skill.key}-family',
            is_active=True,
        )

    def _signature_plan(self, *, primary=None, runtime_sections='default', sub_skills=None, coding_required=True, coding_skill_targets=None):
        primary = primary or {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java'}
        if runtime_sections == 'default':
            runtime_sections = [
                {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
                {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
            ]
        plan = {
            'primary_skill': primary,
            'sub_skills': sub_skills or [
                {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
            ],
            'coding_required': coding_required,
            'coding_skill_targets': coding_skill_targets if coding_skill_targets is not None else ['Core Java'],
        }
        if runtime_sections is not None:
            plan['runtime_sections'] = runtime_sections
        return plan

    def test_plan_signature_ignores_coding_target_order(self):
        first = self._signature_plan(coding_skill_targets=['SQL', 'ETL / ELT'])
        second = self._signature_plan(coding_skill_targets=['ETL / ELT', 'SQL'])

        self.assertEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_ignores_duplicate_coding_targets(self):
        first = self._signature_plan(coding_skill_targets=['SQL', 'ETL / ELT'])
        second = self._signature_plan(coding_skill_targets=['SQL', 'SQL', 'ETL / ELT'])

        self.assertEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_changes_when_coding_required_changes(self):
        first = self._signature_plan(coding_required=True)
        second = self._signature_plan(coding_required=False)

        self.assertNotEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_changes_when_primary_skill_changes(self):
        first = self._signature_plan(primary={'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java'})
        second = self._signature_plan(primary={'skill_id': 9, 'skill_key': 'python', 'name': 'Python'})

        self.assertNotEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_changes_when_runtime_sections_change(self):
        first = self._signature_plan(runtime_sections=[
            {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
            {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
        ])
        second = self._signature_plan(runtime_sections=[
            {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
            {'skill_id': 3, 'skill_key': 'rest-api', 'name': 'REST API', 'skill_role': 'sub_skill'},
        ])

        self.assertNotEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_preserves_runtime_section_order(self):
        first = self._signature_plan(runtime_sections=[
            {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
            {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
            {'skill_id': 3, 'skill_key': 'rest-api', 'name': 'REST API', 'skill_role': 'sub_skill'},
        ])
        second = self._signature_plan(runtime_sections=[
            {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
            {'skill_id': 3, 'skill_key': 'rest-api', 'name': 'REST API', 'skill_role': 'sub_skill'},
            {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
        ])

        self.assertNotEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_dedupes_repeated_runtime_sections(self):
        first = self._signature_plan(runtime_sections=[
            {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
            {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
        ])
        second = self._signature_plan(runtime_sections=[
            {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
            {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
            {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
        ])

        self.assertEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_uses_runtime_sections_over_sub_skills(self):
        runtime_sections = [
            {'skill_id': 1, 'skill_key': 'core-java', 'name': 'Core Java', 'skill_role': 'primary'},
            {'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'},
        ]
        first = self._signature_plan(
            runtime_sections=runtime_sections,
            sub_skills=[{'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'}],
        )
        second = self._signature_plan(
            runtime_sections=runtime_sections,
            sub_skills=[{'skill_id': 3, 'skill_key': 'rest-api', 'name': 'REST API', 'skill_role': 'sub_skill'}],
        )

        self.assertEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_plan_signature_falls_back_to_sub_skills_without_runtime_sections(self):
        first = self._signature_plan(
            runtime_sections=None,
            sub_skills=[{'skill_id': 2, 'skill_key': 'sql', 'name': 'SQL', 'skill_role': 'sub_skill'}],
        )
        second = self._signature_plan(
            runtime_sections=None,
            sub_skills=[{'skill_id': 3, 'skill_key': 'rest-api', 'name': 'REST API', 'skill_role': 'sub_skill'}],
        )

        self.assertNotEqual(blueprint_plan_signature(first), blueprint_plan_signature(second))

    def test_ensure_blueprint_plan_signature_does_not_mutate_original_dict(self):
        plan = self._signature_plan(coding_skill_targets=['SQL', 'ETL / ELT'])
        original = json.loads(json.dumps(plan))

        signed = ensure_blueprint_plan_signature(plan)

        self.assertEqual(plan, original)
        self.assertIsNot(signed, plan)
        self.assertIn('plan_signature', signed)
        self.assertNotIn('plan_signature', plan)

    def test_job_creation_succeeds_and_keeps_response_when_blueprint_enqueue_succeeds(self):
        with patch('smartInterviewApp.services.question_banks.generate_skill_questions_with_openai') as question_openai_mock:
            with patch('smartInterviewApp.services.interview_blueprints.enqueue_job_interview_blueprint') as enqueue_mock:
                enqueue_mock.return_value = {'queued': True, 'mode': 'cloud_tasks'}
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(reverse('add-role'), data=self._add_role_payload())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['Success'])
        self.assertEqual(payload['Data']['RoleDetails']['name'], 'Java Backend Developer')
        self.assertEqual(payload['Data']['RoleDetails']['vacancies'], 2)
        self.assertIn('job_type', payload['Data']['RoleDetails'])
        enqueue_mock.assert_called_once()
        question_openai_mock.assert_not_called()

    def test_job_update_save_does_not_call_question_generation_openai(self):
        vacancy = self._vacancy(role='Python Developer', description='Python role')
        with patch('smartInterviewApp.services.question_banks.generate_skill_questions_with_openai') as question_openai_mock:
            with patch('smartInterviewApp.services.interview_blueprints.enqueue_job_interview_blueprint') as enqueue_mock:
                enqueue_mock.return_value = {'queued': True, 'mode': 'cloud_tasks'}
                with self.captureOnCommitCallbacks(execute=True):
                    vacancy.description = 'Updated Python and Django role'
                    vacancy.save()

        enqueue_mock.assert_called_once()
        question_openai_mock.assert_not_called()

    def test_job_creation_succeeds_when_blueprint_enqueue_fails(self):
        with patch('smartInterviewApp.services.interview_blueprints.enqueue_job_interview_blueprint', side_effect=RuntimeError('queue down')):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse('add-role'), data=self._add_role_payload())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['Success'])
        self.assertTrue(Vacancies.objects.filter(role='Java Backend Developer').exists())

    def test_blueprint_enqueue_uses_post_commit_callback(self):
        with patch('smartInterviewApp.services.interview_blueprints.enqueue_job_interview_blueprint') as enqueue_mock:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                vacancy = Vacancies.objects.create(
                    role='Python Developer',
                    description='Python Django role',
                    position='1',
                    status='active',
                    admin=self.admin,
                )
                self.assertEqual(enqueue_mock.call_count, 0)

            self.assertEqual(len(callbacks), 1)
            self.assertEqual(enqueue_mock.call_count, 0)
            callbacks[0]()
            enqueue_mock.assert_called_once_with(vacancy.id)

    def test_build_job_interview_blueprint_is_idempotent_and_maps_aliases(self):
        core_java = Skill.objects.create(
            name='Core Java',
            key='core-java',
            category='Backend',
            aliases=['JVM', 'Java SE'],
        )
        sql = Skill.objects.create(
            name='SQL',
            key='sql',
            category='Database',
            aliases=['PostgreSQL', 'Joins'],
        )
        vacancy = Vacancies.objects.create(
            role='Backend Developer',
            description='Needs JVM internals and PostgreSQL joins. Java name is intentionally omitted.',
            position='1',
            status='active',
            admin=self.admin,
        )

        first = build_job_interview_blueprint(vacancy.id)
        second = build_job_interview_blueprint(vacancy.id)

        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.status, JobInterviewBlueprint.Status.PARTIAL)
        self.assertEqual(JobInterviewBlueprint.objects.filter(job=vacancy).count(), 1)
        self.assertEqual(JobInterviewSkill.objects.filter(blueprint=blueprint, skill=core_java).count(), 1)
        self.assertEqual(JobInterviewSkill.objects.filter(blueprint=blueprint, skill=sql).count(), 1)
        self.assertEqual(JobInterviewSkill.objects.filter(blueprint=blueprint).count(), 2)
        self.assertIn('core-java', [item['skill_key'] for item in blueprint.selected_skills_snapshot])

    def test_universal_full_stack_extraction_maps_and_creates_broad_skill_pool(self):
        Skill.objects.create(name='JavaScript', key='javascript', category='Programming Language')
        Skill.objects.create(name='Python', key='python', category='Programming Language')
        vacancy = self._vacancy(
            description='0-3 years Full Stack Developer with JavaScript, Python, React Native, MongoDB, MySQL and RESTful APIs.',
        )

        result = self._build_with_mocked_openai(vacancy, self._mock_payload(sub_skills=[
            {'name': 'React Native', 'category': 'Mobile Development', 'confidence': 0.9},
            {'name': 'MongoDB', 'category': 'Database', 'confidence': 0.85},
            {'name': 'MySQL', 'category': 'Database', 'confidence': 0.82},
            {'name': 'RESTful APIs', 'category': 'Web Services', 'confidence': 0.82},
        ]))

        self.assertTrue(result['ok'])
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.experience_level, 'Entry-level (0-3 years)')
        names = self._skill_names_for_blueprint(blueprint)
        self.assertTrue({'JavaScript', 'Python', 'React Native', 'MongoDB', 'MySQL', 'REST API'}.issubset(names))
        self.assertEqual(blueprint.blueprint_plan['blueprint_version'], 2)
        self.assertIn('runtime_policy', blueprint.blueprint_plan)
        self.assertEqual(blueprint.blueprint_plan['runtime_policy']['sub_skills_to_pick'], 3)

    def test_auto_create_missing_skills_and_restful_api_normalization(self):
        vacancy = self._vacancy(description='React Native, MongoDB and RESTful APIs are required.')

        self._build_with_mocked_openai(vacancy, self._mock_payload())

        self.assertTrue(Skill.objects.filter(name='React Native', key='react-native').exists())
        self.assertTrue(Skill.objects.filter(name='MongoDB', key='mongodb').exists())
        self.assertTrue(Skill.objects.filter(name='REST API', key='rest-api').exists())
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertTrue({'React Native', 'MongoDB', 'REST API'}.issubset(self._skill_names_for_blueprint(blueprint)))

    def test_missing_skills_are_not_created_when_auto_create_disabled(self):
        vacancy = self._vacancy(description='React Native and MongoDB are required.')

        result = self._build_with_mocked_openai(vacancy, self._mock_payload(), create_missing=False)

        self.assertFalse(result['ok'])
        self.assertFalse(Skill.objects.filter(name='React Native').exists())
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertGreaterEqual(len(blueprint.raw_extracted_skills), 1)
        self.assertIn('unmapped_skills', blueprint.blueprint_plan)
        self.assertTrue(any(item['name'] == 'React Native' for item in blueprint.blueprint_plan['unmapped_skills']))

    def test_skill_name_normalization_maps_common_aliases(self):
        for name in ['React', 'MongoDB', 'REST API', 'Node.js', 'Next.js', 'PHP']:
            Skill.objects.create(name=name, key=name.lower().replace('.', '-').replace('/', '-').replace(' ', '-'))
        vacancy = self._vacancy(description='ReactJs, React.js, Mongo DB, RESTful APIs, NodeJS, NextJs and Php.')
        payload = self._mock_payload(sub_skills=[
            {'name': 'ReactJs', 'category': 'Frontend Development', 'confidence': 0.9},
            {'name': 'React.js', 'category': 'Frontend Development', 'confidence': 0.9},
            {'name': 'Mongo DB', 'category': 'Database', 'confidence': 0.9},
            {'name': 'RESTful APIs', 'category': 'Web Services', 'confidence': 0.9},
            {'name': 'NodeJS', 'category': 'Backend Development', 'confidence': 0.9},
            {'name': 'NextJs', 'category': 'Frontend Development', 'confidence': 0.9},
            {'name': 'Php', 'category': 'Backend Development', 'confidence': 0.9},
        ])

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        names = self._skill_names_for_blueprint(blueprint)
        self.assertTrue({'React', 'MongoDB', 'REST API', 'Node.js', 'Next.js', 'PHP'}.issubset(names))
        self.assertEqual(JobInterviewSkill.objects.filter(blueprint=blueprint, skill__name='React').count(), 1)

    def test_non_technical_hr_marketing_and_accounting_skills_are_created(self):
        scenarios = [
            ('HR Recruiter', ['Talent Acquisition', 'Candidate Sourcing', 'Candidate Screening', 'Interview Coordination', 'ATS']),
            ('Digital Marketing Executive', ['SEO', 'Social Media Marketing', 'Campaign Management', 'Content Writing', 'Google Analytics']),
            ('Accountant', ['Tally', 'GST', 'Bookkeeping', 'Reconciliation', 'Financial Reporting']),
        ]
        for role, skills in scenarios:
            vacancy = self._vacancy(role=role, description=', '.join(skills), experience_required='1-3 years')
            payload = self._mock_payload(
                role_title=role,
                primary=skills[0],
                sub_skills=[{'name': name, 'category': role, 'confidence': 0.9} for name in skills[1:]],
            )

            self._build_with_mocked_openai(vacancy, payload)

            blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
            self.assertTrue(set(skills).issubset(self._skill_names_for_blueprint(blueprint)))

    def test_noisy_terms_are_not_created_as_skills(self):
        noisy_terms = ['full time', 'permanent', 'B.Tech', 'MCA', 'quick learner', 'team player', 'projects']
        vacancy = self._vacancy(role='Python Developer', description=', '.join(noisy_terms))
        payload = self._mock_payload(
            primary='full time',
            sub_skills=[{'name': name, 'category': 'Noise', 'confidence': 0.95} for name in noisy_terms[1:]],
            optional_skills=[],
        )

        self._build_with_mocked_openai(vacancy, payload)

        for term in noisy_terms:
            self.assertFalse(Skill.objects.filter(key__in=[term.lower().replace('.', '').replace(' ', '-'), term.lower().replace(' ', '-')]).exists())
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(len(blueprint.blueprint_plan['rejected_skills']), len(noisy_terms))

    def test_experience_correction_overrides_openai_output(self):
        entry_vacancy = self._vacancy(description='Full Stack Developer, 0-3 years experience.', experience_required='0-3 years')
        mid_vacancy = self._vacancy(role='Java Developer', description='Java Developer with 3-5 years experience.', experience_required='3-5 years')

        self._build_with_mocked_openai(entry_vacancy, self._mock_payload(experience_level='Mid-level (5-10 years)'))
        self._build_with_mocked_openai(mid_vacancy, self._mock_payload(role_title='Java Developer', primary='Core Java', experience_level='Senior (5-8 years)'))

        self.assertEqual(JobInterviewBlueprint.objects.get(job=entry_vacancy).experience_level, 'Entry-level (0-3 years)')
        self.assertEqual(JobInterviewBlueprint.objects.get(job=mid_vacancy).experience_level, 'Mid-level (3-5 years)')

    def test_entry_level_difficulty_mix_has_no_advanced_questions(self):
        vacancy = self._vacancy(description='Full Stack Developer, 0-3 years experience.', experience_required='0-3 years')

        self._build_with_mocked_openai(vacancy, self._mock_payload())

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        primary_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill_role=JobInterviewSkill.SkillRole.PRIMARY)
        self.assertEqual(primary_plan.difficulty_mix['advanced'], 0)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['difficulty_mix']['advanced'], 0)

    def test_blueprint_plan_contains_required_structure(self):
        vacancy = self._vacancy(description='JavaScript, React Native and MongoDB.')

        self._build_with_mocked_openai(vacancy, self._mock_payload())

        plan = JobInterviewBlueprint.objects.get(job=vacancy).blueprint_plan
        for key in [
            'blueprint_version',
            'role_title',
            'role_family',
            'technical_interview',
            'experience_level',
            'primary_skill',
            'primary_skill_candidates',
            'sub_skills',
            'optional_skills',
            'coding_required',
            'coding_skill_targets',
            'coding_questions_to_ask',
            'runtime_sections',
            'interview_sections',
            'runtime_policy',
        ]:
            self.assertIn(key, plan)

    def test_auto_created_blueprint_build_is_idempotent(self):
        vacancy = self._vacancy(description='JavaScript, React Native, MongoDB and RESTful APIs.')
        payload = self._mock_payload()

        self._build_with_mocked_openai(vacancy, payload)
        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(JobInterviewBlueprint.objects.filter(job=vacancy).count(), 1)
        self.assertEqual(Skill.objects.filter(key='react-native').count(), 1)
        self.assertEqual(Skill.objects.filter(key='mongodb').count(), 1)
        self.assertEqual(Skill.objects.filter(key='rest-api').count(), 1)
        self.assertEqual(JobInterviewSkill.objects.filter(blueprint=blueprint).count(), len(set(JobInterviewSkill.objects.filter(blueprint=blueprint).values_list('skill_id', flat=True))))

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_ensure_question_bank_for_skill_queues_when_below_target(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')

        result = ensure_question_bank_for_skill(skill.id)

        self.assertEqual(result['verbal']['status'], 'queued')
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill, task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).count(), 1)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_blueprint_question_bank_primary_skill_queues_generation(self):
        blueprint, skill = self._blueprint_with_planned_skill(JobInterviewSkill.SkillRole.PRIMARY)

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertEqual(results[0]['verbal']['status'], 'queued')
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill).count(), 1)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_blueprint_question_bank_primary_candidate_queues_generation(self):
        blueprint, skill = self._blueprint_with_planned_skill(JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE)

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertEqual(results[0]['verbal']['status'], 'queued')
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill).count(), 1)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_blueprint_question_bank_eligible_normal_sub_skill_queues_generation(self):
        blueprint, skill = self._blueprint_with_planned_skill(
            JobInterviewSkill.SkillRole.SUB_SKILL,
            interview_weight='normal',
            eligible_for_random_sub_skill=True,
        )

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertEqual(results[0]['verbal']['status'], 'queued')
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill).count(), 1)

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
    )
    def test_blueprint_generation_enqueues_question_jobs_without_processing_question_generation(self):
        vacancy = self._vacancy(description='JavaScript, Python and REST API.')

        with patch('smartInterviewApp.services.question_banks.generate_skill_questions_with_openai') as generate_mock:
            with patch('smartInterviewApp.services.question_banks.process_question_generation_task') as process_mock:
                with self.captureOnCommitCallbacks(execute=True):
                    result = self._build_with_mocked_openai(vacancy, self._mock_payload(sub_skills=[
                        {'name': 'Python', 'category': 'Backend Development', 'confidence': 0.88},
                        {'name': 'REST API', 'category': 'Web Services', 'confidence': 0.82},
                    ]))

        self.assertTrue(result['ok'])
        self.assertGreaterEqual(QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION, status=QuestionGenerationJob.Status.QUEUED).count(), 1)
        generate_mock.assert_not_called()
        process_mock.assert_not_called()

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
        INTERVIEW_QUESTION_BANK_MAX_SKILLS_PER_BLUEPRINT_ENQUEUE=2,
    )
    def test_blueprint_auto_enqueue_caps_max_skills(self):
        vacancy = self._vacancy(role='Full Stack Developer', description='Python React MongoDB REST API SQL')
        blueprint = JobInterviewBlueprint.objects.create(
            job=vacancy,
            status=JobInterviewBlueprint.Status.READY,
            role_title=vacancy.role,
            experience_level='Entry-level (0-3 years)',
            blueprint_plan={},
            minimum_ready=True,
            fully_ready=True,
        )
        for index, name in enumerate(['Python', 'React', 'MongoDB', 'REST API'], start=1):
            skill = Skill.objects.create(name=name, key=name.lower().replace(' ', '-'), category='Programming Language')
            JobInterviewSkill.objects.create(
                blueprint=blueprint,
                job=vacancy,
                skill=skill,
                skill_role=JobInterviewSkill.SkillRole.PRIMARY_CANDIDATE,
                priority=index,
                questions_to_ask=5,
                coding_questions_to_ask=0,
                is_active=True,
            )

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertEqual(QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).count(), 2)
        self.assertEqual(sum(1 for item in results if item.get('status') == 'skipped_max_blueprint_enqueue_limit'), 2)

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
        INTERVIEW_SKILL_CODING_TARGET_COUNT=0,
    )
    def test_required_coding_jobs_are_created_when_coding_target_setting_is_zero(self):
        blueprint, skill = self._blueprint_with_planned_skill(JobInterviewSkill.SkillRole.PRIMARY)
        JobInterviewSkill.objects.filter(blueprint=blueprint, skill=skill).update(coding_questions_to_ask=1)
        blueprint.blueprint_plan.update({
            'coding_required': True,
            'coding_skill_targets': [skill.name],
            'coding_questions_to_ask': 3,
        })
        blueprint.save(update_fields=['blueprint_plan'])

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertTrue(any(item.get('task_type') == QuestionGenerationJob.TaskType.CODING_GENERATION for item in results))
        self.assertTrue(QuestionGenerationJob.objects.filter(skill=skill, task_type=QuestionGenerationJob.TaskType.CODING_GENERATION).exists())

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_blueprint_question_bank_optional_skill_is_skipped(self):
        blueprint, skill = self._blueprint_with_planned_skill(JobInterviewSkill.SkillRole.OPTIONAL)

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertEqual(results[0]['status'], 'skipped_optional_or_low_weight')
        self.assertEqual(results[0]['skill_role'], JobInterviewSkill.SkillRole.OPTIONAL)
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill).count(), 0)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_blueprint_question_bank_low_weight_sub_skill_is_skipped(self):
        blueprint, skill = self._blueprint_with_planned_skill(
            JobInterviewSkill.SkillRole.SUB_SKILL,
            interview_weight='low',
            eligible_for_random_sub_skill=True,
        )

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertEqual(results[0]['status'], 'skipped_optional_or_low_weight')
        self.assertEqual(results[0]['interview_weight'], 'low')
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill).count(), 0)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_blueprint_question_bank_ineligible_sub_skill_is_skipped(self):
        blueprint, skill = self._blueprint_with_planned_skill(
            JobInterviewSkill.SkillRole.SUB_SKILL,
            interview_weight='normal',
            eligible_for_random_sub_skill=False,
        )

        results = ensure_question_bank_for_blueprint(blueprint.id)

        self.assertEqual(results[0]['status'], 'skipped_optional_or_low_weight')
        self.assertFalse(results[0]['eligible_for_random_sub_skill'])
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill).count(), 0)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=1)
    def test_ensure_question_bank_for_skill_does_not_queue_when_enough(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        SkillQuestion.objects.create(
            skill=skill,
            question_text='What is Python?',
            question_hash='python-basic',
            difficulty=SkillQuestion.Difficulty.BASIC,
            question_type=SkillQuestion.QuestionType.CONCEPT,
            family_key='python-basics',
        )

        result = ensure_question_bank_for_skill(skill.id)

        self.assertEqual(result['verbal']['status'], 'enough_questions')
        self.assertFalse(QuestionGenerationJob.objects.filter(skill=skill, task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).exists())

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=2)
    def test_question_pool_resolves_canonical_python_skill_equivalents(self):
        runtime_skill = Skill.objects.create(name='Python Backend', key='python-backend', category='Backend Development')
        exact_skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        alias_skill = Skill.objects.create(name='Backend Language', key='backend-language', aliases=['Core Python'], category='Programming Language')
        other_skill = Skill.objects.create(name='Java', key='java', category='Programming Language')

        equivalent_ids = resolve_equivalent_skill_ids_for_question_pool(runtime_skill)

        self.assertIn(runtime_skill.id, equivalent_ids)
        self.assertIn(exact_skill.id, equivalent_ids)
        self.assertIn(alias_skill.id, equivalent_ids)
        self.assertNotIn(other_skill.id, equivalent_ids)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=1)
    def test_ensure_question_bank_for_skill_uses_canonical_question_pool(self):
        runtime_skill = Skill.objects.create(name='Python Backend', key='python-backend', category='Backend Development')
        existing_skill = Skill.objects.create(name='Core Python', key='core-python', category='Programming Language')
        SkillQuestion.objects.create(
            skill=existing_skill,
            question_text='How do Python decorators work?',
            question_hash='python-decorators',
            difficulty=SkillQuestion.Difficulty.INTERMEDIATE,
            question_type=SkillQuestion.QuestionType.CONCEPT,
            family_key='decorators',
            coverage_area='decorators',
            expected_signal='Understands decorator wrapping and use cases.',
            quality_status=SkillQuestion.QualityStatus.APPROVED,
            is_active=True,
        )

        result = ensure_question_bank_for_skill(runtime_skill.id)

        self.assertEqual(result['verbal']['status'], 'enough_questions')
        self.assertIn(existing_skill.id, result['equivalent_skill_ids'])
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=runtime_skill, task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).count(), 0)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_ensure_question_bank_for_skill_dedupes_queued_or_running_generation_job(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        existing = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
        )

        result = ensure_question_bank_for_skill(skill.id)

        self.assertEqual(result['verbal']['status'], 'already_queued_or_running')
        self.assertEqual(result['verbal']['generation_job_id'], existing.id)
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill, task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).count(), 1)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=True, INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3)
    def test_similar_jobs_do_not_create_duplicate_question_generation_jobs_for_python(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')

        ensure_question_bank_for_skill(skill.id)
        ensure_question_bank_for_skill(skill.id)

        self.assertEqual(Skill.objects.filter(key='python').count(), 1)
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill, task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).count(), 1)

    def test_generated_skill_questions_are_inserted_and_duplicates_skipped(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        questions = [
            {
                'question_text': 'What is Python list comprehension?',
                'difficulty': 'basic',
                'question_type': 'concept',
                'family_key': 'list-comprehension',
                'coverage_area': 'list_comprehension',
                'expected_signal': 'Understands concise list creation.',
                'ideal_answer_points': ['syntax', 'use cases'],
                'evaluation_rubric': {'strong': 'clear', 'average': 'partial', 'weak': 'incorrect'},
                'tags': ['python'],
            },
            {
                'question_text': 'Can you explain list comprehensions in Python?',
                'difficulty': 'basic',
                'question_type': 'concept',
                'family_key': 'list-comprehension',
                'coverage_area': 'list_comprehension',
                'expected_signal': 'Same concept.',
                'ideal_answer_points': [],
                'evaluation_rubric': {},
                'tags': [],
            },
            {
                'question_text': 'What is Python list comprehension?',
                'difficulty': 'basic',
                'question_type': 'concept',
                'family_key': 'list-comprehension',
                'coverage_area': 'list_comprehension',
                'expected_signal': 'Exact duplicate.',
                'ideal_answer_points': [],
                'evaluation_rubric': {},
                'tags': [],
            },
        ]

        stats = insert_skill_questions(skill, questions)

        self.assertEqual(stats['inserted_count'], 1)
        self.assertEqual(stats['duplicate_skipped_count'], 2)
        self.assertEqual(SkillQuestion.objects.filter(skill=skill).count(), 1)
        self.assertTrue(SkillQuestion.objects.get(skill=skill).question_hash)

    @override_settings(INTERVIEW_QUESTION_BANK_OPENAI_ENABLED=True, OPENAI_API_KEY='test-key')
    def test_question_generation_task_inserts_skill_questions(self):
        skill = Skill.objects.create(name='Talent Acquisition', key='talent-acquisition', category='Human Resources')
        generation_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
            payload={'skill_id': skill.id, 'target_verbal_questions': 2, 'batch_size': 1},
        )
        generated = [{
            'question_text': 'How do you build a candidate sourcing strategy?',
            'difficulty': 'intermediate',
            'question_type': 'scenario',
            'family_key': 'candidate-sourcing',
            'coverage_area': 'candidate_sourcing',
            'expected_signal': 'Uses channels and prioritization.',
            'ideal_answer_points': ['channels', 'screening'],
            'evaluation_rubric': {'strong': 'structured', 'average': 'some structure', 'weak': 'generic'},
            'tags': ['hr'],
        }]

        with patch('smartInterviewApp.services.question_banks.generate_skill_questions_with_openai', return_value=generated):
            result = process_question_generation_task(generation_job.id)

        self.assertTrue(result['ok'])
        self.assertEqual(result['inserted_count'], 1)
        self.assertTrue(SkillQuestion.objects.filter(skill=skill, question_text__icontains='candidate sourcing').exists())

    def test_question_generation_success_replay_and_recent_running_replay_are_safe(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        success_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.SUCCESS,
        )
        running_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=2),
        )

        with patch(
            'smartInterviewApp.services.question_banks.build_skill_question_bank',
            return_value={'ok': True, 'status': 'completed', 'skill_id': skill.id},
        ) as build_mock:
            success = process_question_generation_task(success_job.id)
            running = process_question_generation_task(running_job.id)

        self.assertEqual(success['status'], 'already_processed')
        self.assertEqual(running['status'], 'already_running')
        build_mock.assert_not_called()

    def test_stale_running_question_generation_job_can_be_retried(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        stale_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.RUNNING,
            attempts=1,
            started_at=timezone.now() - timedelta(minutes=30),
            payload={'skill_id': skill.id, 'target_verbal_questions': 1, 'batch_size': 1},
        )

        with patch('smartInterviewApp.services.question_banks.build_skill_question_bank', return_value={'ok': True, 'status': 'completed', 'skill_id': skill.id}):
            result = process_question_generation_task(stale_job.id)

        self.assertEqual(result['status'], 'completed')
        stale_job.refresh_from_db()
        self.assertEqual(stale_job.status, QuestionGenerationJob.Status.SUCCESS)
        self.assertEqual(stale_job.attempts, 2)

    @override_settings(INTERVIEW_QUESTION_BANK_OPENAI_ENABLED=True, OPENAI_API_KEY='test-key', INTERVIEW_QUESTION_GENERATION_MAX_ATTEMPTS=1)
    def test_timeout_in_openai_question_generation_marks_job_failed_cleanly(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        generation_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
            payload={'skill_id': skill.id, 'target_verbal_questions': 1, 'batch_size': 1},
        )
        error = OpenAIQuestionGenerationError(
            'OpenAI question generation timed out after 60 seconds.',
            error_type='timeout',
            retryable=True,
        )

        with patch('smartInterviewApp.services.question_banks._call_openai_json', side_effect=error):
            result = process_question_generation_task(generation_job.id)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'timeout')
        generation_job.refresh_from_db()
        self.assertEqual(generation_job.status, QuestionGenerationJob.Status.FAILED)
        self.assertEqual(generation_job.result['error_type'], 'timeout')

    @override_settings(INTERVIEW_QUESTION_BANK_OPENAI_ENABLED=True, OPENAI_API_KEY='test-key')
    def test_http_400_question_generation_marks_bad_request_and_is_not_immediately_retried(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        generation_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
            payload={'skill_id': skill.id, 'target_verbal_questions': 1, 'batch_size': 1},
        )
        error = OpenAIQuestionGenerationError(
            'OpenAI question generation bad request HTTP 400: schema rejected',
            error_type='failed_schema_or_bad_request',
            retryable=False,
            status_code=400,
            body_preview='schema rejected',
        )

        with patch('smartInterviewApp.services.question_banks._call_openai_json', side_effect=error):
            result = process_question_generation_task(generation_job.id)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'failed_schema_or_bad_request')
        generation_job.refresh_from_db()
        self.assertEqual(generation_job.status, QuestionGenerationJob.Status.FAILED)
        self.assertEqual(generation_job.attempts, 1)

        retry_results = process_question_generation_queue(limit=1)

        self.assertEqual(retry_results, [])
        generation_job.refresh_from_db()
        self.assertEqual(generation_job.attempts, 1)

    @override_settings(INTERVIEW_QUESTION_BANK_WORKER_LIMIT=1)
    def test_worker_command_default_limit_uses_setting(self):
        skills = [
            Skill.objects.create(name='Python', key='python', category='Programming Language'),
            Skill.objects.create(name='React', key='react', category='Frontend Development'),
        ]
        for skill in skills:
            QuestionGenerationJob.objects.create(
                skill=skill,
                task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
                status=QuestionGenerationJob.Status.QUEUED,
                payload={'skill_id': skill.id, 'target_verbal_questions': 1, 'batch_size': 1},
            )

        out = StringIO()
        with patch('smartInterviewApp.services.question_banks.build_skill_question_bank', side_effect=lambda skill_id, task_type, payload: {'ok': True, 'status': 'completed', 'skill_id': skill_id}):
            call_command('process_question_generation_queue', stdout=out)

        self.assertIn('Processed 1 question generation jobs.', out.getvalue())
        self.assertEqual(QuestionGenerationJob.objects.filter(status=QuestionGenerationJob.Status.SUCCESS).count(), 1)
        self.assertEqual(QuestionGenerationJob.objects.filter(status=QuestionGenerationJob.Status.QUEUED).count(), 1)

    def test_worker_command_explicit_limit_processes_only_one_job(self):
        skills = [
            Skill.objects.create(name='Python', key='python', category='Programming Language'),
            Skill.objects.create(name='React', key='react', category='Frontend Development'),
        ]
        for skill in skills:
            QuestionGenerationJob.objects.create(
                skill=skill,
                task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
                status=QuestionGenerationJob.Status.QUEUED,
                payload={'skill_id': skill.id, 'target_verbal_questions': 1, 'batch_size': 1},
            )

        out = StringIO()
        with patch('smartInterviewApp.services.question_banks.build_skill_question_bank', side_effect=lambda skill_id, task_type, payload: {'ok': True, 'status': 'completed', 'skill_id': skill_id}):
            call_command('process_question_generation_queue', '--limit', '1', stdout=out)

        self.assertIn('Processed 1 question generation jobs.', out.getvalue())
        self.assertEqual(QuestionGenerationJob.objects.filter(status=QuestionGenerationJob.Status.SUCCESS).count(), 1)
        self.assertEqual(QuestionGenerationJob.objects.filter(status=QuestionGenerationJob.Status.QUEUED).count(), 1)

    def test_worker_queue_processes_only_explicit_limit(self):
        skills = [
            Skill.objects.create(name='Python', key='python', category='Programming Language'),
            Skill.objects.create(name='React', key='react', category='Frontend Development'),
        ]
        for skill in skills:
            QuestionGenerationJob.objects.create(
                skill=skill,
                task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
                status=QuestionGenerationJob.Status.QUEUED,
                payload={'skill_id': skill.id, 'target_verbal_questions': 1, 'batch_size': 1},
            )

        with patch('smartInterviewApp.services.question_banks.build_skill_question_bank', side_effect=lambda skill_id, task_type, payload: {'ok': True, 'status': 'completed', 'skill_id': skill_id}):
            results = process_question_generation_queue(limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(QuestionGenerationJob.objects.filter(status=QuestionGenerationJob.Status.SUCCESS).count(), 1)
        self.assertEqual(QuestionGenerationJob.objects.filter(status=QuestionGenerationJob.Status.QUEUED).count(), 1)

    def test_worker_lock_selection_uses_job_rows_without_related_joins(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        queued_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
        )
        stale_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.RUNNING,
            started_at=timezone.now(),
        )
        stale_cutoff = timezone.now() - timedelta(minutes=20)

        locked_queryset = _worker_lock_queryset(
            [QuestionGenerationJob.TaskType.QUESTION_GENERATION],
            stale_cutoff,
        ).select_for_update()

        self.assertTrue(locked_queryset.query.select_for_update)
        self.assertFalse(locked_queryset.query.select_related)
        self.assertNotIn('JOIN', str(locked_queryset.query).upper())

        selected_ids = _select_question_generation_job_ids(
            5,
            task_types=[QuestionGenerationJob.TaskType.QUESTION_GENERATION],
            stale_cutoff=stale_cutoff,
        )

        self.assertEqual(selected_ids, [queued_job.id, stale_job.id])

    @override_settings(CLOUD_TASKS_SHARED_SECRET='secret')
    def test_skill_question_bank_endpoint_rejects_missing_or_invalid_secret_and_accepts_valid_secret(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        generation_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
        )
        payload = {'generation_job_id': generation_job.id, 'skill_id': skill.id, 'task_type': QuestionGenerationJob.TaskType.QUESTION_GENERATION}

        missing = self.client.post(reverse('internal-generate-skill-question-bank'), data=json.dumps(payload), content_type='application/json')
        invalid = self.client.post(reverse('internal-generate-skill-question-bank'), data=json.dumps(payload), content_type='application/json', HTTP_X_CLOUD_TASKS_SECRET='wrong')
        with patch('smartInterviewApp.views.process_question_generation_task', return_value={'ok': True, 'status': 'completed'}):
            valid = self.client.post(reverse('internal-generate-skill-question-bank'), data=json.dumps(payload), content_type='application/json', HTTP_X_CLOUD_TASKS_SECRET='secret')

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.json()['Success'])

    @override_settings(CLOUD_TASKS_SHARED_SECRET='secret')
    def test_question_generation_queue_endpoint_rejects_bad_secret(self):
        response = self.client.post(
            reverse('internal-process-question-generation-queue'),
            data=json.dumps({}),
            content_type='application/json',
            HTTP_X_CLOUD_TASKS_SECRET='wrong',
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['Success'])

    @override_settings(CLOUD_TASKS_SHARED_SECRET='secret', INTERVIEW_QUESTION_BANK_WORKER_LIMIT=1)
    def test_question_generation_queue_endpoint_returns_processed_zero_when_empty(self):
        response = self.client.post(
            reverse('internal-process-question-generation-queue'),
            data=json.dumps({}),
            content_type='application/json',
            HTTP_X_CLOUD_TASKS_SECRET='secret',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['Data']['processed'], 0)
        self.assertEqual(response.json()['Data']['processed_count'], 0)

    @override_settings(CLOUD_TASKS_SHARED_SECRET='secret', INTERVIEW_SKILL_CODING_TARGET_COUNT=0, INTERVIEW_QUESTION_BANK_WORKER_LIMIT=1)
    def test_question_generation_queue_endpoint_processes_explicit_coding_generation_target(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        generation_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
            payload={'skill_id': skill.id, 'target_coding_questions': 1, 'batch_size': 1},
        )

        with patch(
            'smartInterviewApp.services.question_banks.build_skill_question_bank',
            return_value={'ok': True, 'status': 'completed', 'skill_id': skill.id},
        ) as build_mock:
            response = self.client.post(
                reverse('internal-process-question-generation-queue'),
                data=json.dumps({}),
                content_type='application/json',
                HTTP_X_CLOUD_TASKS_SECRET='secret',
            )

        self.assertEqual(response.status_code, 200)
        build_mock.assert_called_once()
        generation_job.refresh_from_db()
        self.assertEqual(generation_job.status, QuestionGenerationJob.Status.SUCCESS)

    @override_settings(CLOUD_TASKS_SHARED_SECRET='secret')
    def test_question_generation_queue_endpoint_catches_processor_exception(self):
        with patch('smartInterviewApp.views.process_question_generation_queue', side_effect=RuntimeError('processor boom')):
            response = self.client.post(
                reverse('internal-process-question-generation-queue'),
                data=json.dumps({}),
                content_type='application/json',
                HTTP_X_CLOUD_TASKS_SECRET='secret',
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['Success'])
        self.assertEqual(payload['Data']['error_class'], 'RuntimeError')

    @override_settings(
        CLOUD_TASKS_SHARED_SECRET='secret',
        INTERVIEW_QUESTION_BANK_WORKER_LIMIT=1,
        INTERVIEW_QUESTION_GENERATION_MAX_ATTEMPTS=1,
    )
    def test_question_generation_queue_endpoint_saves_failed_question_generation_job(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        generation_job = QuestionGenerationJob.objects.create(
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
            payload={'skill_id': skill.id, 'target_verbal_questions': 1, 'batch_size': 1},
        )

        with patch('smartInterviewApp.services.question_banks.build_skill_question_bank', side_effect=RuntimeError('openai timeout')):
            response = self.client.post(
                reverse('internal-process-question-generation-queue'),
                data=json.dumps({}),
                content_type='application/json',
                HTTP_X_CLOUD_TASKS_SECRET='secret',
            )

        self.assertEqual(response.status_code, 200)
        generation_job.refresh_from_db()
        self.assertEqual(generation_job.status, QuestionGenerationJob.Status.FAILED)
        self.assertEqual(generation_job.result['error_type'], 'runtime_error')
        self.assertIn('openai timeout', generation_job.error_message)

    def test_php_laravel_or_alternates_are_optional_for_full_stack_jd(self):
        vacancy = self._vacancy(description='Use JavaScript and Node.js or Python or Laravel. PHP is optional.', experience_required='0-3 years')
        payload = self._mock_payload(
            primary='JavaScript',
            sub_skills=[
                {'name': 'Node.js', 'category': 'Backend Development', 'confidence': 0.9},
                {'name': 'Python', 'category': 'Backend Development', 'confidence': 0.85},
                {'name': 'PHP', 'category': 'Backend Development', 'confidence': 0.7},
                {'name': 'Laravel', 'category': 'Backend Development', 'confidence': 0.7},
            ],
        )

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        optional_names = {item['name'] for item in blueprint.blueprint_plan['optional_skills']}
        self.assertTrue({'PHP', 'Laravel'}.issubset(optional_names))

    def test_agile_is_low_weight_optional_for_technical_developer_jd(self):
        vacancy = self._vacancy(description='Python Developer using Django and Agile Scrum practices.', experience_required='1-3 years')
        payload = self._mock_payload(
            primary='Python',
            sub_skills=[
                {'name': 'Django', 'category': 'Backend Development', 'confidence': 0.9},
                {'name': 'Agile', 'category': 'Process', 'confidence': 0.8},
            ],
        )

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        agile = next(item for item in blueprint.blueprint_plan['optional_skills'] if item['name'] == 'Agile')
        self.assertEqual(agile['interview_weight'], 'low')
        self.assertFalse(agile['eligible_for_random_sub_skill'])

    def test_core_java_developer_promotes_concrete_technical_primary(self):
        vacancy = self._vacancy(
            role='Core Java Developer',
            description='Core Java collections, JVM fundamentals, multithreading and REST API development.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Core Java Developer',
            primary='Communication Skills',
            sub_skills=[
                {'name': 'Core Java', 'category': 'Programming Language', 'confidence': 0.95},
                {'name': 'REST API', 'category': 'API/Web Services', 'confidence': 0.8},
            ],
        )

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'Core Java')
        primary_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill_role=JobInterviewSkill.SkillRole.PRIMARY)
        self.assertEqual(primary_plan.skill.name, 'Core Java')
        self.assertNotEqual(primary_plan.skill.name, 'Communication Skills')

    def test_core_java_runtime_sections_are_authoritative_and_exclude_database(self):
        vacancy = self._vacancy(
            role='Core Java Developer',
            description='Core Java collections, JVM fundamentals, multithreading and REST API development. SQL is only a nice-to-have.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Core Java Developer',
            primary='Core Java',
            sub_skills=[
                {'name': 'Multithreading', 'category': 'Programming Language', 'confidence': 0.92},
                {'name': 'REST API', 'category': 'API/Web Services', 'confidence': 0.86},
                {'name': 'SQL', 'category': 'Database', 'confidence': 0.65},
            ],
            optional_skills=[{'name': 'SQL', 'category': 'Database', 'confidence': 0.65}],
        )
        payload.update({
            'role_domain': 'Technology',
            'role_subdomain': 'Backend Java',
            'runtime_sections': [
                {'name': 'Core Java', 'category': 'Programming Language', 'skill_role': 'primary', 'target_questions': 5, 'selection_basis': 'primary skill in title and JD', 'reason': 'Central execution skill.', 'confidence': 0.96},
                {'name': 'Multithreading', 'category': 'Programming Language', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'Java-adjacent JD requirement', 'reason': 'Explicitly required for runtime behavior.', 'confidence': 0.92},
                {'name': 'REST API', 'category': 'API/Web Services', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'Java-adjacent service work', 'reason': 'Explicit API development responsibility.', 'confidence': 0.86},
            ],
            'coding_required': True,
            'coding_primary_skill': 'Core Java',
            'coding_questions_to_ask': 1,
            'excluded_skills': [{'name': 'SQL', 'category': 'Database', 'reason': 'Useful but not central to this Core Java JD.'}],
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        runtime_names = [section['name'] for section in blueprint.blueprint_plan['runtime_sections']]
        self.assertEqual(runtime_names, ['Core Java', 'Multithreading', 'REST API'])
        self.assertEqual(blueprint.blueprint_plan['excluded_skills'][0]['name'], 'SQL')
        sql_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill__name='SQL')
        self.assertEqual(sql_plan.skill_role, JobInterviewSkill.SkillRole.OPTIONAL)

    def test_missing_only_uses_runtime_sections_without_ready_section_replacement(self):
        vacancy = self._vacancy(
            role='Core Java Developer',
            description='Core Java collections, multithreading and REST API development. SQL is only a nice-to-have.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Core Java Developer',
            primary='Core Java',
            sub_skills=[
                {'name': 'Multithreading', 'category': 'Programming Language', 'confidence': 0.92},
                {'name': 'REST API', 'category': 'API/Web Services', 'confidence': 0.86},
                {'name': 'SQL', 'category': 'Database', 'confidence': 0.65},
            ],
            optional_skills=[{'name': 'SQL', 'category': 'Database', 'confidence': 0.65}],
        )
        payload.update({
            'runtime_sections': [
                {'name': 'Core Java', 'category': 'Programming Language', 'skill_role': 'primary', 'target_questions': 5, 'selection_basis': 'primary skill in title and JD', 'reason': 'Central execution skill.', 'confidence': 0.96},
                {'name': 'Multithreading', 'category': 'Programming Language', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'Java-adjacent JD requirement', 'reason': 'Explicitly required for runtime behavior.', 'confidence': 0.92},
                {'name': 'REST API', 'category': 'API/Web Services', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'Java-adjacent service work', 'reason': 'Explicit API development responsibility.', 'confidence': 0.86},
            ],
            'coding_required': True,
            'coding_primary_skill': 'Core Java',
            'coding_questions_to_ask': 1,
            'excluded_skills': [{'name': 'SQL', 'category': 'Database', 'reason': 'Useful but not central to this Core Java JD.'}],
        })
        self._build_with_mocked_openai(vacancy, payload)
        sql = Skill.objects.get(name='SQL')
        for index in range(4):
            SkillQuestion.objects.create(
                skill=sql,
                question_text=f'SQL ready question {index}',
                question_hash=f'sql-ready-{index}',
                family_key=f'sql_family_{index}',
                coverage_area=f'sql_area_{index}',
                quality_status=SkillQuestion.QualityStatus.APPROVED,
                is_active=True,
            )
        candidate = User.objects.create_user(username='java-runtime-candidate', password='pass1234', email='java-runtime@example.com')
        UserProfile.objects.create(user=candidate, role='candidate', phone='919999999992', gender='other', hr=self.admin)
        interview = Interview.objects.create(candidate=candidate, recruiter=self.recruiter, hr=self.admin, role=vacancy, status='scheduled')

        result = process_missing_question_bank_for_interview(interview.id, apply=False)

        self.assertEqual(result['selected_sub_skills'], ['Multithreading', 'REST API'])
        self.assertNotIn('SQL', result['selected_sub_skills'])
        self.assertTrue(any(gap['skill_name'] == 'Multithreading' for gap in result['planned_gaps']))

    def test_python_fullstack_developer_promotes_python_primary(self):
        vacancy = self._vacancy(
            role='Python Fullstack Developer',
            description='Build Python APIs with React frontends and clear stakeholder communication.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Python Fullstack Developer',
            primary='Communication Skills',
            sub_skills=[
                {'name': 'Python', 'category': 'Programming Language', 'confidence': 0.95},
                {'name': 'React', 'category': 'Frontend Framework', 'confidence': 0.9},
            ],
        )

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'Python')
        primary_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill_role=JobInterviewSkill.SkillRole.PRIMARY)
        self.assertEqual(primary_plan.skill.name, 'Python')

    def test_framework_developer_roles_promote_named_framework_primary(self):
        scenarios = [
            ('React Developer', 'Build React UI components and consume REST APIs.', 'React', 'Frontend Framework'),
            ('Node.js Backend Developer', 'Build Node.js services with Express and PostgreSQL.', 'Node.js', 'Backend Framework'),
        ]
        for role, description, expected_primary, category in scenarios:
            vacancy = self._vacancy(role=role, description=description, experience_required='3-5 years')
            payload = self._mock_payload(
                role_title=role,
                primary='Communication Skills',
                sub_skills=[
                    {'name': expected_primary, 'category': category, 'confidence': 0.95},
                    {'name': 'REST API', 'category': 'API/Web Services', 'confidence': 0.8},
                ],
            )

            self._build_with_mocked_openai(vacancy, payload)

            blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
            self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], expected_primary)
            primary_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill_role=JobInterviewSkill.SkillRole.PRIMARY)
            self.assertEqual(primary_plan.skill.name, expected_primary)

    def test_non_technical_hr_recruiter_keeps_non_technical_primary(self):
        vacancy = self._vacancy(
            role='HR Recruiter',
            description='Source candidates, communicate with hiring managers, and coordinate interviews.',
            experience_required='1-3 years',
        )
        payload = self._mock_payload(
            role_title='HR Recruiter',
            primary='Communication Skills',
            sub_skills=[
                {'name': 'Candidate Sourcing', 'category': 'Human Resources', 'confidence': 0.9},
                {'name': 'Talent Acquisition', 'category': 'Human Resources', 'confidence': 0.9},
            ],
        )

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'Communication Skills')
        primary_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill_role=JobInterviewSkill.SkillRole.PRIMARY)
        self.assertEqual(primary_plan.skill.name, 'Communication Skills')

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
        INTERVIEW_SKILL_CODING_TARGET_COUNT=4,
    )
    def test_coding_generation_auto_enqueue_uses_technical_primary_and_target_count(self):
        technical_vacancy = self._vacancy(
            role='Python Fullstack Developer',
            description='Python APIs and React UI. Communication is useful but not the execution skill.',
            experience_required='3-5 years',
        )
        technical_payload = self._mock_payload(
            role_title='Python Fullstack Developer',
            primary='Communication Skills',
            sub_skills=[
                {'name': 'Python', 'category': 'Programming Language', 'confidence': 0.95},
                {'name': 'React', 'category': 'Frontend Framework', 'confidence': 0.9},
            ],
        )

        with self.captureOnCommitCallbacks(execute=True):
            self._build_with_mocked_openai(technical_vacancy, technical_payload)

        technical_blueprint = JobInterviewBlueprint.objects.get(job=technical_vacancy)
        python_plan = JobInterviewSkill.objects.get(blueprint=technical_blueprint, skill__name='Python')
        self.assertEqual(python_plan.skill_role, JobInterviewSkill.SkillRole.PRIMARY)
        coding_jobs = QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.CODING_GENERATION)
        self.assertEqual(coding_jobs.count(), 1)
        self.assertEqual(coding_jobs.get().skill.name, 'Python')

        hr_vacancy = self._vacancy(
            role='HR Recruiter',
            description='Communication, sourcing, screening and interview coordination.',
            experience_required='1-3 years',
        )
        hr_payload = self._mock_payload(
            role_title='HR Recruiter',
            primary='Communication Skills',
            sub_skills=[{'name': 'Candidate Sourcing', 'category': 'Human Resources', 'confidence': 0.9}],
        )

        with self.captureOnCommitCallbacks(execute=True):
            self._build_with_mocked_openai(hr_vacancy, hr_payload)

        hr_blueprint = JobInterviewBlueprint.objects.get(job=hr_vacancy)
        self.assertFalse(hr_blueprint.blueprint_plan['coding_required'])
        self.assertEqual(hr_blueprint.blueprint_plan['coding_skill_targets'], [])
        self.assertEqual(QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.CODING_GENERATION).count(), 1)

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
        INTERVIEW_SKILL_CODING_TARGET_COUNT=4,
    )
    def test_hr_recruiter_false_coding_removes_stale_targets_and_does_not_enqueue(self):
        vacancy = self._vacancy(
            role='HR Recruiter',
            description='Source candidates, screen resumes, communicate with hiring managers, and coordinate interviews.',
            experience_required='1-3 years',
        )
        payload = self._mock_payload(
            role_title='HR Recruiter',
            primary='Communication Skills',
            sub_skills=[
                {'name': 'Candidate Sourcing', 'category': 'Human Resources', 'confidence': 0.9},
                {'name': 'Talent Acquisition', 'category': 'Human Resources', 'confidence': 0.9},
            ],
        )
        payload.update({
            'role_family': 'non_technical',
            'technical_interview': False,
            'coding_required': False,
            'coding_skill_targets': ['Communication Skills', 'Problem-solving'],
            'coding_questions_to_ask': 3,
        })

        with self.captureOnCommitCallbacks(execute=True):
            self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertFalse(blueprint.blueprint_plan['coding_required'])
        self.assertEqual(blueprint.blueprint_plan['coding_skill_targets'], [])
        self.assertTrue(any(item['code'] == 'non_technical_coding_removed' for item in blueprint.blueprint_plan['quality_warnings']))
        self.assertFalse(QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.CODING_GENERATION).exists())

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=False,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
        INTERVIEW_SKILL_CODING_TARGET_COUNT=4,
    )
    def test_data_architect_repairs_kubernetes_primary_and_coding_targets_to_data_skills(self):
        vacancy = self._vacancy(
            role='Data Engineer / Data Architect',
            description=(
                'Design data architecture for large-scale data systems. Build data pipelines, data modeling, '
                'data warehousing, ETL processes, data quality checks, and validation for analytics platforms.'
            ),
            experience_required='5-8 years',
        )
        payload = self._mock_payload(
            role_title='Data Engineer / Data Architect',
            primary='Kubernetes',
            sub_skills=[
                {'name': 'Communication Skills', 'category': 'Soft Skills', 'confidence': 0.8},
                {'name': 'Kubernetes', 'category': 'DevOps Tool', 'confidence': 0.9},
                {'name': 'Problem-solving', 'category': 'Soft Skills', 'confidence': 0.7},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Communication Skills', 'Kubernetes', 'Problem-solving'],
            'coding_questions_to_ask': 3,
            'runtime_sections': [
                {'name': 'Kubernetes', 'category': 'DevOps Tool', 'skill_role': 'primary', 'target_questions': 5, 'selection_basis': 'model output', 'reason': 'Incorrect primary.', 'confidence': 0.9},
            ],
        })

        with self.captureOnCommitCallbacks(execute=True):
            self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertIn(blueprint.blueprint_plan['primary_skill']['name'], {'Data Engineering', 'Data Architecture'})
        targets = set(blueprint.blueprint_plan['coding_skill_targets'])
        self.assertTrue({'SQL', 'ETL / ELT', 'Data Pipelines', 'Data Warehousing', 'Data Modeling', 'Data Quality / Validation'}.issubset(targets))
        self.assertFalse({'Communication Skills', 'Problem-solving', 'Kubernetes'} & targets)
        self.assertTrue(blueprint.blueprint_plan['coding_required'])
        warning_codes = {item['code'] for item in blueprint.blueprint_plan['quality_warnings']}
        self.assertTrue({'unsupported_primary_skill', 'repaired_primary_skill', 'rejected_coding_targets', 'repaired_coding_targets', 'infrastructure_without_jd_evidence'}.issubset(warning_codes))
        self.assertFalse(JobInterviewSkill.objects.filter(blueprint=blueprint, skill__name='Kubernetes', coding_questions_to_ask__gt=0).exists())
        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        audit_output = out.getvalue()
        self.assertIn('unsupported_primary_skill', audit_output)
        self.assertIn('repaired_primary_skill', audit_output)
        self.assertIn('rejected_coding_targets', audit_output)
        self.assertIn('repaired_coding_targets', audit_output)
        self.assertIn('infrastructure_without_jd_evidence', audit_output)

    def test_kubernetes_is_allowed_when_jd_explicitly_mentions_container_orchestration(self):
        vacancy = self._vacancy(
            role='Platform Engineer',
            description='Build Kubernetes operators, manage k8s clusters, Docker images, and CI/CD deployment automation.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Platform Engineer',
            primary='Kubernetes',
            sub_skills=[
                {'name': 'Docker', 'category': 'DevOps Tool', 'confidence': 0.9},
                {'name': 'CI/CD', 'category': 'DevOps Tool', 'confidence': 0.9},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Kubernetes'],
            'coding_questions_to_ask': 3,
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'Kubernetes')
        self.assertEqual(blueprint.blueprint_plan['coding_skill_targets'], ['Kubernetes'])

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_AUTO_ENQUEUE_ON_BLUEPRINT=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_BLUEPRINT_OPENAI_ENABLED=True,
        OPENAI_API_KEY='test-key',
        INTERVIEW_BLUEPRINT_CREATE_MISSING_SKILLS=False,
    )
    def test_tosca_timeout_fallback_does_not_select_unrelated_kubernetes(self):
        Skill.objects.create(name='Kubernetes', key='kubernetes', category='Cloud Platform')
        vacancy = self._vacancy(
            role='Tosca Automation Testing / Tosca Automation Engineer',
            description=(
                'Required Technical Skill Set:\n'
                '* Tosca Automation\n'
                '* Rally\n'
                '* HP ALM/QC\n'
                '* Selenium WebDriver\n'
                '* Cucumber/Gherkin\n'
            ),
            experience_required='3-5 years',
        )

        with patch('smartInterviewApp.services.interview_blueprints.extract_skills_with_openai', side_effect=TimeoutError('The read operation timed out')):
            with self.captureOnCommitCallbacks(execute=True):
                result = build_job_interview_blueprint(vacancy.id)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertFalse(result['ok'])
        self.assertEqual(blueprint.status, JobInterviewBlueprint.Status.FAILED)
        self.assertFalse(blueprint.minimum_ready)
        self.assertEqual(blueprint.blueprint_plan['runtime_sections'], [])
        self.assertFalse(JobInterviewSkill.objects.filter(blueprint=blueprint, is_active=True).exists())
        self.assertFalse(JobInterviewSkill.objects.filter(blueprint=blueprint, skill__name='Kubernetes').exists())
        self.assertFalse(QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).exists())

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=False)
    def test_tosca_openai_success_canonicalizes_descriptive_qa_skills(self):
        Skill.objects.create(name='Tosca Automation', key='tosca-automation', category='QA Automation', aliases=['Tricentis Tosca', 'Tosca'])
        Skill.objects.create(name='HP ALM/QC', key='hp-almqc', category='Test Management', aliases=['HP ALM', 'Quality Center'])
        Skill.objects.create(name='Rally', key='rally', category='Agile Tool', aliases=['CA Agile Central'])
        Skill.objects.create(name='Cucumber/Gherkin', key='cucumber-gherkin', category='BDD Testing', aliases=['BDD'])
        Skill.objects.create(name='Selenium WebDriver', key='selenium-webdriver', category='Test Automation', aliases=['Selenium'])
        vacancy = self._vacancy(
            role='Tosca Automation Testing / Tosca Automation Engineer',
            description='Required Technical Skill Set: Tosca Automation, Rally, HP ALM/QC, Selenium WebDriver, Cucumber/Gherkin.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Tosca Automation',
            sub_skills=[
                {'name': 'Test Management with HP ALM/QC', 'category': 'Test Management', 'confidence': 0.93},
                {'name': 'Agile Project Management with Rally', 'category': 'Agile Tool', 'confidence': 0.9},
                {'name': 'Behavior Driven Development with Cucumber/Gherkin', 'category': 'BDD Testing', 'confidence': 0.9},
                {'name': 'Selenium WebDriver', 'category': 'Test Automation', 'confidence': 0.88},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': False,
            'coding_skill_targets': [],
            'coding_questions_to_ask': 0,
            'runtime_sections': [
                {'name': 'Tosca Automation', 'category': 'QA Automation', 'skill_role': 'primary', 'target_questions': 5, 'selection_basis': 'title and JD', 'reason': 'Primary tool.', 'confidence': 0.95},
                {'name': 'Test Management with HP ALM/QC', 'category': 'Test Management', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'required skill', 'reason': 'Required tool.', 'confidence': 0.93},
                {'name': 'Agile Project Management with Rally', 'category': 'Agile Tool', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'required skill', 'reason': 'Required tool.', 'confidence': 0.9},
                {'name': 'Behavior Driven Development with Cucumber/Gherkin', 'category': 'BDD Testing', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'required skill', 'reason': 'Required BDD syntax.', 'confidence': 0.9},
            ],
        })

        result = self._build_with_mocked_openai(vacancy, payload)

        self.assertTrue(result['ok'])
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.status, JobInterviewBlueprint.Status.READY)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'Tosca Automation')
        runtime_sections = blueprint.blueprint_plan['runtime_sections']
        runtime_names = [section['name'] for section in runtime_sections]
        self.assertEqual(runtime_names[0], 'Tosca Automation')
        self.assertEqual(runtime_names[1], 'HP ALM/QC')
        self.assertEqual(runtime_names[2], 'Cucumber/Gherkin')
        self.assertTrue({'Selenium WebDriver', 'Rally'} & set(runtime_names[1:]))
        self.assertEqual(len(runtime_sections), 4)
        self.assertEqual(sum(1 for section in runtime_sections if section['skill_role'] == JobInterviewSkill.SkillRole.PRIMARY), 1)
        self.assertEqual(sum(1 for section in runtime_sections if section['skill_role'] == JobInterviewSkill.SkillRole.SUB_SKILL), 3)
        for section in runtime_sections:
            if section['skill_role'] == JobInterviewSkill.SkillRole.PRIMARY:
                self.assertGreaterEqual(section['questions_to_ask'], 5)
            else:
                self.assertGreaterEqual(section['questions_to_ask'], 3)
            self.assertEqual(section['coding_questions_to_ask'], 0)
        runtime_roles = {
            plan.skill.name: plan.skill_role
            for plan in JobInterviewSkill.objects.select_related('skill').filter(blueprint=blueprint, skill__name__in=runtime_names)
        }
        self.assertEqual(runtime_roles['Tosca Automation'], JobInterviewSkill.SkillRole.PRIMARY)
        self.assertEqual(runtime_roles['HP ALM/QC'], JobInterviewSkill.SkillRole.SUB_SKILL)
        self.assertEqual(runtime_roles['Cucumber/Gherkin'], JobInterviewSkill.SkillRole.SUB_SKILL)
        self.assertEqual(
            {item['name'] for item in blueprint.selected_skills_snapshot if item['skill_role'] in {JobInterviewSkill.SkillRole.PRIMARY, JobInterviewSkill.SkillRole.SUB_SKILL}},
            set(runtime_names),
        )
        names = self._skill_names_for_blueprint(blueprint)
        self.assertTrue({'Tosca Automation', 'HP ALM/QC', 'Rally', 'Cucumber/Gherkin', 'Selenium WebDriver'}.issubset(names))
        self.assertFalse(Skill.objects.filter(name='Test Management with HP ALM/QC').exists())
        self.assertFalse(Skill.objects.filter(name='Agile Project Management with Rally').exists())
        self.assertFalse(Skill.objects.filter(name='Behavior Driven Development with Cucumber/Gherkin').exists())

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_AUTO_ENQUEUE_ON_BLUEPRINT=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
    )
    def test_tosca_question_generation_queues_runtime_skills_only(self):
        Skill.objects.create(name='Tosca Automation', key='tosca-automation', category='QA Automation', aliases=['Tricentis Tosca', 'Tosca'])
        Skill.objects.create(name='HP ALM/QC', key='hp-almqc', category='Test Management', aliases=['HP ALM', 'Quality Center'])
        Skill.objects.create(name='Rally', key='rally', category='Agile Tool', aliases=['CA Agile Central'])
        Skill.objects.create(name='Cucumber/Gherkin', key='cucumber-gherkin', category='BDD Testing', aliases=['BDD'])
        Skill.objects.create(name='Selenium WebDriver', key='selenium-webdriver', category='Test Automation', aliases=['Selenium'])
        vacancy = self._vacancy(
            role='Tosca Automation Testing / Tosca Automation Engineer',
            description='Required Technical Skill Set: Tosca Automation, Rally, HP ALM/QC, Selenium WebDriver, Cucumber/Gherkin.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Tosca Automation',
            sub_skills=[
                {'name': 'Test Management with HP ALM/QC', 'category': 'Test Management', 'confidence': 0.93},
                {'name': 'Agile Project Management with Rally', 'category': 'Agile Tool', 'confidence': 0.9},
                {'name': 'Behavior Driven Development with Cucumber/Gherkin', 'category': 'BDD Testing', 'confidence': 0.9},
                {'name': 'Selenium WebDriver', 'category': 'Test Automation', 'confidence': 0.88},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': False,
            'coding_skill_targets': [],
            'coding_questions_to_ask': 0,
            'runtime_sections': [
                {'name': 'Tosca Automation', 'category': 'QA Automation', 'skill_role': 'primary', 'target_questions': 5, 'selection_basis': 'title and JD', 'reason': 'Primary tool.', 'confidence': 0.95},
                {'name': 'Test Management with HP ALM/QC', 'category': 'Test Management', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'required skill', 'reason': 'Required tool.', 'confidence': 0.93},
                {'name': 'Agile Project Management with Rally', 'category': 'Agile Tool', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'required skill', 'reason': 'Required tool.', 'confidence': 0.9},
                {'name': 'Behavior Driven Development with Cucumber/Gherkin', 'category': 'BDD Testing', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'required skill', 'reason': 'Required BDD syntax.', 'confidence': 0.9},
            ],
        })

        with self.captureOnCommitCallbacks(execute=True):
            self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        runtime_names = {section['name'] for section in blueprint.blueprint_plan['runtime_sections']}
        self.assertEqual(len(runtime_names), 4)
        queued_names = set(QuestionGenerationJob.objects.filter(
            task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION,
        ).values_list('skill__name', flat=True))
        self.assertEqual(queued_names, runtime_names)
        self.assertFalse(QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.CODING_GENERATION).exists())

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_AUTO_ENQUEUE_ON_BLUEPRINT=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
    )
    def test_unsupported_kubernetes_primary_fails_and_skips_question_generation(self):
        Skill.objects.create(name='Kubernetes', key='kubernetes', category='Cloud Platform')
        vacancy = self._vacancy(
            role='QA Automation Engineer',
            description='Required skills: Tosca Automation, Selenium WebDriver, HP ALM/QC, Rally.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Kubernetes',
            sub_skills=[{'name': 'Kubernetes', 'category': 'Cloud Platform', 'confidence': 0.95}],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Kubernetes'],
            'coding_questions_to_ask': 3,
            'runtime_sections': [
                {'name': 'Kubernetes', 'category': 'Cloud Platform', 'skill_role': 'primary', 'target_questions': 5, 'selection_basis': 'model output', 'reason': 'Incorrect primary.', 'confidence': 0.95},
            ],
        })

        with self.captureOnCommitCallbacks(execute=True):
            result = self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertFalse(result['ok'])
        self.assertEqual(blueprint.status, JobInterviewBlueprint.Status.FAILED)
        self.assertFalse(blueprint.minimum_ready)
        self.assertIn('unsupported_primary_skill', blueprint.blueprint_plan['fatal_quality_issues'])
        self.assertFalse(QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.QUESTION_GENERATION).exists())

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=False)
    def test_tool_only_qa_jd_disables_coding_without_programming_evidence(self):
        Skill.objects.create(name='Tosca Automation', key='tosca-automation', category='QA Automation')
        vacancy = self._vacancy(
            role='Tosca Automation Engineer',
            description='Required Technical Skill Set: Tosca Automation, HP ALM/QC, Rally, Cucumber/Gherkin.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(role_title=vacancy.role, primary='Tosca Automation', sub_skills=[])
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Tosca Automation'],
            'coding_questions_to_ask': 3,
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        primary_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill__name='Tosca Automation')
        self.assertFalse(blueprint.blueprint_plan['coding_required'])
        self.assertEqual(blueprint.blueprint_plan['coding_questions_to_ask'], 0)
        self.assertEqual(primary_plan.coding_questions_to_ask, 0)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=False)
    def test_selenium_framework_jd_allows_coding_with_explicit_programming_evidence(self):
        Skill.objects.create(name='Selenium WebDriver', key='selenium-webdriver', category='Test Automation')
        Skill.objects.create(name='Java', key='java', category='Programming Language')
        vacancy = self._vacancy(
            role='QA Automation Engineer',
            description='Build a custom Selenium WebDriver automation framework using Java code and scripting for API automation implementation.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Selenium WebDriver',
            sub_skills=[{'name': 'Java', 'category': 'Programming Language', 'confidence': 0.95}],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Selenium WebDriver', 'Java'],
            'coding_questions_to_ask': 3,
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertTrue(blueprint.blueprint_plan['coding_required'])
        self.assertEqual(blueprint.blueprint_plan['coding_questions_to_ask'], 3)
        selenium_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill__name='Selenium WebDriver')
        self.assertEqual(selenium_plan.coding_questions_to_ask, 3)

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=False)
    def test_generic_missing_skill_creation_requires_clean_skill_evidence(self):
        vacancy = self._vacancy(
            role='QA Test Lead',
            description='Use Zephyr Scale for test case management. Full time remote role at Acme Corp. B.Tech preferred.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Zephyr Scale',
            sub_skills=[
                {'name': 'Full time', 'category': 'Employment Type', 'confidence': 0.95},
                {'name': 'Remote', 'category': 'Location', 'confidence': 0.95},
                {'name': 'Acme Corp', 'category': 'Company', 'confidence': 0.95},
                {'name': 'B.Tech', 'category': 'Education', 'confidence': 0.95},
            ],
        )

        self._build_with_mocked_openai(vacancy, payload)

        self.assertTrue(Skill.objects.filter(name='Zephyr Scale', key='zephyr-scale').exists())
        for key in ['full-time', 'remote', 'acme-corp', 'b-tech']:
            self.assertFalse(Skill.objects.filter(key=key).exists())

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=False)
    def test_marketing_jd_selects_marketing_skills_without_coding_or_tech_false_positives(self):
        vacancy = self._vacancy(
            role='Digital Marketing Executive',
            description='Skills: SEO, Social Media Marketing, Campaign Management, Lead Generation, Google Analytics.',
            experience_required='1-3 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Digital Marketing',
            sub_skills=[
                {'name': 'SEO', 'category': 'Marketing', 'confidence': 0.95},
                {'name': 'Social Media Marketing', 'category': 'Marketing', 'confidence': 0.93},
                {'name': 'Campaign Management', 'category': 'Marketing', 'confidence': 0.9},
                {'name': 'Lead Generation', 'category': 'Marketing', 'confidence': 0.9},
                {'name': 'Kubernetes', 'category': 'Cloud Platform', 'confidence': 0.9},
            ],
        )
        payload.update({
            'role_family': 'non_technical',
            'technical_interview': False,
            'coding_required': False,
            'coding_skill_targets': [],
            'coding_questions_to_ask': 0,
        })

        result = self._build_with_mocked_openai(vacancy, payload)

        self.assertTrue(result['ok'])
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        names = self._skill_names_for_blueprint(blueprint)
        self.assertTrue({'SEO', 'Social Media Marketing', 'Campaign Management', 'Lead Generation'}.issubset(names))
        self.assertFalse(blueprint.blueprint_plan['coding_required'])
        self.assertFalse(JobInterviewSkill.objects.filter(blueprint=blueprint, skill__name='Kubernetes').exists())

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=False)
    def test_noisy_jd_fails_safely_without_company_location_education_skills(self):
        vacancy = self._vacancy(
            role='Operations Role',
            description='Acme Corp is hiring full time candidates in Bengaluru. B.Tech preferred. Remote or hybrid location.',
            experience_required='0-3 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Acme Corp',
            sub_skills=[
                {'name': 'Bengaluru', 'category': 'Location', 'confidence': 0.95},
                {'name': 'Full time', 'category': 'Employment Type', 'confidence': 0.95},
                {'name': 'B.Tech', 'category': 'Education', 'confidence': 0.95},
            ],
        )

        result = self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertFalse(result['ok'])
        self.assertEqual(blueprint.status, JobInterviewBlueprint.Status.FAILED)
        self.assertFalse(blueprint.minimum_ready)
        for key in ['acme-corp', 'bengaluru', 'full-time', 'b-tech']:
            self.assertFalse(Skill.objects.filter(key=key).exists())

    @override_settings(INTERVIEW_QUESTION_BANK_ENABLED=False)
    def test_support_jd_selects_only_explicit_support_skills_without_coding(self):
        vacancy = self._vacancy(
            role='Customer Support Specialist',
            description='Requirements: Customer Support, Ticket Management, SLA Management, Email Communication, CRM tools.',
            experience_required='1-3 years',
        )
        payload = self._mock_payload(
            role_title=vacancy.role,
            primary='Customer Support',
            sub_skills=[
                {'name': 'Ticket Management', 'category': 'Customer Support', 'confidence': 0.93},
                {'name': 'SLA Management', 'category': 'Customer Support', 'confidence': 0.9},
                {'name': 'Email Communication', 'category': 'Customer Support', 'confidence': 0.88},
                {'name': 'Python', 'category': 'Programming Language', 'confidence': 0.9},
            ],
        )
        payload.update({
            'role_family': 'non_technical',
            'technical_interview': False,
            'coding_required': False,
            'coding_skill_targets': ['Python'],
            'coding_questions_to_ask': 3,
        })

        result = self._build_with_mocked_openai(vacancy, payload)

        self.assertTrue(result['ok'])
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        names = self._skill_names_for_blueprint(blueprint)
        self.assertTrue({'Customer Support', 'Ticket Management', 'SLA Management', 'Email Communication'}.issubset(names))
        self.assertFalse(blueprint.blueprint_plan['coding_required'])
        self.assertFalse(JobInterviewSkill.objects.filter(blueprint=blueprint, skill__name='Python').exists())

    def test_core_java_developer_keeps_core_java_and_sql_coding_targets(self):
        vacancy = self._vacancy(
            role='Core Java Developer',
            description='Develop Core Java services using collections, multithreading, REST APIs, and SQL queries.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Core Java Developer',
            primary='Core Java',
            sub_skills=[
                {'name': 'SQL', 'category': 'Database Query Language', 'confidence': 0.9},
                {'name': 'REST API', 'category': 'API/Web Services', 'confidence': 0.85},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Core Java', 'SQL'],
            'coding_questions_to_ask': 3,
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'Core Java')
        self.assertEqual(blueprint.blueprint_plan['coding_skill_targets'], ['Core Java', 'SQL'])

    def test_core_java_concurrency_and_collections_targets_are_active_coding_targets(self):
        vacancy = self._vacancy(
            role='Core Java Developer',
            description=(
                'Develop Core Java services using the collections framework, multithreading, '
                'Java concurrency utilities, and SQL queries.'
            ),
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Core Java Developer',
            primary='Core Java',
            sub_skills=[
                {'name': 'Multithreading and Concurrency', 'category': 'Java Concept', 'confidence': 0.92},
                {'name': 'Collections Framework', 'category': 'Java Framework', 'confidence': 0.9},
                {'name': 'Java Concurrency and Collections', 'category': 'Java API', 'confidence': 0.9},
                {'name': 'SQL', 'category': 'Database Query Language', 'confidence': 0.86},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': [
                'Core Java',
                'Multithreading and Concurrency',
                'Collections Framework',
                'Java Concurrency and Collections',
                'SQL',
            ],
            'coding_questions_to_ask': 3,
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(
            blueprint.blueprint_plan['coding_skill_targets'],
            [
                'Core Java',
                'Multithreading and Concurrency',
                'Collections Framework',
                'Java Concurrency and Collections',
                'SQL',
            ],
        )
        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        output = out.getvalue()
        self.assertIn('Coding skill targets: Core Java, Multithreading and Concurrency, Collections Framework, Java Concurrency and Collections, SQL', output)
        self.assertIn('- Multithreading and Concurrency: active_coding_count=0', output)
        self.assertIn('- Collections Framework: active_coding_count=0', output)
        self.assertIn('- Java Concurrency and Collections: active_coding_count=0', output)

    def test_unresolved_non_coding_target_is_rejected_during_blueprint_repair(self):
        vacancy = self._vacancy(
            role='Core Java Developer',
            description='Develop Core Java services with collections and SQL queries. Agile delivery is a process practice.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Core Java Developer',
            primary='Core Java',
            sub_skills=[
                {'name': 'SQL', 'category': 'Database Query Language', 'confidence': 0.9},
                {'name': 'Agile', 'category': 'Process', 'confidence': 0.75},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Core Java', 'Agile'],
            'coding_questions_to_ask': 3,
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['coding_skill_targets'], ['Core Java'])
        warning_codes = {item['code'] for item in blueprint.blueprint_plan['quality_warnings']}
        self.assertIn('rejected_coding_targets', warning_codes)
        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        output = out.getvalue()
        self.assertIn('Coding skill targets: Core Java', output)
        self.assertNotIn('Coding skill targets: Core Java, Agile', output)
        self.assertIn('rejected_coding_targets', output)

    def test_salesforce_developer_keeps_salesforce_coding_targets(self):
        vacancy = self._vacancy(
            role='Salesforce Developer',
            description='Build Salesforce customizations with Apex, LWC, SOQL, and Salesforce integration APIs.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Salesforce Developer',
            primary='Salesforce',
            sub_skills=[
                {'name': 'Apex', 'category': 'Salesforce Development', 'confidence': 0.95},
                {'name': 'LWC', 'category': 'Salesforce Development', 'confidence': 0.9},
                {'name': 'Salesforce Integration', 'category': 'Salesforce Development', 'confidence': 0.88},
            ],
        )
        payload.update({
            'role_family': 'technical',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['Apex', 'LWC', 'Salesforce Integration'],
            'coding_questions_to_ask': 3,
        })

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'Salesforce')
        self.assertEqual(blueprint.blueprint_plan['coding_skill_targets'], ['Apex', 'LWC', 'Salesforce Integration'])

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
        INTERVIEW_SKILL_CODING_TARGET_COUNT=0,
    )
    def test_coding_generation_uses_blueprint_coding_skill_targets_not_only_primary(self):
        vacancy = self._vacancy(
            role='Data Analyst',
            description='Analyze data with SQL and build stakeholder reports.',
            experience_required='3-5 years',
        )
        payload = self._mock_payload(
            role_title='Data Analyst',
            primary='Data Analysis',
            sub_skills=[
                {'name': 'SQL', 'category': 'Database Query Language', 'confidence': 0.95},
                {'name': 'Stakeholder Management', 'category': 'Business', 'confidence': 0.8},
            ],
        )
        payload.update({
            'role_family': 'hybrid',
            'technical_interview': True,
            'coding_required': True,
            'coding_skill_targets': ['SQL'],
            'coding_questions_to_ask': 3,
            'runtime_sections': [
                {'name': 'Data Analysis', 'category': 'Analytics', 'skill_role': 'primary', 'target_questions': 5, 'selection_basis': 'primary JD responsibility', 'reason': 'Core interview skill.', 'confidence': 0.9},
                {'name': 'SQL', 'category': 'Database Query Language', 'skill_role': 'sub_skill', 'target_questions': 3, 'selection_basis': 'hands-on querying requirement', 'reason': 'Best coding target.', 'confidence': 0.95},
            ],
        })

        with self.captureOnCommitCallbacks(execute=True):
            self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertTrue(blueprint.blueprint_plan['coding_required'])
        self.assertEqual(blueprint.blueprint_plan['coding_questions_to_ask'], 3)
        self.assertEqual(blueprint.blueprint_plan['coding_skill_targets'], ['SQL'])
        sql_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill__name='SQL')
        self.assertEqual(sql_plan.skill_role, JobInterviewSkill.SkillRole.SUB_SKILL)
        self.assertEqual(sql_plan.coding_questions_to_ask, 3)
        coding_jobs = QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.CODING_GENERATION)
        self.assertEqual(coding_jobs.count(), 1)
        self.assertEqual(coding_jobs.get().skill.name, 'SQL')

    def test_audit_question_bank_reports_missing_coding_and_jobs(self):
        skill = Skill.objects.create(name='SQL', key='sql', category='Database Query Language')
        vacancy = self._vacancy(role='Data Analyst', description='SQL analysis role.', experience_required='3-5 years')
        blueprint = JobInterviewBlueprint.objects.create(
            job=vacancy,
            status=JobInterviewBlueprint.Status.READY,
            role_title=vacancy.role,
            experience_level='Mid-level (3-5 years)',
            blueprint_plan=ensure_blueprint_plan_signature({
                'role_family': 'hybrid',
                'technical_interview': True,
                'coding_required': True,
                'coding_skill_targets': ['SQL'],
                'coding_questions_to_ask': 3,
                'primary_skill': {'skill_id': skill.id, 'skill_key': skill.key, 'name': skill.name},
                'sub_skills': [],
                'optional_skills': [],
                'runtime_sections': [{'skill_id': skill.id, 'skill_key': skill.key, 'name': skill.name, 'skill': skill.name, 'skill_role': 'primary', 'role': 'primary', 'target_questions': 5, 'questions_to_ask': 5}],
                'interview_sections': [{'skill_id': skill.id, 'skill_key': skill.key, 'name': skill.name, 'skill': skill.name, 'skill_role': 'primary', 'role': 'primary', 'target_questions': 5, 'questions_to_ask': 5}],
            }),
            minimum_ready=True,
            fully_ready=True,
        )
        JobInterviewSkill.objects.create(
            blueprint=blueprint,
            job=vacancy,
            skill=skill,
            skill_role=JobInterviewSkill.SkillRole.PRIMARY,
            priority=1,
            questions_to_ask=5,
            coding_questions_to_ask=3,
            is_active=True,
        )
        QuestionGenerationJob.objects.create(
            job=vacancy,
            blueprint=blueprint,
            skill=skill,
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.FAILED,
            error_message='provider failed',
            payload={'blueprint_id': blueprint.id, 'plan_signature': blueprint.blueprint_plan['plan_signature'], 'target_skill_id': skill.id, 'target_skill_name': skill.name, 'target_role': 'coding_target'},
        )
        candidate = User.objects.create_user(username='audit-candidate', password='pass1234', email='audit@example.com')
        UserProfile.objects.create(user=candidate, role='candidate', phone='919999999993', gender='other', hr=self.admin)
        interview = Interview.objects.create(candidate=candidate, recruiter=self.recruiter, hr=self.admin, role=vacancy, status='scheduled')

        out = StringIO()
        call_command('audit_question_bank', '--interview-id', str(interview.id), stdout=out)
        output = out.getvalue()

        self.assertIn('Coding required: True', output)
        self.assertIn('Coding skill targets: SQL', output)
        self.assertIn('coding_questions_missing', output)
        self.assertIn('coding_generation_failed', output)
        self.assertIn('coding_generation:failed', output)

    def test_repaired_blueprint_audit_uses_current_coding_targets_and_marks_old_jobs_stale(self):
        blueprint, _, skills = self._coding_audit_blueprint(
            targets=['Core Java'],
            primary='Core Java',
            sub_skills=['Agile', 'Communication Skills'],
        )
        QuestionGenerationJob.objects.create(
            job=blueprint.job,
            blueprint=blueprint,
            skill=skills['Agile'],
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.FAILED,
            payload={'blueprint_id': blueprint.id, 'plan_signature': 'old-plan', 'target_skill_id': skills['Agile'].id, 'target_skill_name': 'Agile', 'target_role': 'coding_target'},
        )
        QuestionGenerationJob.objects.create(
            job=blueprint.job,
            blueprint=blueprint,
            skill=skills['Communication Skills'],
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
        )

        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        output = out.getvalue()

        self.assertIn('Coding skill targets: Core Java', output)
        self.assertIn('- Core Java: active_coding_count=0', output)
        self.assertIn('Stale coding jobs/questions ignored:', output)

    def test_coding_required_false_audit_has_no_active_targets_with_old_coding_jobs(self):
        blueprint, _, skills = self._coding_audit_blueprint(
            role='HR Recruiter',
            coding_required=False,
            targets=[],
            primary='Candidate Screening',
            sub_skills=['Communication Skills'],
        )
        sql = Skill.objects.create(name='SQL', key='sql', category='Database Query Language')
        QuestionGenerationJob.objects.create(
            job=blueprint.job,
            blueprint=blueprint,
            skill=sql,
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.SUCCESS,
        )
        self.assertIn('Candidate Screening', skills)

        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        output = out.getvalue()

        self.assertIn('Coding required: False', output)
        self.assertIn('Coding skill targets: \n', output)
        self.assertNotIn('Coding targets:', output)
        self.assertIn('Stale coding jobs/questions ignored:', output)

    def test_readiness_ignores_stale_coding_jobs_for_non_current_targets(self):
        blueprint, _, skills = self._coding_audit_blueprint(
            targets=['Core Java'],
            primary='Core Java',
            sub_skills=['Agile'],
        )
        for index in range(3):
            self._coding_question(skills['Core Java'], index)
        QuestionGenerationJob.objects.create(
            job=blueprint.job,
            blueprint=blueprint,
            skill=skills['Agile'],
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.FAILED,
            payload={'blueprint_id': blueprint.id, 'plan_signature': 'old-plan', 'target_skill_id': skills['Agile'].id, 'target_skill_name': 'Agile', 'target_role': 'coding_target'},
        )
        plans = list(JobInterviewSkill.objects.select_related('skill').filter(blueprint=blueprint))

        readiness = _coding_readiness_for_blueprint(blueprint, plans)

        self.assertEqual([item['skill_name'] for item in readiness['target_skills']], ['Core Java'])
        self.assertNotIn('coding_generation_failed', readiness['reasons'])
        self.assertEqual(readiness['failed_job_count'], 0)

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=1,
        INTERVIEW_SKILL_CODING_TARGET_COUNT=4,
    )
    def test_generation_enqueues_only_current_coding_targets_after_repair(self):
        blueprint, _, skills = self._coding_audit_blueprint(
            targets=['Core Java'],
            primary='Core Java',
            sub_skills=['Agile'],
        )
        QuestionGenerationJob.objects.create(
            job=blueprint.job,
            blueprint=blueprint,
            skill=skills['Agile'],
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.QUEUED,
        )

        ensure_question_bank_for_blueprint(blueprint.id)

        coding_jobs = QuestionGenerationJob.objects.filter(task_type=QuestionGenerationJob.TaskType.CODING_GENERATION)
        self.assertEqual(coding_jobs.filter(skill=skills['Core Java']).count(), 1)
        self.assertEqual(coding_jobs.filter(skill=skills['Agile']).count(), 1)
        current_job = coding_jobs.get(skill=skills['Core Java'])
        self.assertEqual(current_job.payload['blueprint_id'], blueprint.id)
        self.assertEqual(current_job.payload['plan_signature'], blueprint.blueprint_plan['plan_signature'])
        self.assertEqual(current_job.payload['target_role'], 'coding_target')

    def test_old_coding_job_without_plan_signature_is_not_active(self):
        blueprint, _, skills = self._coding_audit_blueprint(targets=['Core Java'], primary='Core Java')
        for index in range(3):
            self._coding_question(skills['Core Java'], index)
        QuestionGenerationJob.objects.create(
            job=blueprint.job,
            blueprint=blueprint,
            skill=skills['Core Java'],
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.FAILED,
        )
        plans = list(JobInterviewSkill.objects.select_related('skill').filter(blueprint=blueprint))

        readiness = _coding_readiness_for_blueprint(blueprint, plans)

        self.assertNotIn('coding_generation_failed', readiness['reasons'])
        self.assertEqual(readiness['failed_job_count'], 0)

    def test_core_java_rejected_agile_coding_target_is_not_active(self):
        blueprint, _, _ = self._coding_audit_blueprint(
            targets=['Core Java'],
            primary='Core Java',
            sub_skills=['Agile'],
            quality_warnings=[{'code': 'rejected_coding_targets', 'targets': ['Agile']}],
        )

        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        output = out.getvalue()

        self.assertIn('Coding skill targets: Core Java', output)
        self.assertNotIn('Coding skill targets: Core Java, Agile', output)
        self.assertIn('rejected_coding_targets', output)

    def test_hr_recruiter_stale_coding_generation_does_not_show_active_target(self):
        blueprint, _, _ = self._coding_audit_blueprint(
            role='HR Recruiter',
            coding_required=False,
            targets=[],
            primary='Candidate Screening',
            sub_skills=['Interview Coordination'],
        )
        stale_skill = Skill.objects.create(name='Communication Skills', key='communication-skills', category='Soft Skills')
        QuestionGenerationJob.objects.create(
            job=blueprint.job,
            blueprint=blueprint,
            skill=stale_skill,
            task_type=QuestionGenerationJob.TaskType.CODING_GENERATION,
            status=QuestionGenerationJob.Status.FAILED,
        )

        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        output = out.getvalue()

        self.assertIn('Coding required: False', output)
        self.assertIn('Coding skill targets: \n', output)
        self.assertNotIn('Coding targets:', output)
        self.assertIn('Stale coding jobs/questions ignored:', output)

    def test_salesforce_current_coding_targets_include_lwc_and_integration_skills(self):
        vacancy = self._vacancy(role='Salesforce Developer', description='Apex, LWC and Salesforce integration.', experience_required='3-5 years')
        skill_specs = [
            ('Salesforce', 'salesforce', 'CRM Platform', JobInterviewSkill.SkillRole.PRIMARY),
            ('Apex Development', 'apex-development', 'Programming Language', JobInterviewSkill.SkillRole.SUB_SKILL),
            ('Lightning Web Components (LWC)', 'lightning-web-components-lwc', 'Frontend Framework / Salesforce Development', JobInterviewSkill.SkillRole.SUB_SKILL),
            ('Salesforce Integration using Web Services', 'salesforce-integration-using-web-service', '', JobInterviewSkill.SkillRole.SUB_SKILL),
        ]
        skills = [
            Skill.objects.create(name=name, key=key, category=category)
            for name, key, category, _ in skill_specs
        ]
        sections = [
            {
                'skill_id': skill.id,
                'skill_key': skill.key,
                'name': skill.name,
                'skill': skill.name,
                'skill_role': skill_role,
                'role': skill_role,
                'target_questions': 5 if skill_role == JobInterviewSkill.SkillRole.PRIMARY else 3,
                'questions_to_ask': 5 if skill_role == JobInterviewSkill.SkillRole.PRIMARY else 3,
            }
            for skill, (_, _, _, skill_role) in zip(skills, skill_specs)
        ]
        blueprint = JobInterviewBlueprint.objects.create(
            job=vacancy,
            status=JobInterviewBlueprint.Status.READY,
            role_title=vacancy.role,
            experience_level='Mid-level (3-5 years)',
            blueprint_plan=ensure_blueprint_plan_signature({
                'role_family': 'technical',
                'technical_interview': True,
                'coding_required': True,
                'coding_skill_targets': [
                    'Apex Development',
                    'Lightning Web Components (LWC)',
                    'Salesforce Integration using Web Services',
                ],
                'coding_questions_to_ask': 3,
                'primary_skill': sections[0],
                'sub_skills': sections[1:],
                'optional_skills': [],
                'runtime_sections': sections,
                'interview_sections': sections,
            }),
            minimum_ready=True,
            fully_ready=True,
        )
        for index, (skill, section) in enumerate(zip(skills, sections), start=1):
            JobInterviewSkill.objects.create(
                blueprint=blueprint,
                job=vacancy,
                skill=skill,
                skill_role=section['skill_role'],
                priority=index,
                questions_to_ask=section['questions_to_ask'],
                coding_questions_to_ask=3 if skill.name != 'Salesforce' else 0,
                is_active=True,
            )

        out = StringIO()
        call_command('audit_question_bank', '--blueprint-id', str(blueprint.id), stdout=out)
        output = out.getvalue()

        self.assertIn('- Apex Development: active_coding_count=0', output)
        self.assertIn('- Lightning Web Components (LWC): active_coding_count=0', output)
        self.assertIn('- Salesforce Integration using Web Services: active_coding_count=0', output)

    @override_settings(
        INTERVIEW_QUESTION_BANK_ENABLED=True,
        INTERVIEW_QUESTION_BANK_RUNNER_MODE='worker_only',
        INTERVIEW_SKILL_VERBAL_TARGET_COUNT=3,
        INTERVIEW_SKILL_CODING_TARGET_COUNT=4,
    )
    def test_coding_generation_target_does_not_require_runtime_ask_count(self):
        skill = Skill.objects.create(name='Python', key='python', category='Programming Language')
        vacancy = self._vacancy(role='Python Developer', description='Python APIs.', experience_required='3-5 years')
        blueprint = JobInterviewBlueprint.objects.create(
            job=vacancy,
            status=JobInterviewBlueprint.Status.READY,
            role_title=vacancy.role,
            experience_level='Mid-level (3-5 years)',
            blueprint_plan={
                'primary_skill': {
                    'skill_id': skill.id,
                    'skill_key': skill.key,
                    'name': skill.name,
                    'interview_weight': 'normal',
                    'eligible_for_random_sub_skill': True,
                },
                'primary_skill_candidates': [],
                'sub_skills': [],
                'optional_skills': [],
                'coding_required': True,
                'coding_skill_targets': [skill.name],
                'coding_questions_to_ask': 3,
            },
            minimum_ready=True,
            fully_ready=True,
        )
        JobInterviewSkill.objects.create(
            blueprint=blueprint,
            job=vacancy,
            skill=skill,
            skill_role=JobInterviewSkill.SkillRole.PRIMARY,
            priority=1,
            questions_to_ask=5,
            coding_questions_to_ask=0,
            is_active=True,
        )

        results = ensure_question_bank_for_blueprint(blueprint.id)

        coding_result = next(item for item in results if item.get('task_type') == QuestionGenerationJob.TaskType.CODING_GENERATION)
        self.assertEqual(coding_result['coding']['status'], 'queued')
        self.assertEqual(QuestionGenerationJob.objects.filter(skill=skill, task_type=QuestionGenerationJob.TaskType.CODING_GENERATION).count(), 1)

    def test_canonical_mapped_name_is_used_in_snapshots(self):
        sql = Skill.objects.create(name='SQL', key='sql', category='Database', aliases=['Database Query'])
        vacancy = self._vacancy(description='Database Query knowledge is required.')
        payload = self._mock_payload(primary='Database Query', sub_skills=[])

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['name'], 'SQL')
        self.assertEqual(blueprint.blueprint_plan['primary_skill']['original_name'], 'Database Query')
        self.assertEqual(blueprint.selected_skills_snapshot[0]['name'], 'SQL')
        self.assertEqual(JobInterviewSkill.objects.get(blueprint=blueprint, skill=sql).skill_role, JobInterviewSkill.SkillRole.PRIMARY)

    def test_primary_technical_skill_has_coding_question_policy(self):
        vacancy = self._vacancy(description='Python Developer, 0-3 years experience.', experience_required='0-3 years')
        payload = self._mock_payload(primary='Python', sub_skills=[])

        self._build_with_mocked_openai(vacancy, payload)

        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        primary_plan = JobInterviewSkill.objects.get(blueprint=blueprint, skill__name='Python')
        self.assertEqual(blueprint.blueprint_plan['runtime_policy']['coding_questions_per_primary'], 3)
        self.assertEqual(primary_plan.coding_questions_to_ask, 3)
        self.assertEqual(primary_plan.coding_difficulty_mix, {'easy': 1, 'medium': 0, 'hard': 0})

    def test_success_generation_job_does_not_process_again(self):
        vacancy = Vacancies.objects.create(
            role='Python Developer',
            description='Python Django role',
            position='1',
            status='active',
            admin=self.admin,
        )
        blueprint = JobInterviewBlueprint.objects.create(
            job=vacancy,
            status=JobInterviewBlueprint.Status.READY,
            minimum_ready=True,
            fully_ready=True,
        )
        generation_job = QuestionGenerationJob.objects.create(
            job=vacancy,
            blueprint=blueprint,
            task_type=QuestionGenerationJob.TaskType.JD_SKILL_MAPPING,
            status=QuestionGenerationJob.Status.SUCCESS,
        )

        with patch('smartInterviewApp.services.interview_blueprints.build_job_interview_blueprint') as build_mock:
            result = process_job_interview_blueprint_task(generation_job.id)

        self.assertEqual(result, {
            'ok': True,
            'status': 'already_processed',
            'job_id': vacancy.id,
            'generation_job_id': generation_job.id,
            'blueprint_id': blueprint.id,
        })
        build_mock.assert_not_called()

    def test_recent_running_generation_job_does_not_process_again(self):
        vacancy = Vacancies.objects.create(
            role='Python Developer',
            description='Python Django role',
            position='1',
            status='active',
            admin=self.admin,
        )
        generation_job = QuestionGenerationJob.objects.create(
            job=vacancy,
            task_type=QuestionGenerationJob.TaskType.JD_SKILL_MAPPING,
            status=QuestionGenerationJob.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=2),
        )

        with patch('smartInterviewApp.services.interview_blueprints.build_job_interview_blueprint') as build_mock:
            result = process_job_interview_blueprint_task(generation_job.id)

        self.assertEqual(result, {
            'ok': True,
            'status': 'already_running',
            'job_id': vacancy.id,
            'generation_job_id': generation_job.id,
        })
        build_mock.assert_not_called()

    def test_queued_generation_job_still_processes(self):
        vacancy = Vacancies.objects.create(
            role='Python Developer',
            description='Python Django role',
            position='1',
            status='active',
            admin=self.admin,
        )
        generation_job = QuestionGenerationJob.objects.create(
            job=vacancy,
            task_type=QuestionGenerationJob.TaskType.JD_SKILL_MAPPING,
            status=QuestionGenerationJob.Status.QUEUED,
        )

        with patch('smartInterviewApp.services.interview_blueprints.build_job_interview_blueprint') as build_mock:
            build_mock.return_value = {
                'ok': True,
                'status': 'ready',
                'job_id': vacancy.id,
                'selected_skill_count': 1,
            }
            result = process_job_interview_blueprint_task(generation_job.id)

        self.assertTrue(result['ok'])
        build_mock.assert_called_once_with(vacancy.id)
        generation_job.refresh_from_db()
        self.assertEqual(generation_job.status, QuestionGenerationJob.Status.SUCCESS)
        self.assertEqual(generation_job.attempts, 1)

    def test_repeated_generation_job_processing_does_not_duplicate_planned_skills(self):
        Skill.objects.create(
            name='Core Java',
            key='core-java',
            category='Backend',
            aliases=['JVM', 'Java SE'],
        )
        vacancy = Vacancies.objects.create(
            role='Java Backend Developer',
            description='Needs JVM internals and Java SE collections.',
            position='1',
            status='active',
            admin=self.admin,
        )
        generation_job = QuestionGenerationJob.objects.create(
            job=vacancy,
            task_type=QuestionGenerationJob.TaskType.JD_SKILL_MAPPING,
            status=QuestionGenerationJob.Status.QUEUED,
        )

        first = process_job_interview_blueprint_task(generation_job.id)
        second = process_job_interview_blueprint_task(generation_job.id)

        self.assertTrue(first['ok'])
        self.assertEqual(second['status'], 'already_processed')
        blueprint = JobInterviewBlueprint.objects.get(job=vacancy)
        self.assertEqual(JobInterviewSkill.objects.filter(blueprint=blueprint).count(), 1)

    def test_admin_registrations_import_without_error(self):
        from django.contrib import admin

        for model in [
            Skill,
            SkillQuestion,
            CodingQuestion,
            JobInterviewBlueprint,
            JobInterviewSkill,
            QuestionGenerationJob,
        ]:
            self.assertIn(model, admin.site._registry)
