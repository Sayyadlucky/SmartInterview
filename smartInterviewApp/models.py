import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from smartInterviewApp.pgvector_compat import HnswIndex, VectorField


def generate_aptitude_public_token():
    return uuid.uuid4().hex


# Profile table linked to built-in User
class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('candidate', 'Candidate'),
        ('recruiter', 'Recruiter'),
        ('interviewer', 'Interviewer'),
        ('admin', 'Admin'),
    )
    Gender_CHOICES = (
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='candidate')
    profile_picture = models.FileField(upload_to='profile_pictures/', blank=True, null=True)
    resume = models.FileField(upload_to='resumes/', blank=True, null=True)
    notifications_enabled = models.BooleanField(default=True)
    phone = models.CharField(max_length=15,null=True)
    gender = models.CharField(max_length=10, null=True, choices=Gender_CHOICES, default='other')
    company_url = models.URLField(blank=True, default='')
    company = models.ForeignKey(
        'CompanyProfile',
        on_delete=models.SET_NULL,
        related_name='user_profiles',
        null=True,
        blank=True
    )
    hr = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='hr',
        limit_choices_to={'profile__role': 'admin'},
        null=True, blank=True
    )
    recruiter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='assigned_interviewers',
        limit_choices_to={'profile__role': 'recruiter'},
        null=True, blank=True
    )
    def __str__(self):
        return f"{self.user.username} ({self.role})"


class RecruiterNote(models.Model):
    recruiter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='recruiter_workspace_notes',
        limit_choices_to={'profile__role': 'recruiter'},
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='authored_recruiter_workspace_notes',
        null=True,
        blank=True,
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recruiter', '-created_at']),
        ]

    def __str__(self):
        return f"Note for {self.recruiter.username} by {self.author.username if self.author else 'system'}"


class LitioAssistantKnowledge(models.Model):
    class Category(models.TextChoices):
        WORKFLOW = 'workflow', 'Workflow'
        FEATURE = 'feature', 'Feature'
        POLICY = 'policy', 'Policy'

    title = models.CharField(max_length=180)
    intent_key = models.CharField(max_length=120, unique=True)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.FEATURE)
    question_patterns = models.JSONField(default=list, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    answer = models.TextField()
    priority = models.PositiveSmallIntegerField(default=50, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'title']
        indexes = [
            models.Index(fields=['is_active', 'priority']),
            models.Index(fields=['intent_key']),
        ]

    def __str__(self):
        return self.title


class LitioAssistantConversation(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='litio_assistant_conversations',
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=180, blank=True, default='')
    status = models.CharField(max_length=30, default='open', db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['user', 'updated_at']),
            models.Index(fields=['status', 'updated_at']),
        ]

    def __str__(self):
        return self.title or f'Litio Assistant Conversation {self.id}'


class LitioAssistantMessage(models.Model):
    class Sender(models.TextChoices):
        USER = 'user', 'User'
        ASSISTANT = 'assistant', 'Assistant'

    conversation = models.ForeignKey(
        LitioAssistantConversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.CharField(max_length=20, choices=Sender.choices, db_index=True)
    content = models.TextField()
    intent_key = models.CharField(max_length=120, blank=True, default='', db_index=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['sender', 'created_at']),
        ]

    def __str__(self):
        return f'{self.sender} message for conversation {self.conversation_id}'


class LitioAssistantFeedback(models.Model):
    class Rating(models.TextChoices):
        HELPFUL = 'helpful', 'Helpful'
        NOT_HELPFUL = 'not_helpful', 'Not Helpful'

    conversation = models.ForeignKey(
        LitioAssistantConversation,
        on_delete=models.CASCADE,
        related_name='feedback',
    )
    message = models.ForeignKey(
        LitioAssistantMessage,
        on_delete=models.SET_NULL,
        related_name='feedback',
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='litio_assistant_feedback',
        null=True,
        blank=True,
    )
    rating = models.CharField(max_length=20, choices=Rating.choices)
    comment = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['rating', 'created_at']),
        ]

    def __str__(self):
        return f'Litio Assistant feedback {self.rating} for conversation {self.conversation_id}'


class CompanyProfile(models.Model):
    class CompanyType(models.TextChoices):
        PRIVATE = 'private', 'Private Limited'
        PUBLIC = 'public', 'Public Company'
        LLP = 'llp', 'LLP'
        PARTNERSHIP = 'partnership', 'Partnership'
        SOLE = 'sole_proprietorship', 'Sole Proprietorship'
        NON_PROFIT = 'non_profit', 'Non Profit'
        GOVERNMENT = 'government', 'Government'
        AGENCY = 'agency', 'Agency / Consultancy'
        OTHER = 'other', 'Other'

    class CompanyStage(models.TextChoices):
        BOOTSTRAPPED = 'bootstrapped', 'Bootstrapped'
        SEED = 'seed', 'Seed'
        SERIES_A = 'series_a', 'Series A'
        SERIES_B = 'series_b', 'Series B'
        SERIES_C = 'series_c', 'Series C+'
        GROWTH = 'growth', 'Growth'
        ENTERPRISE = 'enterprise', 'Enterprise'
        PUBLIC = 'public_market', 'Public Market'
        OTHER = 'other', 'Other'

    class CompanySize(models.TextChoices):
        SOLO = '1_10', '1-10'
        SMALL = '11_50', '11-50'
        MID_SMALL = '51_200', '51-200'
        MID = '201_500', '201-500'
        LARGE = '501_1000', '501-1,000'
        XL = '1001_5000', '1,001-5,000'
        XXL = '5001_10000', '5,001-10,000'
        ENTERPRISE = '10000_plus', '10,000+'

    admin = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='company_profile',
        limit_choices_to={'profile__role': 'admin'},
    )
    legal_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default='')
    company_code = models.CharField(max_length=50, blank=True, default='', db_index=True)
    description = models.TextField(blank=True, default='')
    industry = models.CharField(max_length=120, blank=True, default='', db_index=True)
    sub_industry = models.CharField(max_length=120, blank=True, default='')
    company_type = models.CharField(max_length=30, choices=CompanyType.choices, default=CompanyType.PRIVATE)
    company_stage = models.CharField(max_length=30, choices=CompanyStage.choices, blank=True, default='')
    company_size = models.CharField(max_length=20, choices=CompanySize.choices, blank=True, default='')
    employee_count = models.PositiveIntegerField(null=True, blank=True)
    founded_year = models.PositiveIntegerField(null=True, blank=True)

    website = models.URLField(blank=True, default='')
    careers_page = models.URLField(blank=True, default='')
    linkedin_url = models.URLField(blank=True, default='')
    twitter_url = models.URLField(blank=True, default='')
    logo_url = models.URLField(blank=True, default='')
    logo = models.FileField(upload_to='company_logos/', blank=True, null=True)

    contact_email = models.EmailField(blank=True, default='')
    contact_phone = models.CharField(max_length=20, blank=True, default='')
    alternate_phone = models.CharField(max_length=20, blank=True, default='')

    address_line_1 = models.CharField(max_length=255, blank=True, default='')
    address_line_2 = models.CharField(max_length=255, blank=True, default='')
    landmark = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='', db_index=True)
    state = models.CharField(max_length=120, blank=True, default='')
    postal_code = models.CharField(max_length=20, blank=True, default='')
    country = models.CharField(max_length=120, blank=True, default='India')
    headquarters = models.CharField(max_length=255, blank=True, default='')
    timezone = models.CharField(max_length=80, blank=True, default='Asia/Kolkata')

    registration_number = models.CharField(max_length=120, blank=True, default='')
    tax_identifier = models.CharField(max_length=120, blank=True, default='')
    currency_code = models.CharField(max_length=10, blank=True, default='INR')

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['legal_name', 'id']
        indexes = [
            models.Index(fields=['industry', 'city']),
            models.Index(fields=['company_code']),
            models.Index(fields=['legal_name']),
        ]

    def __str__(self):
        return self.display_name or self.legal_name


