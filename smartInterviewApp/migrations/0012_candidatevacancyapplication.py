from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0011_candidate_insight_snapshot'),
    ]

    operations = [
        migrations.CreateModel(
            name='CandidateVacancyApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending_review', 'Pending Review'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('withdrawn', 'Withdrawn')], default='pending_review', max_length=30)),
                ('source', models.CharField(blank=True, default='candidate_dashboard', max_length=30)),
                ('notes', models.TextField(blank=True, default='')),
                ('recruiter_notification', models.JSONField(blank=True, default=dict)),
                ('applied_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.ForeignKey(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='vacancy_applications', to=settings.AUTH_USER_MODEL)),
                ('vacancy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='candidate_applications', to='smartInterviewApp.vacancies')),
            ],
            options={
                'ordering': ['-applied_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='candidatevacancyapplication',
            constraint=models.UniqueConstraint(fields=('candidate', 'vacancy'), name='unique_candidate_vacancy_application'),
        ),
    ]
