from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from smartInterviewApp.pgvector_compat import HnswIndex, VectorField


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

    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not Started'
        PROCESSING = 'processing', 'Processing'
        XML_VERIFIED = 'xml_verified', 'XML Verified'
        DOCUMENT_MATCHED = 'document_matched', 'Document Matched'
        DOCUMENT_MISMATCH = 'document_mismatch', 'Document Mismatch'
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