class Interview(models.Model):
    INTERVIEW_TYPE_CHOICES = (
        ('manual', 'Manual Interview'),
        ('auto', 'Auto Interview'),
    )

    STATUS_CHOICES = (
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('shortlisted', 'Shortlisted'),
        ('offer_made', 'Offer Made'),
        ('offer_accepted', 'Offer Accepted'),
        ('offer_declined', 'Offer Declined'),
        ('hired', 'Hired'),
        ('assessment_pending', 'Assessment Pending'),
        ('rejected', 'Rejected'),
        ('assessment_completed', 'Assessment Completed'),
        ('auto_screening_scheduled', 'Auto Screening Scheduled'),
    )

    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='candidate_interviews',
        limit_choices_to={'profile__role': 'candidate'}
    )
    recruiter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='recruiter_interviews',
        limit_choices_to={'profile__role': 'recruiter'},
        null=True, blank=True
    )
    interviewer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='interviewer_interviews',
        limit_choices_to={'profile__role': 'interviewer'},
        null=True, blank=True
    )
    interview_type = models.CharField(
        max_length=20,
        choices=INTERVIEW_TYPE_CHOICES,
        default='manual'
    )
    date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='scheduled')
    litio_interview_token = models.CharField(max_length=80, unique=True, null=True, blank=True, db_index=True)
    candidate_signup_token = models.CharField(max_length=80, unique=True, null=True, blank=True, db_index=True)
    candidate_signup_token_created_at = models.DateTimeField(null=True, blank=True)
    hired_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    recording_url = models.URLField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    role = models.ForeignKey(
        'Vacancies',
        on_delete=models.CASCADE,
        related_name='interviews',
        null=True,
        blank=True
    )
    hr = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='hr_interviews',
        limit_choices_to={'profile__role': 'admin'},
        null=True, blank=True
    )

    def __str__(self):
        return f"Interview: {self.candidate.username} with {self.recruiter.username} on {self.date}"


class CandidateResume(models.Model):
    class ParseStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='resumes',
        limit_choices_to={'profile__role': 'candidate'}
    )
    interview = models.ForeignKey(
        Interview,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resume_snapshots'
    )
    source_file = models.CharField(max_length=500, blank=True, default='')
    original_filename = models.CharField(max_length=255, blank=True, default='')
    file_size = models.PositiveIntegerField(default=0)
    mime_type = models.CharField(max_length=120, blank=True, default='')
    parser_provider = models.CharField(max_length=80, blank=True, default='heuristic')
    parser_version = models.CharField(max_length=40, blank=True, default='v1')
    status = models.CharField(max_length=20, choices=ParseStatus.choices, default=ParseStatus.PENDING)
    error_message = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    raw_text = models.TextField(blank=True, default='')
    structured_data = models.JSONField(default=dict, blank=True)
    candidate_type = models.CharField(max_length=30, blank=True, default='')
    headline = models.CharField(max_length=255, blank=True, default='')
    summary = models.TextField(blank=True, default='')
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=20, blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    total_experience_years = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    current_title = models.CharField(max_length=255, blank=True, default='')
    current_company = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Resume {self.id} for {self.candidate.username} ({self.status})"


class CandidateResumeSection(models.Model):
    resume = models.ForeignKey(CandidateResume, on_delete=models.CASCADE, related_name='sections')
    section_key = models.CharField(max_length=80)
    title = models.CharField(max_length=120)
    section_type = models.CharField(max_length=80, blank=True, default='')
    display_order = models.PositiveIntegerField(default=0)
    content = models.JSONField(default=dict, blank=True)
    raw_text = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f"{self.title} ({self.resume_id})"


class CandidateResumeBuilderDraft(models.Model):
    candidate = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='resume_builder_draft',
        limit_choices_to={'profile__role': 'candidate'},
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Resume Builder Draft for {self.candidate.username}"


class ResumeAiSuggestion(models.Model):
    class Status(models.TextChoices):
        SHOWN = 'shown', 'Shown'
        APPLIED = 'applied', 'Applied'
        IGNORED = 'ignored', 'Ignored'
        NOT_USEFUL = 'not_useful', 'Not Useful'
        PROFESSIONAL_REQUESTED = 'professional_requested', 'Professional Requested'
        PROFESSIONAL_APPLIED = 'professional_applied', 'Professional Applied'

    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='resume_ai_suggestions',
        limit_choices_to={'profile__role': 'candidate'},
    )
    draft = models.ForeignKey(
        CandidateResumeBuilderDraft,
        on_delete=models.SET_NULL,
        related_name='ai_suggestions',
        null=True,
        blank=True,
    )
    section_key = models.CharField(max_length=80)
    step_key = models.CharField(max_length=80, blank=True, default='')
    role_family = models.CharField(max_length=80, blank=True, default='general')
    resume_type = models.CharField(max_length=80, blank=True, default='incomplete')
    suggestion_type = models.CharField(max_length=80)
    local_suggestion_title = models.CharField(max_length=180)
    local_suggestion_text = models.TextField()
    local_suggestion_payload = models.JSONField(default=dict, blank=True)
    source_context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SHOWN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['role_family', 'section_key', 'suggestion_type', 'status'], name='rai_suggest_lookup_idx'),
            models.Index(fields=['candidate', 'created_at'], name='rai_suggest_cand_idx'),
        ]

    def __str__(self):
        return f"{self.suggestion_type} for {self.candidate.username}"


class ResumeAiFeedback(models.Model):
    class Feedback(models.TextChoices):
        LIKED = 'liked', 'Liked'
        APPLIED = 'applied', 'Applied'
        IGNORED = 'ignored', 'Ignored'
        NOT_USEFUL = 'not_useful', 'Not Useful'
        REQUESTED_PROFESSIONAL_REVIEW = 'requested_professional_review', 'Requested Professional Review'
        APPLIED_PROFESSIONAL_REVIEW = 'applied_professional_review', 'Applied Professional Review'

    suggestion = models.ForeignKey(ResumeAiSuggestion, on_delete=models.CASCADE, related_name='feedback_events')
    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='resume_ai_feedback',
        limit_choices_to={'profile__role': 'candidate'},
    )
    feedback = models.CharField(max_length=48, choices=Feedback.choices)
    feedback_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['candidate', 'created_at'], name='rai_feedback_cand_idx'),
        ]

    def __str__(self):
        return f"{self.feedback} for suggestion {self.suggestion_id}"


class ResumeAiProfessionalReview(models.Model):
    suggestion = models.ForeignKey(ResumeAiSuggestion, on_delete=models.CASCADE, related_name='professional_reviews')
    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='resume_ai_professional_reviews',
        limit_choices_to={'profile__role': 'candidate'},
    )
    openai_model = models.CharField(max_length=100, blank=True, default='')
    prompt_version = models.CharField(max_length=40, blank=True, default='')
    professional_title = models.CharField(max_length=180, blank=True, default='')
    professional_text = models.TextField(blank=True, default='')
    professional_payload = models.JSONField(default=dict, blank=True)
    user_applied = models.BooleanField(default=False)
    error_code = models.CharField(max_length=80, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['candidate', 'created_at'], name='rai_review_cand_idx'),
        ]

    def __str__(self):
        return f"Professional review {self.id} for suggestion {self.suggestion_id}"


