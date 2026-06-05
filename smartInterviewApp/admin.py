from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    CandidateVacancyApplication,
    CodingQuestion,
    CompanyProfile,
    InterviewFeedback,
    UserProfile,
    Interview,
    InterviewCallSession,
    InterviewReminderDelivery,
    JobInterviewBlueprint,
    JobInterviewSkill,
    Notification,
    NotificationAttempt,
    OtpRequest,
    QuestionGenerationJob,
    ResumeAiFeedback,
    ResumeAiLearningPattern,
    ResumeAiProfessionalReview,
    ResumeAiSuggestion,
    Skill,
    SkillQuestion,
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


class ResumeAiReadOnlyAdmin(admin.ModelAdmin):
    readonly_fields = ()

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ResumeAiSuggestion)
class ResumeAiSuggestionAdmin(ResumeAiReadOnlyAdmin):
    list_display = ('id', 'candidate', 'role_family', 'section_key', 'suggestion_type', 'status', 'created_at')
    list_filter = ('role_family', 'section_key', 'suggestion_type', 'status')
    search_fields = ('candidate__username', 'candidate__email', 'local_suggestion_title', 'local_suggestion_text')


@admin.register(ResumeAiFeedback)
class ResumeAiFeedbackAdmin(ResumeAiReadOnlyAdmin):
    list_display = ('id', 'suggestion', 'candidate', 'feedback', 'created_at')
    list_filter = ('feedback', 'created_at')
    search_fields = ('candidate__username', 'candidate__email', 'feedback_reason')


@admin.register(ResumeAiProfessionalReview)
class ResumeAiProfessionalReviewAdmin(ResumeAiReadOnlyAdmin):
    list_display = ('id', 'suggestion', 'candidate', 'openai_model', 'user_applied', 'error_code', 'created_at')
    list_filter = ('openai_model', 'user_applied', 'error_code', 'created_at')
    search_fields = ('candidate__username', 'candidate__email', 'professional_title', 'professional_text')


@admin.register(ResumeAiLearningPattern)
class ResumeAiLearningPatternAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'role_family',
        'section_key',
        'suggestion_type',
        'pattern_type',
        'status',
        'confidence_score',
        'source_count',
        'applied_count',
        'rejected_count',
    )
    list_filter = ('role_family', 'section_key', 'suggestion_type', 'pattern_type', 'status')
    search_fields = ('template_text', 'role_family', 'section_key', 'suggestion_type')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'category', 'is_active', 'verbal_count', 'coding_count', 'generation_job_count', 'updated_at')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'key', 'aliases', 'category')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Verbal questions')
    def verbal_count(self, obj):
        return obj.verbal_questions.count()

    @admin.display(description='Coding questions')
    def coding_count(self, obj):
        return obj.coding_questions.count()

    @admin.display(description='Generation jobs')
    def generation_job_count(self, obj):
        return obj.generation_jobs.count()


@admin.register(SkillQuestion)
class SkillQuestionAdmin(admin.ModelAdmin):
    list_display = ('skill', 'difficulty', 'question_type', 'family_key', 'question_hash', 'source', 'is_active', 'updated_at')
    list_filter = ('skill', 'difficulty', 'question_type', 'source', 'is_active')
    search_fields = ('question_text', 'skill__name', 'family_key', 'tags')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('skill',)


@admin.register(CodingQuestion)
class CodingQuestionAdmin(admin.ModelAdmin):
    list_display = ('title', 'skill', 'difficulty', 'question_type', 'family_key', 'prompt_hash', 'source', 'is_active', 'updated_at')
    list_filter = ('skill', 'difficulty', 'question_type', 'source', 'is_active')
    search_fields = ('title', 'prompt', 'skill__name', 'family_key', 'tags')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('skill',)
    prepopulated_fields = {'slug': ('title',)}


