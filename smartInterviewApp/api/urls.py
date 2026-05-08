from django.urls import path

from smartInterviewApp.api.views import (
    ExotelWebhookApi,
    MetaWhatsappWebhookApi,
    Msg91WebhookApi,
    NotificationDetailApi,
    RequestOtpApi,
    ResendOtpApi,
    SendNotificationApi,
    VerifyOtpApi,
)

urlpatterns = [
    path('auth/request-otp/', RequestOtpApi.as_view(), name='api-request-otp'),
    path('auth/verify-otp/', VerifyOtpApi.as_view(), name='api-verify-otp'),
    path('auth/resend-otp/', ResendOtpApi.as_view(), name='api-resend-otp'),
    path('notifications/send/', SendNotificationApi.as_view(), name='api-notifications-send'),
    path('notifications/<int:notification_id>/', NotificationDetailApi.as_view(), name='api-notifications-detail'),
    path('webhooks/whatsapp/meta/', MetaWhatsappWebhookApi.as_view(), name='api-webhook-meta-whatsapp'),
    path('webhooks/msg91/', Msg91WebhookApi.as_view(), name='api-webhook-msg91'),
    path('webhooks/exotel/', ExotelWebhookApi.as_view(), name='api-webhook-exotel'),
]
