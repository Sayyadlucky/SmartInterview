from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from smartInterviewApp.api.serializers import (
    ExotelWebhookSerializer,
    Msg91WebhookSerializer,
    NotificationResponseSerializer,
    NotificationSendSerializer,
    OtpRequestSerializer,
    OtpResendSerializer,
    OtpVerifySerializer,
)
from smartInterviewApp.api.throttles import OtpRateThrottle
from smartInterviewApp.models import Notification
from smartInterviewApp.notifications.services import NotificationService
from smartInterviewApp.otp.services import OtpService
from smartInterviewApp.services.interview_calls import InterviewCallService
from smartInterviewApp.webhooks.services import WebhookService


class RequestOtpApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OtpRateThrottle]
    throttle_scope = 'otp_request'

    def post(self, request):
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = OtpService()
        result = service.request_otp(
            phone=serializer.validated_data['phone'],
            purpose=serializer.validated_data['purpose'],
            user=request.user if request.user.is_authenticated else None,
            metadata={'ip': request.META.get('REMOTE_ADDR', '')},
        )
        code = status.HTTP_200_OK if result.get('success') else status.HTTP_429_TOO_MANY_REQUESTS
        return Response({'success': result.get('success', False), 'error': None if result.get('success') else result.get('message'), 'data': result}, status=code)


class VerifyOtpApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OtpRateThrottle]
    throttle_scope = 'otp_verify'

    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = OtpService()
        result = service.verify_otp(
            phone=serializer.validated_data['phone'],
            otp=serializer.validated_data['otp'],
            purpose=serializer.validated_data['purpose'],
        )
        code = status.HTTP_200_OK if result.get('success') else status.HTTP_400_BAD_REQUEST
        return Response({'success': result.get('success', False), 'error': None if result.get('success') else result.get('message'), 'data': result}, status=code)


class ResendOtpApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OtpRateThrottle]
    throttle_scope = 'otp_resend'

    def post(self, request):
        serializer = OtpResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = OtpService()
        result = service.resend_otp(
            phone=serializer.validated_data['phone'],
            purpose=serializer.validated_data['purpose'],
            user=request.user if request.user.is_authenticated else None,
            metadata={'ip': request.META.get('REMOTE_ADDR', '')},
        )
        code = status.HTTP_200_OK if result.get('success') else status.HTTP_429_TOO_MANY_REQUESTS
        return Response({'success': result.get('success', False), 'error': None if result.get('success') else result.get('message'), 'data': result}, status=code)


class SendNotificationApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = NotificationSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if serializer.validated_data.get('user_id'):
            user = User.objects.filter(id=serializer.validated_data['user_id']).first()

        service = NotificationService()
        notification = service.send_notification(
            event_type=serializer.validated_data['event_type'],
            severity=serializer.validated_data['severity'],
            user=user,
            payload=serializer.validated_data['payload'],
            idempotency_key=serializer.validated_data.get('idempotency_key'),
        )
        return Response(
            {
                'success': True,
                'error': None,
                'data': NotificationResponseSerializer(notification).data,
            },
            status=status.HTTP_201_CREATED,
        )


class NotificationDetailApi(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, notification_id: int):
        notification = (
            request.user.notifications.filter(id=notification_id).first()
            if not request.user.is_superuser
            else None
        )
        if request.user.is_superuser:
            notification = Notification.objects.filter(id=notification_id).first()

        if not notification:
            return Response({'success': False, 'error': 'Notification not found.', 'data': None}, status=status.HTTP_404_NOT_FOUND)

        return Response({'success': True, 'error': None, 'data': NotificationResponseSerializer(notification).data})


class MetaWhatsappWebhookApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        mode = request.GET.get('hub.mode')
        verify_token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        if mode == 'subscribe' and verify_token == settings.META_WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge or '', status=200)
        return HttpResponse('Invalid verification token', status=403)

    def post(self, request):
        service = WebhookService()
        signature = request.META.get('HTTP_X_HUB_SIGNATURE_256')
        raw_body = request.body
        if not service.verify_meta_signature(raw_body, signature):
            return Response({'success': False, 'error': 'Invalid signature', 'data': None}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data if isinstance(request.data, dict) else json.loads(raw_body.decode('utf-8') or '{}')
        events = service.extract_meta_status_events(payload)
        for item in events:
            service.update_attempt_status(item['provider_message_id'], item['status'], payload)
        return Response({'success': True, 'error': None, 'data': {'processed': len(events)}})


class Msg91WebhookApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = Msg91WebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = WebhookService()
        secret = settings.MSG91_WEBHOOK_SECRET
        if secret:
            signature = request.headers.get('X-Webhook-Signature') or request.headers.get('X-Signature')
            if not service.verify_hmac_signature(request.body, signature, secret):
                return Response({'success': False, 'error': 'Invalid webhook signature', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        expected_token = settings.MSG91_WEBHOOK_TOKEN
        if expected_token:
            incoming = request.headers.get('X-Webhook-Token') or serializer.validated_data.get('token')
            if incoming != expected_token:
                return Response({'success': False, 'error': 'Invalid webhook token', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        provider_message_id = serializer.validated_data['provider_message_id']
        event_status = serializer.validated_data['status']
        updated = service.update_attempt_status(provider_message_id, event_status, dict(request.data))
        return Response({'success': True, 'error': None, 'data': {'updated': updated}})


class ExotelWebhookApi(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ExotelWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = WebhookService()
        secret = settings.EXOTEL_WEBHOOK_SECRET
        if secret:
            signature = request.headers.get('X-Webhook-Signature') or request.headers.get('X-Signature')
            if not service.verify_hmac_signature(request.body, signature, secret):
                return Response({'success': False, 'error': 'Invalid webhook signature', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        expected_token = settings.EXOTEL_WEBHOOK_TOKEN
        if expected_token:
            incoming = request.headers.get('X-Webhook-Token') or serializer.validated_data.get('token') or request.GET.get('token')
            if incoming != expected_token:
                return Response({'success': False, 'error': 'Invalid webhook token', 'data': None}, status=status.HTTP_403_FORBIDDEN)
        provider_message_id = serializer.validated_data['provider_message_id']
        event_status = serializer.validated_data['event_status']
        updated = service.update_attempt_status(provider_message_id, event_status, dict(request.data))
        InterviewCallService().sync_session_from_webhook(provider_message_id, dict(request.data))
        return Response({'success': True, 'error': None, 'data': {'updated': updated}})