class ResumeAiLearningPattern(models.Model):
    class Status(models.TextChoices):
        CANDIDATE = 'candidate', 'Candidate'
        TRUSTED = 'trusted', 'Trusted'
        DISABLED = 'disabled', 'Disabled'

    role_family = models.CharField(max_length=80, blank=True, default='general')
    resume_type = models.CharField(max_length=80, blank=True, default='incomplete')
    section_key = models.CharField(max_length=80)
    suggestion_type = models.CharField(max_length=80)
    pattern_type = models.CharField(max_length=80)
    template_text = models.TextField(blank=True, default='')
    keywords_json = models.JSONField(default=list, blank=True)
    rule_payload = models.JSONField(default=dict, blank=True)
    source_count = models.PositiveIntegerField(default=0)
    applied_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    confidence_score = models.FloatField(default=0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.CANDIDATE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-confidence_score', '-updated_at']
        indexes = [
            models.Index(fields=['role_family', 'section_key', 'suggestion_type', 'status'], name='rai_pattern_lookup_idx'),
            models.Index(fields=['confidence_score'], name='rai_pattern_conf_idx'),
        ]

    def __str__(self):
        return f"{self.pattern_type} {self.role_family}/{self.section_key}"


class CandidateSearchProfile(models.Model):
    candidate = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='search_profile',
        limit_choices_to={'profile__role': 'candidate'},
    )
    active_resume = models.ForeignKey(
        CandidateResume,
        on_delete=models.SET_NULL,
        related_name='search_profiles',
        null=True,
        blank=True,
    )
    normalized_title = models.CharField(max_length=255, blank=True, default='', db_index=True)
    normalized_skills = models.JSONField(default=list, blank=True)
    role_family = models.CharField(max_length=80, blank=True, default='', db_index=True)
    role_subfamily = models.CharField(max_length=80, blank=True, default='', db_index=True)
    experience_years = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, db_index=True)
    location_normalized = models.CharField(max_length=255, blank=True, default='', db_index=True)
    latest_role_summary = models.CharField(max_length=255, blank=True, default='')
    recent_companies = models.JSONField(default=list, blank=True)
    domain_exposure = models.JSONField(default=list, blank=True)
    availability = models.CharField(max_length=120, blank=True, default='')
    profile_quality_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    search_text = models.TextField(blank=True, default='')
    embedding = VectorField(dimensions=384, null=True, blank=True)
    embedding_json = models.JSONField(default=list, blank=True)
    search_metadata = models.JSONField(default=dict, blank=True)
    parser_signature = models.CharField(max_length=128, blank=True, default='', db_index=True)
    source_signature = models.CharField(max_length=128, blank=True, default='', db_index=True)
    inactive_reason = models.CharField(max_length=120, blank=True, default='', db_index=True)
    active_resume_found = models.BooleanField(default=False)
    searchable_profile_built = models.BooleanField(default=False)
    missing_fields_summary = models.JSONField(default=list, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['-indexed_at', '-updated_at']
        indexes = [
            models.Index(fields=['role_family', 'role_subfamily'], name='cand_search_family_idx'),
            models.Index(fields=['location_normalized', 'experience_years'], name='cand_search_loc_exp_idx'),
            HnswIndex(
                name='cand_search_embedding_hnsw',
                fields=['embedding'],
                opclasses=['vector_cosine_ops'],
                m=16,
                ef_construction=64,
            ),
        ]

    def __str__(self):
        return f"SearchProfile<{self.candidate_id}>"


class RoleSearchCache(models.Model):
    vacancy = models.OneToOneField(
        'Vacancies',
        on_delete=models.CASCADE,
        related_name='search_cache',
    )
    query_signature = models.CharField(max_length=128, blank=True, default='', db_index=True)
    role_family = models.CharField(max_length=80, blank=True, default='', db_index=True)
    role_subfamily = models.CharField(max_length=80, blank=True, default='', db_index=True)
    location_normalized = models.CharField(max_length=255, blank=True, default='')
    search_text = models.TextField(blank=True, default='')
    embedding = VectorField(dimensions=384, null=True, blank=True)
    embedding_json = models.JSONField(default=list, blank=True)
    search_metadata = models.JSONField(default=dict, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"RoleSearchCache<{self.vacancy_id}>"


class OtpRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Requested'
        VERIFIED = 'verified', 'Verified'
        FAILED = 'failed', 'Failed'
        EXPIRED = 'expired', 'Expired'
        RATE_LIMITED = 'rate_limited', 'Rate Limited'

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='otp_requests')
    phone = models.CharField(max_length=20, db_index=True)
    purpose = models.CharField(max_length=64, db_index=True)
    provider = models.CharField(max_length=40, default='msg91_otp')
    provider_request_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    otp_hash = models.CharField(max_length=255, blank=True, null=True)
    expires_at = models.DateTimeField()
    next_resend_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP {self.phone} ({self.purpose}) - {self.status}"


class EmailOtpRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Requested'
        VERIFIED = 'verified', 'Verified'
        FAILED = 'failed', 'Failed'
        EXPIRED = 'expired', 'Expired'
        RATE_LIMITED = 'rate_limited', 'Rate Limited'

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='email_otp_requests')
    email = models.EmailField(db_index=True)
    purpose = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    otp_hash = models.CharField(max_length=255, blank=True, null=True)
    expires_at = models.DateTimeField()
    next_resend_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Email OTP {self.email} ({self.purpose}) - {self.status}"


class CandidateIdentityVerification(models.Model):
    class Method(models.TextChoices):
        OFFLINE_XML = 'offline_xml', 'Offline XML'
        DOCUMENT_UPLOAD = 'document_upload', 'Document Upload'
        LIVE_SELFIE = 'live_selfie', 'Live Selfie'

    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not Started'
        PROCESSING = 'processing', 'Processing'
        XML_VERIFIED = 'xml_verified', 'XML Verified'
        DOCUMENT_MATCHED = 'document_matched', 'Document Matched'
        DOCUMENT_MISMATCH = 'document_mismatch', 'Document Mismatch'
        SELFIE_CAPTURED = 'selfie_captured', 'Selfie Captured'
        FACE_MATCHED = 'face_matched', 'Face Matched'
        FACE_MISMATCH = 'face_mismatch', 'Face Mismatch'
        PROFILE_PHOTO_REQUIRED = 'profile_photo_required', 'Profile Photo Required'
        FAILED = 'failed', 'Failed'

    candidate = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='identity_verification',
        limit_choices_to={'profile__role': 'candidate'},
    )
    verification_method = models.CharField(max_length=30, choices=Method.choices, blank=True, default='')
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NOT_STARTED)
    uploaded_xml = models.FileField(upload_to='identity/offline_xml/', blank=True, null=True)
    uploaded_pdf = models.FileField(upload_to='identity/documents/', blank=True, null=True)
    uploaded_front_image = models.FileField(upload_to='identity/documents/', blank=True, null=True)
    uploaded_back_image = models.FileField(upload_to='identity/documents/', blank=True, null=True)
    live_selfie_image = models.ImageField(upload_to='identity/live_selfies/', blank=True, null=True)
    face_match_score = models.FloatField(null=True, blank=True)
    face_match_threshold = models.FloatField(null=True, blank=True)
    face_match_payload = models.JSONField(default=dict, blank=True)
    aadhaar_name = models.CharField(max_length=255, blank=True, default='')
    aadhaar_gender = models.CharField(max_length=20, blank=True, default='')
    aadhaar_dob = models.CharField(max_length=40, blank=True, default='')
    aadhaar_reference = models.CharField(max_length=80, blank=True, default='')
    raw_text = models.TextField(blank=True, default='')
    extracted_data = models.JSONField(default=dict, blank=True)
    comparison = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Identity verification for {self.candidate.username} ({self.status})"


