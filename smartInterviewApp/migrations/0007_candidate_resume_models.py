from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0006_userprofile_resume_file'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CandidateResume',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_file', models.CharField(blank=True, default='', max_length=500)),
                ('original_filename', models.CharField(blank=True, default='', max_length=255)),
                ('file_size', models.PositiveIntegerField(default=0)),
                ('mime_type', models.CharField(blank=True, default='', max_length=120)),
                ('parser_provider', models.CharField(blank=True, default='heuristic', max_length=80)),
                ('parser_version', models.CharField(blank=True, default='v1', max_length=40)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('error_message', models.TextField(blank=True, default='')),
                ('is_active', models.BooleanField(default=True)),
                ('raw_text', models.TextField(blank=True, default='')),
                ('structured_data', models.JSONField(blank=True, default=dict)),
                ('candidate_type', models.CharField(blank=True, default='', max_length=30)),
                ('headline', models.CharField(blank=True, default='', max_length=255)),
                ('summary', models.TextField(blank=True, default='')),
                ('email', models.EmailField(blank=True, default='', max_length=254)),
                ('phone', models.CharField(blank=True, default='', max_length=20)),
                ('location', models.CharField(blank=True, default='', max_length=255)),
                ('total_experience_years', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('current_title', models.CharField(blank=True, default='', max_length=255)),
                ('current_company', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('candidate', models.ForeignKey(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='resumes', to=settings.AUTH_USER_MODEL)),
                ('interview', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='resume_snapshots', to='smartInterviewApp.interview')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='CandidateResumeSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('section_key', models.CharField(max_length=80)),
                ('title', models.CharField(max_length=120)),
                ('section_type', models.CharField(blank=True, default='', max_length=80)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('content', models.JSONField(blank=True, default=dict)),
                ('raw_text', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('resume', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sections', to='smartInterviewApp.candidateresume')),
            ],
            options={'ordering': ['display_order', 'id']},
        ),
    ]
