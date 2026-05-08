# Notification System (Django + DRF + Angular)

## Overview
This implementation adds a modular notification system inside `smartInterviewApp` with:
- OTP + fallback SMS through MSG91 adapters
- WhatsApp template notifications through Meta WhatsApp Cloud API adapter
- Voice alert escalation through Exotel adapter
- Provider abstraction interfaces (`OtpProvider`, `SmsProvider`, `WhatsappProvider`, `VoiceProvider`)
- Orchestration with severity routing (`low`, `medium`, `critical`)
- Persistence models for notification attempts, OTP audits, and preferences
- Webhook handlers for status updates
- Angular typed API service and demo integration widgets in dashboard

## Backend Modules
- `smartInterviewApp/integrations/providers/`
  - `contracts.py`
  - `http_utils.py`
  - `msg91.py`
  - `meta_whatsapp.py`
  - `exotel.py`
- `smartInterviewApp/otp/services.py`
- `smartInterviewApp/notifications/services.py`
- `smartInterviewApp/notifications/channels.py`
- `smartInterviewApp/notifications/utils.py`
- `smartInterviewApp/webhooks/services.py`
- `smartInterviewApp/api/serializers.py`
- `smartInterviewApp/api/views.py`
- `smartInterviewApp/api/urls.py`

## Models
Added/updated in `smartInterviewApp/models.py`:
- `OtpRequest`
- `Notification` (enhanced for orchestration and status lifecycle)
- `NotificationAttempt`
- `UserNotificationPreference`

Migration file:
- `smartInterviewApp/migrations/0004_notification_system.py`
- `smartInterviewApp/migrations/0005_notification_updated_at_non_null.py`

## Required Environment Variables
Set these in your environment (or `.env` loader if you add one):

### MSG91
- `MSG91_AUTH_KEY`
- `MSG91_SENDER_ID`
- `MSG91_ROUTE` (default: `4`)
- `MSG91_OTP_TEMPLATE_ID`
- `MSG91_INTERVIEW_TEMPLATE_ID`
- `MSG91_CANDIDATE_SIGNUP_TEMPLATE_ID`
- `MSG91_INTERVIEW_REMINDER_ONE_HOUR_TEMPLATE_ID`
- `MSG91_INTERVIEW_REMINDER_THIRTY_MIN_TEMPLATE_ID`
- `MSG91_INTERVIEW_REMINDER_FIFTEEN_MIN_TEMPLATE_ID`
- `MSG91_OTP_LENGTH` (default: `6`)
- `MSG91_OTP_EXPIRY_SECONDS` (default: `300`)
- `MSG91_OTP_RESEND_COOLDOWN_SECONDS` (default: `60`)
- `MSG91_OTP_MAX_VERIFY_ATTEMPTS` (default: `5`)
- `MSG91_WEBHOOK_TOKEN` (optional callback validation)
- `MSG91_WEBHOOK_SECRET` (optional HMAC SHA-256 signature validation)
- `MSG91_MOCK_MODE` (default: `false`)

### Meta WhatsApp Cloud API
- `META_WHATSAPP_TOKEN`
- `META_WHATSAPP_PHONE_NUMBER_ID`
- `META_WHATSAPP_VERIFY_TOKEN`
- `META_WHATSAPP_API_VERSION` (default: `v21.0`)
- `META_WHATSAPP_APP_SECRET` (used for webhook signature validation)
- `META_WHATSAPP_MOCK_MODE` (default: `false`)

### Exotel
- `EXOTEL_SID`
- `EXOTEL_TOKEN`
- `EXOTEL_CALLER_ID`
- `EXOTEL_FLOW_ID`
- `EXOTEL_SUBDOMAIN` (default: `api.exotel.com`)
- `EXOTEL_WEBHOOK_TOKEN` (optional callback validation)
- `EXOTEL_WEBHOOK_SECRET` (optional HMAC SHA-256 signature validation)
- `EXOTEL_MOCK_MODE` (default: `false`)

### Orchestration + Logging
- `NOTIFICATION_RETRY_LIMIT` (default: `2`)
- `NOTIFICATION_RETRY_BACKOFF_SECONDS` (default: `10`)
- `NOTIFICATION_LOG_LEVEL` (default: `INFO`)
- `NOTIFICATION_PROVIDER_MODE` (`real` or `mock`, default: `real`)