class CandidateInsightSnapshot(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not Started'
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    candidate = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='insight_snapshot',
        limit_choices_to={'profile__role': 'candidate'},
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    source_signature = models.CharField(max_length=128, blank=True, default='')
    generated_for_role = models.CharField(max_length=255, blank=True, default='')
    generated_for_title = models.CharField(max_length=255, blank=True, default='')
    executive_summary = models.TextField(blank=True, default='')
    profile_strength_summary = models.TextField(blank=True, default='')
    profile_strength_evidence = models.JSONField(default=list, blank=True)
    profile_strength_missing_items = models.JSONField(default=list, blank=True)
    profile_strength_confidence = models.CharField(max_length=20, blank=True, default='')
    role_fit_summary = models.TextField(blank=True, default='')
    role_fit_confidence = models.CharField(max_length=20, blank=True, default='')
    role_fit_evidence = models.JSONField(default=list, blank=True)
    role_fit_matched_requirements = models.JSONField(default=list, blank=True)
    role_fit_missing_requirements = models.JSONField(default=list, blank=True)
    data_quality_flags = models.JSONField(default=list, blank=True)
    resume_score = models.PositiveIntegerField(null=True, blank=True)
    role_fit_score = models.PositiveIntegerField(null=True, blank=True)
    market_demand_score = models.PositiveIntegerField(null=True, blank=True)
    current_skills_impact_score = models.PositiveIntegerField(null=True, blank=True)
    market_demand_label = models.CharField(max_length=80, blank=True, default='')
    salary_range = models.CharField(max_length=120, blank=True, default='')
    salary_trend_summary = models.TextField(blank=True, default='')
    market_demand_summary = models.TextField(blank=True, default='')
    current_skills_impact_summary = models.TextField(blank=True, default='')
    top_strengths = models.JSONField(default=list, blank=True)
    growth_areas = models.JSONField(default=list, blank=True)
    recommended_skills = models.JSONField(default=list, blank=True)
    recommended_roles = models.JSONField(default=list, blank=True)
    model_name = models.CharField(max_length=80, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    requested_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Insight snapshot for {self.candidate.username} ({self.status})"


class AutoInterviewEvaluationResult(models.Model):
    interview = models.OneToOneField(
        'Interview',
        on_delete=models.DO_NOTHING,
        related_name='auto_interview_evaluation_result',
        db_column='interview_id',
        primary_key=False,
    )
    interview_token = models.CharField(max_length=80, blank=True, default='', db_index=True)
    room_name = models.CharField(max_length=120, blank=True, default='', db_index=True)
    candidate_name = models.CharField(max_length=160, blank=True, default='')
    decision = models.CharField(max_length=40, blank=True, default='', db_index=True)
    recommendation = models.CharField(max_length=80, blank=True, default='')
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    executive_summary = models.TextField(blank=True, default='')
    summary_verdict = models.TextField(blank=True, default='')
    evaluation_payload = models.JSONField(default=dict, blank=True)
    conversation_payload = models.JSONField(default=list, blank=True)
    early_exit = models.BooleanField(default=False, db_index=True)
    early_exit_reason = models.CharField(max_length=160, blank=True, default='')
    trace_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        managed = False
        db_table = 'conference_autointerviewevaluationresult'
        ordering = ['-updated_at']

    def __str__(self):
        return f"Auto interview evaluation <{self.interview_id}>"


# Notification table
class Notification(models.Model):
    class Severity(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        CRITICAL = 'critical', 'Critical'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        PARTIAL = 'partial', 'Partial'
        DELIVERED = 'delivered', 'Delivered'
        READ = 'read', 'Read'
        ESCALATED = 'escalated', 'Escalated'

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    event_type = models.CharField(max_length=128, blank=True, default='')
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.LOW)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    message = models.TextField(blank=True, default='')
    read = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    final_channel = models.CharField(max_length=30, blank=True, default='')

    def __str__(self):
        username = self.user.username if self.user else 'anonymous'
        return f"Notification {self.id} for {username}"


class NotificationAttempt(models.Model):
    class Channel(models.TextChoices):
        WHATSAPP = 'whatsapp', 'WhatsApp'
        SMS = 'sms', 'SMS'
        VOICE = 'voice', 'Voice'

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        READ = 'read', 'Read'
        FAILED = 'failed', 'Failed'
        CALLBACK_RECEIVED = 'callback_received', 'Callback Received'

    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='attempts')
    channel = models.CharField(max_length=20, choices=Channel.choices)
    provider = models.CharField(max_length=40)
    provider_message_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.QUEUED)
    response_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['attempted_at']

    def __str__(self):
        return f"Attempt {self.channel} ({self.provider}) - {self.status}"


class UserNotificationPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preference')
    whatsapp_opt_in = models.BooleanField(default=True)
    sms_opt_in = models.BooleanField(default=True)
    voice_opt_in = models.BooleanField(default=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    preferred_language = models.CharField(max_length=10, default='en')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Prefs for {self.user.username}"


class InterviewReminderDelivery(models.Model):
    class ReminderType(models.TextChoices):
        ONE_HOUR = 'one_hour', '60 Minutes Before'
        THIRTY_MIN = 'thirty_min', '30 Minutes Before'
        FIFTEEN_MIN = 'fifteen_min', '15 Minutes Before'

    class Channel(models.TextChoices):
        SMS = 'sms', 'SMS'
        WHATSAPP = 'whatsapp', 'WhatsApp'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'
        SKIPPED = 'skipped', 'Skipped'

    interview = models.ForeignKey('Interview', on_delete=models.CASCADE, related_name='reminder_deliveries')
    reminder_type = models.CharField(max_length=20, choices=ReminderType.choices)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    scheduled_for = models.DateTimeField(db_index=True)
    expected_interview_time = models.DateTimeField(db_index=True)
    cloud_task_name = models.CharField(max_length=500, blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')
    provider_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['interview', 'reminder_type', 'channel', 'expected_interview_time'],
                name='uniq_interview_reminder_delivery',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'scheduled_for']),
            models.Index(fields=['interview', 'status']),
            models.Index(fields=['channel', 'status']),
        ]
        ordering = ['scheduled_for', 'id']

    def __str__(self):
        return f"Reminder {self.reminder_type}/{self.channel} for interview {self.interview_id} ({self.status})"


class InterviewCallSession(models.Model):
    class Status(models.TextChoices):
        DIALING_AGENT = 'dialing_agent', 'Dialing Agent'
        CONNECTING_CANDIDATE = 'connecting_candidate', 'Connecting Candidate'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        BUSY = 'busy', 'Busy'
        NO_ANSWER = 'no_answer', 'No Answer'
        CANCELLED = 'cancelled', 'Cancelled'
        DISCONNECTED = 'disconnected', 'Disconnected'

    interview = models.ForeignKey('Interview', on_delete=models.CASCADE, related_name='call_sessions')
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='initiated_call_sessions')
    exotel_call_sid = models.CharField(max_length=128, blank=True, default='', db_index=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DIALING_AGENT, db_index=True)
    caller_phone = models.CharField(max_length=20, blank=True, default='')
    candidate_phone = models.CharField(max_length=20, blank=True, default='')
    billing_started_at = models.DateTimeField(null=True, blank=True)
    candidate_connected_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    billable_seconds = models.PositiveIntegerField(default=0)
    connected_seconds = models.PositiveIntegerField(default=0)
    disconnect_requested_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=30, blank=True, default='')
    note = models.TextField(blank=True, default='')
    note_updated_at = models.DateTimeField(null=True, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['interview', 'status']),
            models.Index(fields=['initiated_by', 'created_at']),
            models.Index(fields=['exotel_call_sid']),
        ]

    def __str__(self):
        return f"Call {self.exotel_call_sid or self.id} for interview {self.interview_id} ({self.status})"


