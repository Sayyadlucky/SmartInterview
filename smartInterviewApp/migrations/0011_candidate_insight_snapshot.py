from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0010_candidate_identity_verification'),
    ]

    operations = [
        migrations.CreateModel(
            name='CandidateInsightSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('not_started', 'Not Started'), ('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='not_started', max_length=20)),
                ('source_signature', models.CharField(blank=True, default='', max_length=128)),
                ('generated_for_role', models.CharField(blank=True, default='', max_length=255)),
                ('generated_for_title', models.CharField(blank=True, default='', max_length=255)),
                ('executive_summary', models.TextField(blank=True, default='')),
                ('resume_score', models.PositiveIntegerField(blank=True, null=True)),
                ('role_fit_score', models.PositiveIntegerField(blank=True, null=True)),
                ('market_demand_score', models.PositiveIntegerField(blank=True, null=True)),
                ('current_skills_impact_score', models.PositiveIntegerField(blank=True, null=True)),
                ('market_demand_label', models.CharField(blank=True, default='', max_length=80)),
                ('salary_range', models.CharField(blank=True, default='', max_length=120)),
                ('salary_trend_summary', models.TextField(blank=True, default='')),
                ('market_demand_summary', models.TextField(blank=True, default='')),
                ('current_skills_impact_summary', models.TextField(blank=True, default='')),
                ('top_strengths', models.JSONField(blank=True, default=list)),
                ('growth_areas', models.JSONField(blank=True, default=list)),
                ('recommended_skills', models.JSONField(blank=True, default=list)),
                ('recommended_roles', models.JSONField(blank=True, default=list)),
                ('model_name', models.CharField(blank=True, default='', max_length=80)),
                ('error_message', models.TextField(blank=True, default='')),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('requested_at', models.DateTimeField(blank=True, null=True)),
                ('generated_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.OneToOneField(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='insight_snapshot', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
