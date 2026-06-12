from django.contrib import admin
from django.db.models import F
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    AptitudeAnswer,
    AptitudeIntegrityEvent,
    AptitudeQuestionBank,
    AptitudeQuestionGenerationJob,
    AptitudeSection,
    AptitudeTestAssignment,
    AptitudeTestQuestion,
    AptitudeTestResult,
    AptitudeTestTemplate,
    AptitudeTestTemplateSection,
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
    LitioAssistantConversation,
    LitioAssistantFeedback,
    LitioAssistantKnowledge,
    LitioAssistantKnowledgeGap,
    LitioAssistantMessage,
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
from .services.interview_blueprints import enqueue_job_interview_blueprint
from .services.question_banks import enqueue_question_generation_jobs


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


@admin.register(LitioAssistantKnowledge)
class LitioAssistantKnowledgeAdmin(admin.ModelAdmin):
    list_display = ('title', 'intent_key', 'category', 'priority', 'is_active', 'updated_at')
    list_filter = ('is_active', 'category', 'intent_key', 'updated_at')
    search_fields = ('title', 'intent_key', 'category', 'keywords', 'question_patterns', 'answer')
    ordering = ('category', 'intent_key', '-priority', 'title')
    readonly_fields = ('created_at', 'updated_at')
    actions = ('mark_selected_active', 'mark_selected_inactive', 'increase_priority', 'decrease_priority')

    fieldsets = (
        ('Identity', {
            'fields': ('title', 'intent_key', 'category', 'priority', 'is_active')
        }),
        ('Matching', {
            'fields': ('question_patterns', 'keywords')
        }),
        ('Answer', {
            'fields': ('answer',)
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    @admin.action(description='Mark selected as active')
    def mark_selected_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'Marked {updated} knowledge row(s) as active.')

    @admin.action(description='Mark selected as inactive')
    def mark_selected_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'Marked {updated} knowledge row(s) as inactive.')

    @admin.action(description='Increase priority by 1')
    def increase_priority(self, request, queryset):
        queryset.update(priority=F('priority') - 1)
        self.message_user(request, f'Increased priority for {queryset.count()} row(s).')

    @admin.action(description='Decrease priority by 1')
    def decrease_priority(self, request, queryset):
        queryset.update(priority=F('priority') + 1)
        self.message_user(request, f'Decreased priority for {queryset.count()} row(s).')


class LitioAssistantMessageInline(admin.TabularInline):
    model = LitioAssistantMessage
    extra = 0
    fields = ('sender', 'content', 'intent_key', 'confidence', 'created_at')
    readonly_fields = ('sender', 'content', 'intent_key', 'confidence', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LitioAssistantConversation)
class LitioAssistantConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('title', 'user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (LitioAssistantMessageInline,)


@admin.register(LitioAssistantMessage)
class LitioAssistantMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'intent_key', 'confidence', 'created_at')
    list_filter = ('sender', 'intent_key', 'created_at')
    search_fields = ('content', 'intent_key', 'conversation__title')
    readonly_fields = ('created_at',)


@admin.register(LitioAssistantFeedback)
class LitioAssistantFeedbackAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'message', 'user', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('comment', 'conversation__title', 'user__username', 'user__email')
    readonly_fields = ('created_at',)


@admin.register(LitioAssistantKnowledgeGap)
class LitioAssistantKnowledgeGapAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'status',
        'fallback_reason',
        'question_preview',
        'normalized_question',
        'context_page',
        'context_section',
        'user',
        'company',
    )
    list_filter = ('status', 'fallback_reason', 'created_at')
    search_fields = ('original_question', 'normalized_question', 'admin_notes')
    readonly_fields = (
        'original_question',
        'normalized_question',
        'context',
        'fallback_reason',
        'conversation',
        'message',
        'company',
        'user',
        'created_at',
        'updated_at',
    )
    # Using fieldsets below; do not define top-level `fields` to avoid admin.E005
    actions = ('mark_reviewed', 'mark_ignored', 'mark_resolved', 'create_draft_knowledge_from_selected_gaps')

    fieldsets = (
        ('Gap', {
            'fields': ('original_question', 'normalized_question', 'fallback_reason', 'status')
        }),
        ('Review', {
            'fields': ('admin_notes', 'resolved_by_knowledge')
        }),
        ('Context', {
            'fields': ('context', 'context_page', 'context_section')
        }),
        ('Links', {
            'fields': ('conversation', 'message', 'company', 'user')
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def question_preview(self, obj):
        return (obj.original_question or '')[:120]
    question_preview.short_description = 'question_preview'

    def context_page(self, obj):
        if isinstance(obj.context, dict):
            return obj.context.get('page') or obj.context.get('openModal') or ''
        return ''
    context_page.short_description = 'context_page'

    def context_section(self, obj):
        if isinstance(obj.context, dict):
            return obj.context.get('section') or obj.context.get('activeTab') or ''
        return ''
    context_section.short_description = 'context_section'

    def age_days(self, obj):
        if not obj.created_at:
            return ''
        delta = timezone.now() - obj.created_at
        return delta.days
    age_days.short_description = 'age_days'

    @admin.action(description='Mark selected as reviewed')
    def mark_reviewed(self, request, queryset):
        updated = queryset.update(status=LitioAssistantKnowledgeGap.Status.REVIEWED)
        self.message_user(request, f'Marked {updated} gap(s) as reviewed.')

    @admin.action(description='Mark selected as ignored')
    def mark_ignored(self, request, queryset):
        updated = queryset.update(status=LitioAssistantKnowledgeGap.Status.IGNORED)
        self.message_user(request, f'Marked {updated} gap(s) as ignored.')

    @admin.action(description='Mark selected as resolved')
    def mark_resolved(self, request, queryset):
        updated = queryset.update(status=LitioAssistantKnowledgeGap.Status.RESOLVED)
        self.message_user(request, f'Marked {updated} gap(s) as resolved.')

    @admin.action(description='Create draft knowledge from selected gaps')
    def create_draft_knowledge_from_selected_gaps(self, request, queryset):
        from .models import LitioAssistantKnowledge

        created = 0
        skipped = 0
        for gap in queryset:
            if gap.resolved_by_knowledge_id:
                skipped += 1
                continue
            title = (gap.original_question or '')[:140] or f'Knowledge draft from gap {gap.id}'
            # Ensure unique intent_key by appending gap id to base key to avoid unique constraint errors
            intent_key = f'gap_review_{gap.id}'
            try:
                knowledge = LitioAssistantKnowledge.objects.create(
                    title=title,
                    intent_key=intent_key,
                    category='knowledge_gap',
                    priority=0,
                    is_active=False,
                    question_patterns=[p for p in ([gap.original_question] + ([gap.normalized_question] if gap.normalized_question else [])) if p],
                    keywords=[],
                    answer='TODO: Add reviewed answer.',
                )
                # link gap to created knowledge and mark reviewed
                gap.resolved_by_knowledge = knowledge
                gap.status = LitioAssistantKnowledgeGap.Status.REVIEWED
                gap.save(update_fields=['resolved_by_knowledge', 'status'])
                created += 1
            except Exception:
                skipped += 1
        self.message_user(request, f'Created {created} draft knowledge row(s); skipped {skipped}.')


@admin.register(Vacancies)
class VacanciesAdmin(admin.ModelAdmin):
    list_display = ('id', 'role', 'status', 'position', 'admin', 'company', 'date')
    list_filter = ('status', 'job_type', 'company')
    search_fields = ('role', 'description', 'position', 'admin__username', 'admin__email', 'company__legal_name', 'company__display_name')
    autocomplete_fields = ('recruiter', 'admin', 'company')
    actions = ('generate_or_regenerate_interview_blueprint',)

    @admin.action(description='Generate or regenerate interview blueprint')
    def generate_or_regenerate_interview_blueprint(self, request, queryset):
        queued = 0
        skipped = 0
        for vacancy in queryset:
            result = enqueue_job_interview_blueprint(vacancy.id)
            if result.get('queued') or result.get('mode') in {'cloud_tasks', 'db_queue_only', 'already_queued_or_running', 'deduped'}:
                queued += 1
            else:
                skipped += 1
        self.message_user(
            request,
            f'Interview blueprint generation requested for {queued} vacancy row(s); skipped {skipped}.',
        )


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
    actions = ('regenerate_question_generation_jobs',)

    @admin.action(description='Regenerate question generation jobs')
    def regenerate_question_generation_jobs(self, request, queryset):
        requested = 0
        for blueprint in queryset:
            results = enqueue_question_generation_jobs(blueprint.id)
            requested += sum(1 for item in results if item.get('queued') or item.get('ok'))
        self.message_user(
            request,
            f'Question generation enqueue requested for {queryset.count()} blueprint row(s); {requested} enqueue result(s) returned.',
        )


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


@admin.register(AptitudeSection)
class AptitudeSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'default_order', 'is_active', 'updated_at')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at')
    prepopulated_fields = {'code': ('name',)}


@admin.register(AptitudeQuestionBank)
class AptitudeQuestionBankAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'section',
        'question_type',
        'difficulty',
        'role_family',
        'skill_tag',
        'quality_status',
        'marks',
        'is_active',
        'updated_at',
    )
    list_filter = ('section', 'question_type', 'difficulty', 'quality_status', 'is_active')
    search_fields = ('question_text', 'question_html', 'role_family', 'skill_tag', 'topic_tag', 'explanation')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('section', 'created_by')


@admin.register(AptitudeQuestionGenerationJob)
class AptitudeQuestionGenerationJobAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'section',
        'status',
        'role_family',
        'skill_tag',
        'target_count',
        'batch_size',
        'generated_count',
        'accepted_count',
        'rejected_count',
        'attempts',
        'updated_at',
    )
    list_filter = ('status', 'section', 'quality_status_for_created', 'provider', 'created_at')
    search_fields = ('section__name', 'section__code', 'role_family', 'skill_tag', 'topic_tag', 'error_message')
    readonly_fields = ('created_at', 'updated_at', 'started_at', 'finished_at')
    autocomplete_fields = ('section', 'created_by')


