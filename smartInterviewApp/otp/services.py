from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from smartInterviewApp.emailing import send_email_otp_notification
from smartInterviewApp.integrations.providers.contracts import ProviderResult
from smartInterviewApp.integrations.providers.meta_whatsapp import MetaWhatsappProvider
from smartInterviewApp.integrations.providers.msg91 import Msg91OtpProvider, Msg91SmsProvider
from smartInterviewApp.models import EmailOtpRequest, OtpRequest, UserNotificationPreference
from smartInterviewApp.notifications.utils import logger, safe_log


GENERIC_OTP_RESPONSE = {'success': True, 'message': 'If the number is valid, an OTP has been sent.'}


class OtpService:
    def __init__(self) -> None:
        self.provider = Msg91OtpProvider()
        self.sms_provider = Msg91SmsProvider()
        self.whatsapp_provider = MetaWhatsappProvider()

    def _normalize_phone(self, phone: str) -> str:
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) == 10:
            return f'91{digits}'
        return digits

    def _generate_otp(self) -> str:
        size = max(4, min(settings.MSG91_OTP_LENGTH, 8))
        return ''.join(str(random.randint(0, 9)) for _ in range(size))

    def request_otp(self, phone: str, purpose: str, user: User | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = self._normalize_phone(phone)
        now = timezone.now()
        existing = OtpRequest.objects.filter(
            phone=normalized,
            purpose=purpose,
            status=OtpRequest.Status.REQUESTED,
            expires_at__gt=now,
        ).order_by('-created_at').first()

        if existing and existing.next_resend_at > now:
            return {
                'success': False,
                'message': 'Please wait before requesting another OTP.',
                'retry_after_seconds': int((existing.next_resend_at - now).total_seconds()),
            }

        otp = self._generate_otp()
        provider_result = self.provider.request_otp(
            phone=normalized,
            otp=otp,
            purpose=purpose,
            expires_in_seconds=settings.MSG91_OTP_EXPIRY_SECONDS,
        )
        whatsapp_result = self._send_whatsapp_otp(normalized, otp, purpose)
        fallback_result: ProviderResult | None = None
        if not provider_result.success:
            fallback_result = self.sms_provider.send_sms(
                to=normalized,
                message=f'Your Shortlistii verification code is {otp}. Do not share this OTP with anyone.\n\n--Shortlistii',
                metadata={'purpose': purpose, 'fallback': True},
            )

        otp_request = OtpRequest.objects.create(
            user=user,
            phone=normalized,
            purpose=purpose,
            provider=self.provider.name,
            provider_request_id=provider_result.provider_request_id,
            status=OtpRequest.Status.REQUESTED if (provider_result.success or (fallback_result and fallback_result.success) or whatsapp_result.success) else OtpRequest.Status.FAILED,
            attempt_count=0,
            max_attempts=settings.MSG91_OTP_MAX_VERIFY_ATTEMPTS,
            otp_hash=make_password(otp),
            expires_at=now + timedelta(seconds=settings.MSG91_OTP_EXPIRY_SECONDS),
            next_resend_at=now + timedelta(seconds=settings.MSG91_OTP_RESEND_COOLDOWN_SECONDS),
            metadata={
                **(metadata or {}),
                'primary_provider': provider_result.response_payload,
                'fallback_provider': fallback_result.response_payload if fallback_result else {},
                'whatsapp_provider': whatsapp_result.response_payload,
            },
        )

        logger.info('OTP requested', extra=safe_log({'phone': normalized, 'purpose': purpose, 'status': otp_request.status}))
        if not provider_result.success and not (fallback_result and fallback_result.success) and not whatsapp_result.success:
            return {'success': False, 'message': 'Unable to process OTP request. Please try again later.'}
        return GENERIC_OTP_RESPONSE

    def _send_whatsapp_otp(self, phone: str, otp: str, purpose: str) -> ProviderResult:
        return self.whatsapp_provider.send_authentication_message(
            to=phone,
            template_name=getattr(settings, 'PHONE_VERIFICATION_WHATSAPP_TEMPLATE', 'verify_phone_otp'),
            language_code=getattr(settings, 'DEFAULT_WHATSAPP_LANGUAGE_CODE', 'en'),
            code=otp,
            metadata={'purpose': purpose, 'channel': 'whatsapp_authentication_otp'},
        )

    def resend_otp(self, phone: str, purpose: str, user: User | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request_otp(phone=phone, purpose=purpose, user=user, metadata=metadata)

    @transaction.atomic
    def verify_otp(self, phone: str, otp: str, purpose: str) -> dict[str, Any]:
        normalized = self._normalize_phone(phone)
        now = timezone.now()
        otp_request = (
            OtpRequest.objects.select_for_update()
            .filter(phone=normalized, purpose=purpose)
            .order_by('-created_at')
            .first()
        )

        if not otp_request:
            return {'success': False, 'message': 'Invalid OTP.'}

        if otp_request.expires_at <= now:
            otp_request.status = OtpRequest.Status.EXPIRED
            otp_request.save(update_fields=['status', 'updated_at'])
            return {'success': False, 'message': 'OTP has expired.'}

        if otp_request.attempt_count >= otp_request.max_attempts:
            otp_request.status = OtpRequest.Status.FAILED
            otp_request.save(update_fields=['status', 'updated_at'])
            return {'success': False, 'message': 'Maximum verification attempts exceeded.'}

        otp_request.attempt_count += 1
        valid = bool(otp_request.otp_hash and check_password(otp, otp_request.otp_hash))

        if valid:
            otp_request.status = OtpRequest.Status.VERIFIED
            otp_request.save(update_fields=['status', 'attempt_count', 'updated_at'])
            if otp_request.user:
                prefs, _ = UserNotificationPreference.objects.get_or_create(user=otp_request.user)
                prefs.phone_verified_at = now
                prefs.save(update_fields=['phone_verified_at', 'updated_at'])
            return {'success': True, 'message': 'OTP verified.'}

        otp_request.status = OtpRequest.Status.FAILED
        otp_request.save(update_fields=['status', 'attempt_count', 'updated_at'])
        logger.warning('OTP verification failed', extra=safe_log({'phone': normalized, 'purpose': purpose}))
        return {'success': False, 'message': 'Invalid OTP.'}


def request_otp(phone: str, purpose: str, user: User | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return OtpService().request_otp(phone=phone, purpose=purpose, user=user, metadata=metadata)


def verify_otp(phone: str, otp: str, purpose: str) -> dict[str, Any]:
    return OtpService().verify_otp(phone=phone, otp=otp, purpose=purpose)


def resend_otp(phone: str, purpose: str, user: User | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return OtpService().resend_otp(phone=phone, purpose=purpose, user=user, metadata=metadata)


class EmailVerificationService:
    def _generate_otp(self) -> str:
        size = max(4, min(settings.MSG91_OTP_LENGTH, 8))
        return ''.join(str(random.randint(0, 9)) for _ in range(size))

    def request_otp(self, email: str, purpose: str, user: User | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = (email or '').strip().lower()
        now = timezone.now()
        existing = EmailOtpRequest.objects.filter(
            email=normalized,
            purpose=purpose,
            status=EmailOtpRequest.Status.REQUESTED,
            expires_at__gt=now,
        ).order_by('-created_at').first()

        cooldown = getattr(settings, 'EMAIL_OTP_RESEND_COOLDOWN_SECONDS', settings.MSG91_OTP_RESEND_COOLDOWN_SECONDS)
        expiry = getattr(settings, 'EMAIL_OTP_EXPIRY_SECONDS', settings.MSG91_OTP_EXPIRY_SECONDS)
        max_attempts = getattr(settings, 'EMAIL_OTP_MAX_VERIFY_ATTEMPTS', settings.MSG91_OTP_MAX_VERIFY_ATTEMPTS)

        if existing and existing.next_resend_at > now:
            return {
                'success': False,
                'message': 'Please wait before requesting another OTP.',
                'retry_after_seconds': int((existing.next_resend_at - now).total_seconds()),
            }

        otp = self._generate_otp()
        send_email_otp_notification(
            to_email=normalized,
            otp=otp,
            expires_in_minutes=max(1, int(expiry / 60)),
        )

        EmailOtpRequest.objects.create(
            user=user,
            email=normalized,
            purpose=purpose,
            status=EmailOtpRequest.Status.REQUESTED,
            attempt_count=0,
            max_attempts=max_attempts,
            otp_hash=make_password(otp),
            expires_at=now + timedelta(seconds=expiry),
            next_resend_at=now + timedelta(seconds=cooldown),
            metadata=metadata or {},
        )
        return {'success': True, 'message': 'If the email is valid, an OTP has been sent.'}

    @transaction.atomic
    def verify_otp(self, email: str, otp: str, purpose: str) -> dict[str, Any]:
        normalized = (email or '').strip().lower()
        now = timezone.now()
        otp_request = (
            EmailOtpRequest.objects.select_for_update()
            .filter(email=normalized, purpose=purpose)
            .order_by('-created_at')
            .first()
        )
        if not otp_request:
            return {'success': False, 'message': 'Invalid OTP.'}
        if otp_request.expires_at <= now:
            otp_request.status = EmailOtpRequest.Status.EXPIRED
            otp_request.save(update_fields=['status', 'updated_at'])
            return {'success': False, 'message': 'OTP has expired.'}
        if otp_request.attempt_count >= otp_request.max_attempts:
            otp_request.status = EmailOtpRequest.Status.FAILED
            otp_request.save(update_fields=['status', 'updated_at'])
            return {'success': False, 'message': 'Maximum verification attempts exceeded.'}

        otp_request.attempt_count += 1
        valid = bool(otp_request.otp_hash and check_password(otp, otp_request.otp_hash))
        if valid:
            otp_request.status = EmailOtpRequest.Status.VERIFIED
            otp_request.save(update_fields=['status', 'attempt_count', 'updated_at'])
            if otp_request.user:
                prefs, _ = UserNotificationPreference.objects.get_or_create(user=otp_request.user)
                prefs.email_verified_at = now
                prefs.save(update_fields=['email_verified_at', 'updated_at'])
            return {'success': True, 'message': 'Email verified.'}

        otp_request.status = EmailOtpRequest.Status.FAILED
        otp_request.save(update_fields=['status', 'attempt_count', 'updated_at'])
        return {'success': False, 'message': 'Invalid OTP.'}


def request_email_otp(email: str, purpose: str, user: User | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return EmailVerificationService().request_otp(email=email, purpose=purpose, user=user, metadata=metadata)


def verify_email_otp(email: str, otp: str, purpose: str) -> dict[str, Any]:
    return EmailVerificationService().verify_otp(email=email, otp=otp, purpose=purpose)