class Vacancies(models.Model):
    class JobType(models.TextChoices):
        FULL_TIME = 'full_time', 'Full Time'
        PART_TIME = 'part_time', 'Part Time'
        INTERN = 'intern', 'Intern'

    STATUS_CHOICES = (
        ('active', 'Active'),
        ('hired', 'Hired'),
        ('canceled', 'Canceled'),
        ('closed', 'Closed'),
    )
    role = models.CharField(max_length=100)
    recruiter = models.ManyToManyField(
        User,
        related_name='vacancies',
        limit_choices_to={'profile__role': 'recruiter'},
        blank=True
    )
    description = models.TextField()
    position = models.CharField(max_length=100)
    job_type = models.CharField(max_length=20, choices=JobType.choices, blank=True, default='')
    location = models.CharField(max_length=160, blank=True, default='')
    salary_range = models.CharField(max_length=120, blank=True, default='')
    experience_required = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=100, choices=STATUS_CHOICES, default='active')
    date = models.DateTimeField(default=timezone.now)
    company = models.ForeignKey(
        'CompanyProfile',
        on_delete=models.SET_NULL,
        related_name='vacancies',
        null=True,
        blank=True,
    )
    admin = models.ForeignKey(User, null=True, on_delete=models.CASCADE, related_name='admin', limit_choices_to={'profile__role': 'admin'})

    def __str__(self):
        return f"Vacancy: {self.role} - {self.status}"


def normalize_skill_key(value: str) -> str:
    return slugify(value or '').strip('-')


class Skill(models.Model):
    name = models.CharField(max_length=120)
    key = models.SlugField(max_length=120, unique=True)
    category = models.CharField(max_length=80, blank=True, default='')
    aliases = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['key']),
            models.Index(fields=['name']),
            models.Index(fields=['is_active']),
            models.Index(fields=['category']),
        ]

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = normalize_skill_key(self.name)
        else:
            self.key = normalize_skill_key(self.key)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SkillQuestion(models.Model):
    class Difficulty(models.TextChoices):
        BASIC = 'basic', 'Basic'
        INTERMEDIATE = 'intermediate', 'Intermediate'
        ADVANCED = 'advanced', 'Advanced'

    class QuestionType(models.TextChoices):
        CONCEPT = 'concept', 'Concept'
        SCENARIO = 'scenario', 'Scenario'
        DEBUGGING = 'debugging', 'Debugging'
        PRACTICAL = 'practical', 'Practical'
        BEHAVIORAL = 'behavioral', 'Behavioral'
        FOLLOW_UP = 'follow_up', 'Follow Up'

    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        OPENAI = 'openai', 'OpenAI'
        IMPORTED = 'imported', 'Imported'

    class QualityStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        NEEDS_REVIEW = 'needs_review', 'Needs Review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='verbal_questions')
    question_text = models.TextField()
    question_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices)
    question_type = models.CharField(max_length=30, choices=QuestionType.choices)
    family_key = models.CharField(max_length=120, db_index=True)
    coverage_area = models.CharField(max_length=80, blank=True, default='', db_index=True)
    expected_signal = models.TextField(blank=True, default='')
    ideal_answer_points = models.JSONField(default=list, blank=True)
    evaluation_rubric = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    quality_status = models.CharField(max_length=20, choices=QualityStatus.choices, default=QualityStatus.APPROVED, db_index=True)
    quality_score = models.FloatField(default=0)
    jd_relevance_score = models.FloatField(default=0)
    quality_notes = models.JSONField(default=dict, blank=True)
    generation_batch_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['skill__name', 'difficulty', 'id']
        constraints = [
            models.UniqueConstraint(fields=['skill', 'question_hash'], condition=~models.Q(question_hash=''), name='unique_skill_question_hash'),
        ]
        indexes = [
            models.Index(fields=['skill', 'difficulty', 'is_active']),
            models.Index(fields=['skill', 'family_key']),
            models.Index(fields=['skill', 'coverage_area']),
            models.Index(fields=['skill', 'quality_status', 'is_active']),
            models.Index(fields=['question_type']),
            models.Index(fields=['source']),
        ]

    def __str__(self):
        preview = ' '.join((self.question_text or '').split())[:80]
        return f'{self.skill.name}: {preview}'