class AptitudeTestTemplateSectionInline(admin.TabularInline):
    model = AptitudeTestTemplateSection
    extra = 0
    autocomplete_fields = ('section',)


@admin.register(AptitudeTestTemplate)
class AptitudeTestTemplateAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'role_type',
        'role_family',
        'duration_minutes',
        'total_questions',
        'total_marks',
        'passing_score_percent',
        'is_active',
        'updated_at',
    )
    list_filter = ('role_type', 'negative_marking_enabled', 'randomize_questions', 'allow_retake', 'is_active')
    search_fields = ('title', 'description', 'role_family')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('created_by',)
    inlines = (AptitudeTestTemplateSectionInline,)


@admin.register(AptitudeTestTemplateSection)
class AptitudeTestTemplateSectionAdmin(admin.ModelAdmin):
    list_display = ('template', 'section', 'question_count', 'marks_per_question', 'order_index', 'is_required')
    list_filter = ('section', 'is_required')
    search_fields = ('template__title', 'section__name', 'section__code')
    autocomplete_fields = ('template', 'section')


class AptitudeTestQuestionInline(admin.TabularInline):
    model = AptitudeTestQuestion
    extra = 0
    fields = ('order_index', 'section', 'question_type', 'difficulty', 'marks', 'source_question')
    readonly_fields = ()
    autocomplete_fields = ('section', 'source_question')


