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
    profile_picture = models.URLField(blank=True, null=True)
    resume = models.URLField(blank=True, null=True)
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
        ('assessment_Pending', 'Assessment Pending'),
        ('rejected', 'Rejected'),
        ('Assesment_Completed', 'Assesment Completed'),
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
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


# Notification table
class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.user.username}"


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
    
    