### API Throttling (OTP)
- `DRF_THROTTLE_ANON_RATE` (default: `120/minute`)
- `DRF_THROTTLE_USER_RATE` (default: `300/minute`)
- `OTP_REQUEST_THROTTLE_RATE` (default: `10/minute`)
- `OTP_VERIFY_THROTTLE_RATE` (default: `20/minute`)
- `OTP_RESEND_THROTTLE_RATE` (default: `5/minute`)

## API Endpoints
- `POST /api/auth/request-otp/`
- `POST /api/auth/verify-otp/`
- `POST /api/auth/resend-otp/`
- `POST /api/notifications/send/`
- `GET /api/notifications/<id>/`
- `GET /api/webhooks/whatsapp/meta/` (Meta verify handshake)
- `POST /api/webhooks/whatsapp/meta/`
- `POST /api/webhooks/msg91/`
- `POST /api/webhooks/exotel/`

Validation notes:
- OTP endpoints validate phone format, OTP length, and allowed purposes.
- Notification send validates payload shape and destination fields.
- Webhook endpoints validate required callback identifiers before status updates.
- OTP endpoints use scoped DRF throttles.

## Severity Routing
- `low`: WhatsApp only
- `medium`: WhatsApp, fallback to SMS on failure
- `critical`: WhatsApp -> SMS -> Voice escalation

## Angular Integration
Added under `angular/frontend/src/app/notifications/`:
- Typed models and API service
- OTP console component
- Notification trigger component
- Notification status component
- Combined console embedded in dashboard

Helper:
- `angular/frontend/src/app/core/api-base.ts`

## Setup Steps
1. Install project dependencies including Django REST Framework in your environment.
2. Export all required environment variables.
3. Run migrations:
   - `python3 manage.py migrate`
4. Start Django server.
5. Start Angular frontend as per existing project flow.

## API Request/Response Examples
### Request OTP
`POST /api/auth/request-otp/`
```json
{
  "phone": "919876543210",
  "purpose": "login"
}
```
```json
{
  "success": true,
  "error": null,
  "data": {
    "success": true,
    "message": "If the number is valid, an OTP has been sent."
  }
}
```

### Verify OTP
`POST /api/auth/verify-otp/`
```json
{
  "phone": "919876543210",
  "purpose": "login",
  "otp": "123456"
}
```
```json
{
  "success": true,
  "error": null,
  "data": {
    "success": true,
    "message": "OTP verified."
  }
}
```

### Send Notification
`POST /api/notifications/send/`
```json
{
  "event_type": "interview_reminder",
  "severity": "medium",
  "payload": {
    "to": "919876543210",
    "template_name": "interview_reminder",
    "language_code": "en",
    "sms_message": "Interview starts in 30 minutes"
  },
  "idempotency_key": "notif-evt-1001"
}
```
```json
{
  "success": true,
  "error": null,
  "data": {
    "id": 15,
    "event_type": "interview_reminder",
    "severity": "medium",
    "status": "sent",
    "final_channel": "whatsapp",
    "attempts": []
  }
}
```

### Webhook (MSG91) callback
`POST /api/webhooks/msg91/`
```json
{
  "request_id": "abc123",
  "status": "delivered",
  "token": "optional-token"
}
```
```json
{
  "success": true,
  "error": null,
  "data": {
    "updated": true
  }
}
```

## Testing
Added tests in `smartInterviewApp/tests.py` for:
- OTP request + verify
- Medium fallback (WhatsApp -> SMS)
- Critical escalation (WhatsApp -> SMS -> Voice)
- Meta webhook status updates

Run:
- `python3 manage.py test smartInterviewApp`

## Assumptions
- Existing auth is Django session-based.
- Phone values can come from payload or `UserProfile.phone`.
- If no async worker exists, sending is synchronous with retry hooks.
- Existing `Notification` model was extended to preserve backwards compatibility (`message`, `read`).

## Production Hardening TODOs
- Add Redis-based distributed rate-limits for OTP and send endpoints.
- Move retries/escalation into Celery/RQ tasks for non-blocking delivery.
- Add end-to-end integration tests against sandbox provider environments.
- Add API throttling classes and request-id middleware for full traceability.
