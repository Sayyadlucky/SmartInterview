from __future__ import annotations

import re
from typing import Any

from django.contrib.auth.models import User
from rest_framework import serializers

from smartInterviewApp.models import LitioAssistantConversation, LitioAssistantFeedback, LitioAssistantMessage, Notification

PHONE_RE = re.compile(r'^\+?[0-9]{10,15}$')
ALLOWED_PURPOSES = {'login', 'signup', 'password_reset', 'verify_phone', 'verify_email'}


class OtpRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    purpose = serializers.CharField(max_length=64)

    def validate_phone(self, value: str) -> str:
        normalized = value.strip()
        if not PHONE_RE.match(normalized):
            raise serializers.ValidationError('Enter a valid phone number.')
        return normalized

    def validate_purpose(self, value: str) -> str:
        purpose = value.strip().lower()
        if purpose not in ALLOWED_PURPOSES:
            raise serializers.ValidationError(f'Purpose must be one of: {", ".join(sorted(ALLOWED_PURPOSES))}.')
        return purpose


class OtpVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    otp = serializers.CharField(max_length=10)
    purpose = serializers.CharField(max_length=64)

    def validate_phone(self, value: str) -> str:
        normalized = value.strip()
        if not PHONE_RE.match(normalized):
            raise serializers.ValidationError('Enter a valid phone number.')
        return normalized

    def validate_otp(self, value: str) -> str:
        token = value.strip()
        if not token.isdigit() or len(token) < 4 or len(token) > 8:
            raise serializers.ValidationError('OTP must be 4 to 8 digits.')
        return token

    def validate_purpose(self, value: str) -> str:
        purpose = value.strip().lower()
        if purpose not in ALLOWED_PURPOSES:
            raise serializers.ValidationError(f'Purpose must be one of: {", ".join(sorted(ALLOWED_PURPOSES))}.')
        return purpose


class OtpResendSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    purpose = serializers.CharField(max_length=64)

    def validate_phone(self, value: str) -> str:
        normalized = value.strip()
        if not PHONE_RE.match(normalized):
            raise serializers.ValidationError('Enter a valid phone number.')
        return normalized

    def validate_purpose(self, value: str) -> str:
        purpose = value.strip().lower()
        if purpose not in ALLOWED_PURPOSES:
            raise serializers.ValidationError(f'Purpose must be one of: {", ".join(sorted(ALLOWED_PURPOSES))}.')
        return purpose


class NotificationSendSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=128)
    severity = serializers.ChoiceField(choices=Notification.Severity.choices)
    user_id = serializers.IntegerField(required=False)
    payload = serializers.JSONField()
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        user_id = attrs.get('user_id')
        if user_id and not User.objects.filter(id=user_id).exists():
            raise serializers.ValidationError({'user_id': 'User not found.'})
        payload = attrs.get('payload') or {}
        if not isinstance(payload, dict):
            raise serializers.ValidationError({'payload': 'Payload must be an object.'})
        if not payload.get('to') and not payload.get('phone') and not user_id:
            raise serializers.ValidationError({'payload': 'Payload must include `to` or `phone` when `user_id` is not provided.'})
        return attrs


class NotificationResponseSerializer(serializers.ModelSerializer):
    attempts = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            'id',
            'event_type',
            'severity',
            'status',
            'final_channel',
            'payload',
            'metadata',
            'created_at',
            'updated_at',
            'attempts',
        )

    def get_attempts(self, obj: Notification) -> list[dict[str, Any]]:
        return [
            {
                'id': attempt.id,
                'channel': attempt.channel,
                'provider': attempt.provider,
                'status': attempt.status,
                'provider_message_id': attempt.provider_message_id,
                'attempted_at': attempt.attempted_at,
                'updated_at': attempt.updated_at,
            }
            for attempt in obj.attempts.all().order_by('attempted_at')
        ]


class LitioAssistantChatSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000, trim_whitespace=True)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_conversation_id(self, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise serializers.ValidationError('conversation_id is invalid.')
        if not LitioAssistantConversation.objects.filter(id=value).exists():
            raise serializers.ValidationError('Conversation was not found.')
        return value


class LitioAssistantFeedbackSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField()
    message_id = serializers.IntegerField(required=False, allow_null=True)
    rating = serializers.ChoiceField(choices=LitioAssistantFeedback.Rating.choices)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate_conversation_id(self, value: int) -> int:
        if not LitioAssistantConversation.objects.filter(id=value).exists():
            raise serializers.ValidationError('Conversation was not found.')
        return value

    def validate_message_id(self, value: int | None) -> int | None:
        if value is None:
            return None
        if not LitioAssistantMessage.objects.filter(id=value).exists():
            raise serializers.ValidationError('Message was not found.')
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        message_id = attrs.get('message_id')
        conversation_id = attrs.get('conversation_id')
        if message_id and not LitioAssistantMessage.objects.filter(id=message_id, conversation_id=conversation_id).exists():
            raise serializers.ValidationError({'message_id': 'Message does not belong to this conversation.'})
        return attrs


class Msg91WebhookSerializer(serializers.Serializer):
    request_id = serializers.CharField(required=False, allow_blank=True)
    id = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=True)
    token = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        provider_id = (attrs.get('request_id') or attrs.get('id') or '').strip()
        if not provider_id:
            raise serializers.ValidationError('Either `request_id` or `id` is required.')
        attrs['provider_message_id'] = provider_id
        return attrs


class ExotelWebhookSerializer(serializers.Serializer):
    CallSid = serializers.CharField(required=False, allow_blank=True)
    Sid = serializers.CharField(required=False, allow_blank=True)
    CallStatus = serializers.CharField(required=False, allow_blank=True)
    Status = serializers.CharField(required=False, allow_blank=True)
    EventType = serializers.CharField(required=False, allow_blank=True)
    token = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        provider_id = (attrs.get('CallSid') or attrs.get('Sid') or '').strip()
        call_status = (attrs.get('CallStatus') or attrs.get('Status') or '').strip()
        event_type = (attrs.get('EventType') or '').strip()
        if not provider_id:
            raise serializers.ValidationError('Either `CallSid` or `Sid` is required.')
        if not call_status and not event_type:
            raise serializers.ValidationError('One of `CallStatus`, `Status`, or `EventType` is required.')
        attrs['provider_message_id'] = provider_id
        attrs['event_status'] = call_status or event_type
        return attrs