class CodingQuestion(models.Model):
    class Difficulty(models.TextChoices):
        EASY = 'easy', 'Easy'
        MEDIUM = 'medium', 'Medium'
        HARD = 'hard', 'Hard'

    class QuestionType(models.TextChoices):
        ALGORITHM = 'algorithm', 'Algorithm'
        DATA_STRUCTURE = 'data_structure', 'Data Structure'
        DEBUGGING = 'debugging', 'Debugging'
        SQL_QUERY = 'sql_query', 'SQL Query'
        FRAMEWORK_TASK = 'framework_task', 'Framework Task'
        API_DESIGN = 'api_design', 'API Design'
        SYSTEM_DESIGN = 'system_design', 'System Design'

    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        OPENAI = 'openai', 'OpenAI'
        IMPORTED = 'imported', 'Imported'

    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='coding_questions')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    prompt = models.TextField()
    prompt_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices)
    question_type = models.CharField(max_length=30, choices=QuestionType.choices)
    topic = models.CharField(max_length=120, blank=True, default='')
    family_key = models.CharField(max_length=120, db_index=True)
    input_format = models.TextField(blank=True, default='')
    output_format = models.TextField(blank=True, default='')
    constraints = models.TextField(blank=True, default='')
    starter_code = models.JSONField(default=dict, blank=True)
    test_cases = models.JSONField(default=list, blank=True)
    hidden_test_cases = models.JSONField(default=list, blank=True)
    expected_solution = models.TextField(blank=True, default='')
    explanation = models.TextField(blank=True, default='')
    time_limit_ms = models.PositiveIntegerField(default=2000)
    memory_limit_mb = models.PositiveIntegerField(default=256)
    tags = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['skill__name', 'difficulty', 'title']
        constraints = [
            models.UniqueConstraint(fields=['skill', 'prompt_hash'], condition=~models.Q(prompt_hash=''), name='unique_skill_coding_prompt_hash'),
        ]
        indexes = [
            models.Index(fields=['skill', 'difficulty', 'is_active']),
            models.Index(fields=['skill', 'family_key']),
            models.Index(fields=['question_type']),
            models.Index(fields=['slug']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = normalize_skill_key(self.title)
        else:
            self.slug = normalize_skill_key(self.slug)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class JobInterviewBlueprint(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        GENERATING = 'generating', 'Generating'
        READY = 'ready', 'Ready'
        PARTIAL = 'partial', 'Partial'
        FAILED = 'failed', 'Failed'

    class GenerationSource(models.TextChoices):
        OPENAI = 'openai', 'OpenAI'
        MANUAL = 'manual', 'Manual'
        SYSTEM = 'system', 'System'

    job = models.OneToOneField(Vacancies, on_delete=models.CASCADE, related_name='interview_blueprint')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    role_title = models.CharField(max_length=255, blank=True, default='')
    experience_level = models.CharField(max_length=80, blank=True, default='')
    raw_extracted_skills = models.JSONField(default=list, blank=True)
    selected_skills_snapshot = models.JSONField(default=list, blank=True)
    blueprint_plan = models.JSONField(default=dict, blank=True)
    generation_source = models.CharField(max_length=20, choices=GenerationSource.choices, default=GenerationSource.OPENAI)
    model_name = models.CharField(max_length=120, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    version = models.PositiveIntegerField(default=1)
    minimum_ready = models.BooleanField(default=False)
    fully_ready = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['job']),
            models.Index(fields=['status']),
            models.Index(fields=['minimum_ready']),
            models.Index(fields=['fully_ready']),
        ]

    def __str__(self):
        return f'{self.job} - {self.status}'


class JobInterviewSkill(models.Model):
    class Source(models.TextChoices):
        OPENAI = 'openai', 'OpenAI'
        MANUAL = 'manual', 'Manual'
        SYSTEM = 'system', 'System'

    class SkillRole(models.TextChoices):
        PRIMARY = 'primary', 'Primary'
        PRIMARY_CANDIDATE = 'primary_candidate', 'Primary Candidate'
        SUB_SKILL = 'sub_skill', 'Sub Skill'
        OPTIONAL = 'optional', 'Optional'

    blueprint = models.ForeignKey(JobInterviewBlueprint, on_delete=models.CASCADE, related_name='planned_skills')
    job = models.ForeignKey(Vacancies, on_delete=models.CASCADE, related_name='interview_skills')
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name='job_plans')
    skill_role = models.CharField(max_length=30, choices=SkillRole.choices, default=SkillRole.SUB_SKILL, db_index=True)
    priority = models.PositiveIntegerField(default=1)
    questions_to_ask = models.PositiveIntegerField(default=4)
    coding_questions_to_ask = models.PositiveIntegerField(default=0)
    difficulty_mix = models.JSONField(default=dict, blank=True)
    coding_difficulty_mix = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.OPENAI)
    confidence = models.FloatField(null=True, blank=True)
    is_required = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['blueprint', 'priority', 'id']
        constraints = [
            models.UniqueConstraint(fields=['blueprint', 'skill'], name='unique_blueprint_skill_plan'),
        ]
        indexes = [
            models.Index(fields=['job', 'priority']),
            models.Index(fields=['blueprint', 'priority']),
            models.Index(fields=['skill', 'is_active']),
            models.Index(fields=['blueprint', 'skill_role']),
        ]

    def __str__(self):
        return f'{self.job} - {self.skill}'


class QuestionGenerationJob(models.Model):
    class TaskType(models.TextChoices):
        JD_SKILL_MAPPING = 'jd_skill_mapping', 'JD Skill Mapping'
        QUESTION_GENERATION = 'question_generation', 'Question Generation'
        CODING_GENERATION = 'coding_generation', 'Coding Generation'
        REPAIR = 'repair', 'Repair'

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    job = models.ForeignKey(Vacancies, on_delete=models.CASCADE, null=True, blank=True, related_name='question_generation_jobs')
    blueprint = models.ForeignKey(JobInterviewBlueprint, on_delete=models.SET_NULL, null=True, blank=True, related_name='generation_jobs')
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, null=True, blank=True, related_name='generation_jobs')
    task_type = models.CharField(max_length=40, choices=TaskType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['job', 'status']),
            models.Index(fields=['skill', 'task_type', 'status']),
            models.Index(fields=['task_type', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.task_type} for job {self.job_id or "-"} ({self.status})'


class AptitudeSection(models.Model):
    class Category(models.TextChoices):
        APTITUDE = 'aptitude', 'Aptitude'
        COMMUNICATION = 'communication', 'Communication'
        TECHNICAL = 'technical', 'Technical'
        REASONING = 'reasoning', 'Reasoning'

    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.APTITUDE, db_index=True)
    default_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['default_order', 'name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['default_order']),
        ]

    def __str__(self):
        return self.name


class AptitudeQuestionBank(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE_CHOICE = 'single_choice', 'Single Choice'
        MULTIPLE_CHOICE = 'multiple_choice', 'Multiple Choice'
        TRUE_FALSE = 'true_false', 'True/False'
        NUMERIC = 'numeric', 'Numeric Answer'
        TEXT_INPUT = 'text_input', 'Text Input'
        FILL_BLANK = 'fill_blank', 'Fill in the Blank'
        IMAGE_CHOICE = 'image_choice', 'Image Choice'
        MATCHING = 'matching', 'Matching'
        ORDERING = 'ordering', 'Ordering'

    class Difficulty(models.TextChoices):
        EASY = 'easy', 'Easy'
        MEDIUM = 'medium', 'Medium'
        HARD = 'hard', 'Hard'

    class QualityStatus(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        APPROVED = 'approved', 'Approved'
        NEEDS_REVIEW = 'needs_review', 'Needs Review'
        ARCHIVED = 'archived', 'Archived'

    section = models.ForeignKey(AptitudeSection, on_delete=models.PROTECT, related_name='question_bank')
    question_type = models.CharField(max_length=30, choices=QuestionType.choices, default=QuestionType.SINGLE_CHOICE)
    role_family = models.CharField(max_length=120, blank=True, default='', db_index=True)
    skill_tag = models.CharField(max_length=120, blank=True, default='', db_index=True)
    topic_tag = models.CharField(max_length=120, blank=True, default='', db_index=True)
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices, default=Difficulty.MEDIUM, db_index=True)
    question_text = models.TextField()
    question_html = models.TextField(blank=True, default='')
    question_media = models.JSONField(default=list, blank=True)
    options = models.JSONField(default=list, blank=True)
    answer_schema = models.JSONField(default=dict, blank=True)
    scoring_schema = models.JSONField(default=dict, blank=True)
    marks = models.DecimalField(max_digits=6, decimal_places=2, default=2)
    negative_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    explanation = models.TextField(blank=True, default='')
    quality_status = models.CharField(
        max_length=30,
        choices=QualityStatus.choices,
        default=QualityStatus.DRAFT,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='created_aptitude_questions',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['section__default_order', 'difficulty', 'id']
        indexes = [
            models.Index(fields=['section', 'difficulty', 'is_active']),
            models.Index(fields=['section', 'quality_status', 'is_active']),
            models.Index(fields=['role_family', 'skill_tag']),
            models.Index(fields=['skill_tag', 'topic_tag']),
            models.Index(fields=['difficulty', 'quality_status']),
            models.Index(fields=['question_type']),
        ]

    def __str__(self):
        preview = ' '.join((self.question_text or '').split())[:80]
        return f'{self.section.name}: {preview}'


class AptitudeQuestionGenerationJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    class CreatedQualityStatus(models.TextChoices):
        DRAFT = AptitudeQuestionBank.QualityStatus.DRAFT, 'Draft'
        APPROVED = AptitudeQuestionBank.QualityStatus.APPROVED, 'Approved'
        NEEDS_REVIEW = AptitudeQuestionBank.QualityStatus.NEEDS_REVIEW, 'Needs Review'

    section = models.ForeignKey(AptitudeSection, on_delete=models.PROTECT, related_name='generation_jobs')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    role_family = models.CharField(max_length=120, blank=True, default='', db_index=True)
    skill_tag = models.CharField(max_length=120, blank=True, default='', db_index=True)
    topic_tag = models.CharField(max_length=120, blank=True, default='', db_index=True)
    target_count = models.PositiveIntegerField(default=500)
    batch_size = models.PositiveIntegerField(default=20)
    generated_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    difficulty_mix = models.JSONField(default=dict, blank=True)
    question_types = models.JSONField(default=list, blank=True)
    quality_status_for_created = models.CharField(
        max_length=30,
        choices=CreatedQualityStatus.choices,
        default=CreatedQualityStatus.NEEDS_REVIEW,
    )
    prompt_version = models.CharField(max_length=40, default='aptitude_v1')
    provider = models.CharField(max_length=40, default='openai')
    model_name = models.CharField(max_length=100, blank=True, default='')
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='created_aptitude_generation_jobs',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['status', 'updated_at'], name='apt_gen_status_updated_idx'),
            models.Index(fields=['section', 'status'], name='apt_gen_section_status_idx'),
            models.Index(fields=['role_family', 'skill_tag'], name='apt_gen_role_skill_idx'),
            models.Index(fields=['created_at'], name='apt_gen_created_idx'),
        ]

    def __str__(self):
        return f'{self.section.code} aptitude generation ({self.status})'