class AptitudeIntegrityEventInline(admin.TabularInline):
    model = AptitudeIntegrityEvent
    extra = 0
    fields = ('event_type', 'occurred_at')
    readonly_fields = ('occurred_at',)
    can_delete = False


@admin.register(AptitudeTestAssignment)
class AptitudeTestAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'candidate',
        'vacancy',
        'interview',
        'status',
        'role_type',
        'attempt_number',
        'created_at',
        'submitted_at',
    )
    list_filter = ('status', 'role_type', 'negative_marking_enabled', 'allow_retake', 'created_at')
    search_fields = (
        'title',
        'public_token',
        'candidate__username',
        'candidate__email',
        'vacancy__role',
        'interview__id',
    )
    readonly_fields = ('public_token', 'created_at', 'updated_at')
    autocomplete_fields = ('candidate', 'vacancy', 'template', 'created_by')
    inlines = (AptitudeTestQuestionInline, AptitudeIntegrityEventInline)


@admin.register(AptitudeTestQuestion)
class AptitudeTestQuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'assignment', 'section', 'question_type', 'difficulty', 'marks', 'order_index')
    list_filter = ('section', 'question_type', 'difficulty')
    search_fields = (
        'assignment__title',
        'assignment__public_token',
        'question_text',
        'role_family',
        'skill_tag',
        'topic_tag',
    )
    autocomplete_fields = ('assignment', 'source_question', 'section')


@admin.register(AptitudeAnswer)
class AptitudeAnswerAdmin(admin.ModelAdmin):
    list_display = ('id', 'assignment', 'question', 'is_correct', 'marks_awarded', 'answered_at')
    list_filter = ('is_correct', 'answered_at')
    search_fields = ('assignment__title', 'assignment__public_token', 'question__question_text')
    readonly_fields = ('answered_at', 'created_at')
    autocomplete_fields = ('assignment', 'question')


@admin.register(AptitudeTestResult)
class AptitudeTestResultAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'assignment',
        'attempted_questions',
        'correct_answers',
        'marks_obtained',
        'score_percent',
        'passed',
        'updated_at',
    )
    list_filter = ('assignment__status', 'assignment__role_type', 'passed', 'created_at')
    search_fields = ('assignment__title', 'assignment__public_token', 'assignment__candidate__username', 'assignment__candidate__email')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('assignment',)


@admin.register(AptitudeIntegrityEvent)
class AptitudeIntegrityEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'assignment', 'event_type', 'occurred_at')
    list_filter = ('event_type', 'occurred_at')
    search_fields = ('assignment__title', 'assignment__public_token', 'event_payload')
    readonly_fields = ('occurred_at',)
    autocomplete_fields = ('assignment',)


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
