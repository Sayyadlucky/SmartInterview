from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    CandidateVacancyApplication,
    CompanyProfile,
    UserProfile,
    Interview,
    Notification,
    NotificationAttempt,
    OtpRequest,
    UserNotificationPreference,
    Vacancies,
)


# Define an inline admin descriptor for UserProfile model
# which acts a bit like a singleton
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'

# Define a new User admin
class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Register other models
admin.site.register(Interview)
admin.site.register(Vacancies)


@admin.register(CandidateVacancyApplication)
class CandidateVacancyApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'candidate',
        'vacancy',
        'status',
        'pipeline_source',
        'hiring_started_at',
        'applied_at',
        'reviewed_at',
        'updated_at',
    )
    list_filter = ('status', 'pipeline_source', 'vacancy')
    search_fields = (
        'candidate__username',
        'candidate__email',
        'vacancy__role',
        'vacancy__id',
    )
    readonly_fields = ('applied_at', 'created_at', 'updated_at')


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ('legal_name', 'display_name', 'admin', 'website', 'logo_url', 'industry', 'city', 'country', 'is_active')
    list_filter = ('is_active', 'company_type', 'company_stage', 'company_size', 'industry', 'country')
    search_fields = ('legal_name', 'display_name', 'website', 'logo_url', 'company_code', 'industry', 'city', 'admin__username', 'admin__email')


@admin.register(OtpRequest)
class OtpRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'phone', 'purpose', 'status', 'attempt_count', 'provider', 'expires_at', 'created_at')
    list_filter = ('status', 'provider', 'purpose')
    search_fields = ('phone', 'provider_request_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_type', 'severity', 'status', 'final_channel', 'user', 'created_at')
    list_filter = ('severity', 'status', 'final_channel')
    search_fields = ('event_type', 'idempotency_key')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(NotificationAttempt)
class NotificationAttemptAdmin(admin.ModelAdmin):
    list_display = ('id', 'notification', 'channel', 'provider', 'status', 'provider_message_id', 'attempted_at')
    list_filter = ('channel', 'provider', 'status')
    search_fields = ('provider_message_id',)
    readonly_fields = ('attempted_at', 'updated_at')


@admin.register(UserNotificationPreference)
class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'whatsapp_opt_in', 'sms_opt_in', 'voice_opt_in', 'preferred_language', 'phone_verified_at')
    list_filter = ('whatsapp_opt_in', 'sms_opt_in', 'voice_opt_in', 'preferred_language')