class AptitudeTestTemplate(models.Model):
    class RoleType(models.TextChoices):
        GENERAL = 'general', 'General'
        TECHNICAL = 'technical', 'Technical'
        MIXED = 'mixed', 'Mixed'

    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default='')
    role_type = models.CharField(max_length=20, choices=RoleType.choices, default=RoleType.GENERAL, db_index=True)
    role_family = models.CharField(max_length=120, blank=True, default='', db_index=True)
    duration_minutes = models.PositiveIntegerField(default=60)
    total_questions = models.PositiveIntegerField(default=50)
    marks_per_question = models.DecimalField(max_digits=6, decimal_places=2, default=2)
    total_marks = models.DecimalField(max_digits=7, decimal_places=2, default=100)
    passing_score_percent = models.DecimalField(max_digits=5, decimal_places=2, default=70)
    negative_marking_enabled = models.BooleanField(default=False)
    randomize_questions = models.BooleanField(default=True)
    randomize_options = models.BooleanField(default=True)
    allow_retake = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='created_aptitude_templates',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title', 'id']
        indexes = [
            models.Index(fields=['role_type', 'is_active']),
            models.Index(fields=['role_family', 'is_active']),
        ]

    def __str__(self):
        return self.title


class AptitudeTestTemplateSection(models.Model):
    template = models.ForeignKey(AptitudeTestTemplate, on_delete=models.CASCADE, related_name='sections')
    section = models.ForeignKey(AptitudeSection, on_delete=models.PROTECT, related_name='template_sections')
    question_count = models.PositiveIntegerField(default=0)
    difficulty_mix = models.JSONField(default=dict, blank=True)
    marks_per_question = models.DecimalField(max_digits=6, decimal_places=2, default=2)
    order_index = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)

    class Meta:
        ordering = ['template', 'order_index', 'id']
        constraints = [
            models.UniqueConstraint(fields=['template', 'section'], name='unique_aptitude_template_section'),
        ]
        indexes = [
            models.Index(fields=['template', 'order_index']),
            models.Index(fields=['section', 'is_required']),
        ]

    def __str__(self):
        return f'{self.template.title} - {self.section.name}'


class AptitudeTestAssignment(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = 'assigned', 'Assigned'
        IN_PROGRESS = 'in_progress', 'In Progress'
        SUBMITTED = 'submitted', 'Submitted'
        EXPIRED = 'expired', 'Expired'
        CANCELLED = 'cancelled', 'Cancelled'

    class RoleType(models.TextChoices):
        GENERAL = 'general', 'General'
        TECHNICAL = 'technical', 'Technical'
        MIXED = 'mixed', 'Mixed'

    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='aptitude_test_assignments',
        limit_choices_to={'profile__role': 'candidate'},
        null=True,
        blank=True,
    )
    vacancy = models.ForeignKey(
        Vacancies,
        on_delete=models.SET_NULL,
        related_name='aptitude_test_assignments',
        null=True,
        blank=True,
    )
    interview = models.ForeignKey(
        Interview,
        on_delete=models.SET_NULL,
        related_name='aptitude_test_assignments',
        null=True,
        blank=True,
    )
    template = models.ForeignKey(
        AptitudeTestTemplate,
        on_delete=models.SET_NULL,
        related_name='assignments',
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=180, default='Aptitude Test')
    public_token = models.CharField(max_length=64, unique=True, default=generate_aptitude_public_token, db_index=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ASSIGNED, db_index=True)
    role_type = models.CharField(max_length=20, choices=RoleType.choices, default=RoleType.GENERAL, db_index=True)
    section_config = models.JSONField(default=dict, blank=True)
    duration_minutes = models.PositiveIntegerField(default=60)
    total_questions = models.PositiveIntegerField(default=50)
    marks_per_question = models.DecimalField(max_digits=6, decimal_places=2, default=2)
    total_marks = models.DecimalField(max_digits=7, decimal_places=2, default=100)
    passing_score_percent = models.DecimalField(max_digits=5, decimal_places=2, default=70)
    negative_marking_enabled = models.BooleanField(default=False)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    early_exit = models.BooleanField(default=False)
    early_exit_reason = models.CharField(max_length=80, blank=True, default='')
    allow_retake = models.BooleanField(default=False)
    attempt_number = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='created_aptitude_assignments',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['public_token']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['candidate', 'created_at']),
            models.Index(fields=['vacancy', 'status']),
            models.Index(fields=['interview', 'status']),
        ]

    def __str__(self):
        candidate = self.candidate.username if self.candidate else 'unassigned'
        return f'{self.title} for {candidate} ({self.status})'


class AptitudeTestQuestion(models.Model):
    assignment = models.ForeignKey(AptitudeTestAssignment, on_delete=models.CASCADE, related_name='questions')
    source_question = models.ForeignKey(
        AptitudeQuestionBank,
        on_delete=models.SET_NULL,
        related_name='assignment_snapshots',
        null=True,
        blank=True,
    )
    section = models.ForeignKey(
        AptitudeSection,
        on_delete=models.SET_NULL,
        related_name='assignment_questions',
        null=True,
        blank=True,
    )
    question_type = models.CharField(
        max_length=30,
        choices=AptitudeQuestionBank.QuestionType.choices,
        default=AptitudeQuestionBank.QuestionType.SINGLE_CHOICE,
    )
    role_family = models.CharField(max_length=120, blank=True, default='')
    skill_tag = models.CharField(max_length=120, blank=True, default='')
    topic_tag = models.CharField(max_length=120, blank=True, default='')
    difficulty = models.CharField(
        max_length=20,
        choices=AptitudeQuestionBank.Difficulty.choices,
        default=AptitudeQuestionBank.Difficulty.MEDIUM,
    )
    question_text = models.TextField()
    question_html = models.TextField(blank=True, default='')
    question_media = models.JSONField(default=list, blank=True)
    options = models.JSONField(default=list, blank=True)
    answer_schema = models.JSONField(default=dict, blank=True)
    scoring_schema = models.JSONField(default=dict, blank=True)
    marks = models.DecimalField(max_digits=6, decimal_places=2, default=2)
    negative_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['assignment', 'order_index', 'id']
        indexes = [
            models.Index(fields=['assignment', 'order_index']),
            models.Index(fields=['assignment', 'section']),
            models.Index(fields=['section', 'order_index']),
        ]

    def __str__(self):
        return f'Question {self.order_index or self.id} for assignment {self.assignment_id}'


