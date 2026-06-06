# Generated manually for aptitude question generation jobs.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0050_aptitude_assessment_foundation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AptitudeQuestionGenerationJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], db_index=True, default='queued', max_length=20)),
                ('role_family', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('skill_tag', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('topic_tag', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('target_count', models.PositiveIntegerField(default=500)),
                ('batch_size', models.PositiveIntegerField(default=20)),
                ('generated_count', models.PositiveIntegerField(default=0)),
                ('accepted_count', models.PositiveIntegerField(default=0)),
                ('rejected_count', models.PositiveIntegerField(default=0)),
                ('difficulty_mix', models.JSONField(blank=True, default=dict)),
                ('question_types', models.JSONField(blank=True, default=list)),
                ('quality_status_for_created', models.CharField(choices=[('draft', 'Draft'), ('approved', 'Approved'), ('needs_review', 'Needs Review')], default='needs_review', max_length=30)),
                ('prompt_version', models.CharField(default='aptitude_v1', max_length=40)),
                ('provider', models.CharField(default='openai', max_length=40)),
                ('model_name', models.CharField(blank=True, default='', max_length=100)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('max_attempts', models.PositiveIntegerField(default=3)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('result', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True, default='')),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_aptitude_generation_jobs', to=settings.AUTH_USER_MODEL)),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='generation_jobs', to='smartInterviewApp.aptitudesection')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['status', 'updated_at'], name='apt_gen_status_updated_idx'),
                    models.Index(fields=['section', 'status'], name='apt_gen_section_status_idx'),
                    models.Index(fields=['role_family', 'skill_tag'], name='apt_gen_role_skill_idx'),
                    models.Index(fields=['created_at'], name='apt_gen_created_idx'),
                ],
            },
        ),
    ]