class JobInterviewSkillInline(admin.TabularInline):
    model = JobInterviewSkill
    extra = 0
    autocomplete_fields = ('skill',)
    readonly_fields = ('created_at', 'updated_at')
    fields = (
        'skill',
        'skill_role',
        'priority',
        'questions_to_ask',
        'coding_questions_to_ask',
        'confidence',
        'source',
        'is_required',
        'is_active',
        'created_at',
        'updated_at',
    )


@admin.register(JobInterviewBlueprint)
class JobInterviewBlueprintAdmin(admin.ModelAdmin):
    list_display = ('job', 'status', 'role_title', 'experience_level', 'minimum_ready', 'fully_ready', 'version', 'updated_at')
    list_filter = ('status', 'minimum_ready', 'fully_ready', 'generation_source')
    search_fields = ('job__role', 'job__position', 'job__description', 'role_title', 'raw_extracted_skills', 'selected_skills_snapshot', 'blueprint_plan')
    readonly_fields = ('created_at', 'updated_at')
    fields = (
        'job',
        'status',
        'role_title',
        'experience_level',
        'raw_extracted_skills',
        'selected_skills_snapshot',
        'blueprint_plan',
        'generation_source',
        'model_name',
        'error_message',
        'version',
        'minimum_ready',
        'fully_ready',
        'created_at',
        'updated_at',
    )
    inlines = (JobInterviewSkillInline,)


@admin.register(JobInterviewSkill)
class JobInterviewSkillAdmin(admin.ModelAdmin):
    list_display = ('job', 'skill', 'skill_role', 'priority', 'questions_to_ask', 'coding_questions_to_ask', 'confidence', 'is_active')
    list_filter = ('skill_role', 'skill', 'is_required', 'is_active', 'source')
    search_fields = ('job__role', 'job__position', 'job__description', 'skill__name')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('blueprint', 'skill')


@admin.register(QuestionGenerationJob)
class QuestionGenerationJobAdmin(admin.ModelAdmin):
    list_display = ('task_type', 'status', 'job', 'skill', 'attempts', 'started_at', 'finished_at', 'updated_at')
    list_filter = ('task_type', 'status', 'skill', 'attempts')
    search_fields = ('payload', 'result', 'error_message', 'job__role', 'job__position', 'skill__name', 'skill__key')
    readonly_fields = ('created_at', 'updated_at', 'started_at', 'finished_at')
    autocomplete_fields = ('blueprint', 'skill')


@admin.register(InterviewCallSession)
class InterviewCallSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'interview', 'initiated_by', 'exotel_call_sid', 'status', 'outcome', 'billable_seconds', 'connected_seconds', 'created_at', 'ended_at')
    list_filter = ('status', 'outcome', 'created_at')
    search_fields = ('exotel_call_sid', 'note', 'interview__id', 'interview__candidate__username', 'interview__candidate__email', 'initiated_by__username')
    readonly_fields = ('created_at', 'updated_at', 'billing_started_at', 'candidate_connected_at', 'ended_at')


@admin.register(InterviewReminderDelivery)
class InterviewReminderDeliveryAdmin(admin.ModelAdmin):
    list_display = ('id', 'interview', 'reminder_type', 'channel', 'status', 'scheduled_for', 'expected_interview_time', 'sent_at')
    list_filter = ('reminder_type', 'channel', 'status')
    search_fields = ('interview__id', 'interview__candidate__username', 'interview__candidate__email', 'cloud_task_name')
    readonly_fields = ('created_at', 'updated_at', 'sent_at')


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


@admin.register(InterviewFeedback)
class InterviewFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'room_name',
        'participant_role',
        'participant_name',
        'participant_email',
        'overall_rating',
        'experience_rating',
        'audio_video_rating',
        'ai_interviewer_rating',
        'created_at',
    )
    list_filter = (
        'participant_role',
        'interview_type',
        'summary_credit_notice_shown',
        'created_at',
    )
    search_fields = (
        'room_name',
        'interview_token',
        'participant_name',
        'participant_email',
        'user__username',
        'user__email',
    )
    readonly_fields = ('created_at',)


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