class AptitudeAnswer(models.Model):
    assignment = models.ForeignKey(AptitudeTestAssignment, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(AptitudeTestQuestion, on_delete=models.CASCADE, related_name='answers')
    answer_payload = models.JSONField(default=dict, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    marks_awarded = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    answered_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['assignment', 'question__order_index', 'id']
        constraints = [
            models.UniqueConstraint(fields=['assignment', 'question'], name='unique_aptitude_assignment_answer'),
        ]
        indexes = [
            models.Index(fields=['assignment', 'question']),
            models.Index(fields=['assignment', 'is_correct']),
        ]

    def __str__(self):
        return f'Answer for assignment {self.assignment_id}, question {self.question_id}'


class AptitudeTestResult(models.Model):
    assignment = models.OneToOneField(AptitudeTestAssignment, on_delete=models.CASCADE, related_name='result')
    total_questions = models.PositiveIntegerField(default=50)
    attempted_questions = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    wrong_answers = models.PositiveIntegerField(default=0)
    skipped_questions = models.PositiveIntegerField(default=0)
    total_marks = models.DecimalField(max_digits=7, decimal_places=2, default=100)
    marks_obtained = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    score_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    passed = models.BooleanField(default=False, db_index=True)
    problem_solving_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    communication_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    technical_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    section_breakdown = models.JSONField(default=dict, blank=True)
    skill_breakdown = models.JSONField(default=dict, blank=True)
    integrity_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['passed', 'updated_at']),
            models.Index(fields=['score_percent']),
        ]

    def __str__(self):
        return f'Result for aptitude assignment {self.assignment_id} ({self.score_percent}%)'


class AptitudeIntegrityEvent(models.Model):
    class EventType(models.TextChoices):
        TAB_SWITCH = 'tab_switch', 'Tab Switch'
        WINDOW_BLUR = 'window_blur', 'Window Blur'
        FULLSCREEN_EXIT = 'fullscreen_exit', 'Fullscreen Exit'
        COPY_ATTEMPT = 'copy_attempt', 'Copy Attempt'
        PASTE_ATTEMPT = 'paste_attempt', 'Paste Attempt'
        RIGHT_CLICK = 'right_click', 'Right Click'
        REFRESH = 'refresh', 'Refresh'
        DEVTOOLS_SUSPECTED = 'devtools_suspected', 'Devtools Suspected'
        NETWORK_RECONNECT = 'network_reconnect', 'Network Reconnect'
        CAMERA_MISSING = 'camera_missing', 'Camera Missing'
        CAMERA_DISABLED = 'camera_disabled', 'Camera Disabled'
        MICROPHONE_DISABLED = 'microphone_disabled', 'Microphone Disabled'
        FACE_MISSING = 'face_missing', 'Face Missing'
        MULTIPLE_FACE_SUSPECTED = 'multiple_face_suspected', 'Multiple Face Suspected'
        GAZE_LOST = 'gaze_lost', 'Gaze Lost'
        MULTIPLE_VOICE_SUSPECTED = 'multiple_voice_suspected', 'Multiple Voice Suspected'
        VOICE_ACTIVITY_SUSPICIOUS = 'voice_activity_suspicious', 'Voice Activity Suspicious'
        EXTERNAL_DEVICE_SUSPECTED = 'external_device_suspected', 'External Device Suspected'

    assignment = models.ForeignKey(AptitudeTestAssignment, on_delete=models.CASCADE, related_name='integrity_events')
    event_type = models.CharField(max_length=40, choices=EventType.choices, db_index=True)
    event_payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-occurred_at', '-id']
        indexes = [
            models.Index(fields=['assignment', 'event_type', 'occurred_at']),
            models.Index(fields=['assignment', 'occurred_at']),
        ]

    def __str__(self):
        return f'{self.event_type} for aptitude assignment {self.assignment_id}'


class CandidateVacancyApplication(models.Model):
    class Status(models.TextChoices):
        PENDING_REVIEW = 'pending_review', 'Pending Review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        WITHDRAWN = 'withdrawn', 'Withdrawn'
        NOT_INTERESTED = 'not_interested', 'Not Interested'

    class PipelineSource(models.TextChoices):
        SELF_APPLIED = 'self_applied', 'Self Applied'
        DIRECT = 'direct', 'Direct'
        REFERRAL = 'referral', 'Referral'

    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='vacancy_applications',
        limit_choices_to={'profile__role': 'candidate'},
    )
    vacancy = models.ForeignKey(
        Vacancies,
        on_delete=models.CASCADE,
        related_name='candidate_applications',
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING_REVIEW)
    source = models.CharField(max_length=30, blank=True, default='candidate_dashboard')
    # Canonical origin used for source/origin analytics. Prefer setting this at
    # application creation time so reporting does not rely on heuristic inference.
    pipeline_source = models.CharField(
        max_length=20,
        choices=PipelineSource.choices,
        blank=True,
        default='',
        db_index=True,
    )
    notes = models.TextField(blank=True, default='')
    recruiter_notification = models.JSONField(default=dict, blank=True)
    # Canonical start of the hiring cycle for time-to-hire analytics.
    # Keep this populated as early as possible for every candidate-vacancy pair.
    hiring_started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-applied_at']
        constraints = [
            models.UniqueConstraint(fields=['candidate', 'vacancy'], name='unique_candidate_vacancy_application'),
        ]

    def __str__(self):
        return f"{self.candidate.username} -> {self.vacancy.role} ({self.status})"


class CandidateSavedVacancy(models.Model):
    candidate = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='saved_vacancies',
        limit_choices_to={'profile__role': 'candidate'},
    )
    vacancy = models.ForeignKey(
        Vacancies,
        on_delete=models.CASCADE,
        related_name='saved_by_candidates',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['candidate', 'vacancy'], name='unique_candidate_saved_vacancy'),
        ]

    def __str__(self):
        return f"{self.candidate.username} saved {self.vacancy.role}"


class CandidatePublicResume(models.Model):
    candidate = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='public_resume',
        limit_choices_to={'profile__role': 'candidate'},
    )
    short_code = models.CharField(max_length=16, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_shared_at = models.DateTimeField(null=True, blank=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    download_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Public resume for {self.candidate.username} ({self.short_code})"


class InterviewFeedback(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='litio_interview_feedback',
        null=True,
        blank=True,
    )
    room_name = models.CharField(max_length=120, db_index=True)
    interview_token = models.CharField(max_length=80, blank=True, default='', db_index=True)
    interview_type = models.CharField(max_length=20, blank=True, default='')
    participant_role = models.CharField(max_length=20, blank=True, default='', db_index=True)
    participant_name = models.CharField(max_length=160, blank=True, default='')
    participant_email = models.EmailField(blank=True, default='')
    overall_rating = models.PositiveSmallIntegerField()
    experience_rating = models.PositiveSmallIntegerField()
    audio_video_rating = models.PositiveSmallIntegerField()
    ai_interviewer_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    liked_most = models.TextField(blank=True, default='')
    improvement_suggestions = models.TextField(blank=True, default='')
    summary_credit_notice_shown = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        managed = False
        db_table = 'conference_interviewfeedback'
        ordering = ['-created_at']
        verbose_name = 'Interview Feedback'
        verbose_name_plural = 'Interview Feedback'

    def __str__(self):
        return f"Feedback<{self.room_name}:{self.participant_role}:{self.overall_rating}>"
