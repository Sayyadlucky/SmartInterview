from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


# Profile table linked to built-in User
class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('candidate', 'Candidate'),
        ('recruiter', 'Recruiter'),
        ('admin', 'Admin'),
    )
    Gender_CHOICES = (
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='candidate')
    profile_picture = models.FileField(upload_to='profile_pictures/', blank=True, null=True)
    resume = models.FileField(upload_to='resumes/', blank=True, null=True)
    notifications_enabled = models.BooleanField(default=True)
    phone = models.CharField(max_length=15,null=True)
    gender = models.CharField(max_length=10, null=True, choices=Gender_CHOICES, default='other')
    hr = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='hr',
        limit_choices_to={'profile__role': 'admin'},
        null=True, blank=True
    )
    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Interview(models.Model):
    STATUS_CHOICES = (
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('shortlisted', 'Shortlisted'),
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
    date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='scheduled')
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
    status = models.CharField(max_length=100, choices=STATUS_CHOICES, default='active')
    date = models.DateTimeField(default=timezone.now)
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
    notes = models.TextField(blank=True, default='')
    recruiter_notification = models.JSONField(default=dict, blank=True)
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
