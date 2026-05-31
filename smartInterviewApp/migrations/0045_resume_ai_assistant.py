from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0044_skillquestion_quality_metadata'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ResumeAiLearningPattern',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role_family', models.CharField(blank=True, default='general', max_length=80)),
                ('resume_type', models.CharField(blank=True, default='incomplete', max_length=80)),
                ('section_key', models.CharField(max_length=80)),
                ('suggestion_type', models.CharField(max_length=80)),
                ('pattern_type', models.CharField(max_length=80)),
                ('template_text', models.TextField(blank=True, default='')),
                ('keywords_json', models.JSONField(blank=True, default=list)),
                ('rule_payload', models.JSONField(blank=True, default=dict)),
                ('source_count', models.PositiveIntegerField(default=0)),
                ('applied_count', models.PositiveIntegerField(default=0)),
                ('rejected_count', models.PositiveIntegerField(default=0)),
                ('confidence_score', models.FloatField(default=0)),
                ('status', models.CharField(choices=[('candidate', 'Candidate'), ('trusted', 'Trusted'), ('disabled', 'Disabled')], db_index=True, default='candidate', max_length=24)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-confidence_score', '-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='ResumeAiSuggestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('section_key', models.CharField(max_length=80)),
                ('step_key', models.CharField(blank=True, default='', max_length=80)),
                ('role_family', models.CharField(blank=True, default='general', max_length=80)),
                ('resume_type', models.CharField(blank=True, default='incomplete', max_length=80)),
                ('suggestion_type', models.CharField(max_length=80)),
                ('local_suggestion_title', models.CharField(max_length=180)),
                ('local_suggestion_text', models.TextField()),
                ('local_suggestion_payload', models.JSONField(blank=True, default=dict)),
                ('source_context', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('shown', 'Shown'), ('applied', 'Applied'), ('ignored', 'Ignored'), ('not_useful', 'Not Useful'), ('professional_requested', 'Professional Requested'), ('professional_applied', 'Professional Applied')], db_index=True, default='shown', max_length=32)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.ForeignKey(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='resume_ai_suggestions', to=settings.AUTH_USER_MODEL)),
                ('draft', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ai_suggestions', to='smartInterviewApp.candidateresumebuilderdraft')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ResumeAiProfessionalReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('openai_model', models.CharField(blank=True, default='', max_length=100)),
                ('prompt_version', models.CharField(blank=True, default='', max_length=40)),
                ('professional_title', models.CharField(blank=True, default='', max_length=180)),
                ('professional_text', models.TextField(blank=True, default='')),
                ('professional_payload', models.JSONField(blank=True, default=dict)),
                ('user_applied', models.BooleanField(default=False)),
                ('error_code', models.CharField(blank=True, default='', max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('candidate', models.ForeignKey(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='resume_ai_professional_reviews', to=settings.AUTH_USER_MODEL)),
                ('suggestion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='professional_reviews', to='smartInterviewApp.resumeaisuggestion')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ResumeAiFeedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('feedback', models.CharField(choices=[('liked', 'Liked'), ('applied', 'Applied'), ('ignored', 'Ignored'), ('not_useful', 'Not Useful'), ('requested_professional_review', 'Requested Professional Review'), ('applied_professional_review', 'Applied Professional Review')], max_length=48)),
                ('feedback_reason', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('candidate', models.ForeignKey(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='resume_ai_feedback', to=settings.AUTH_USER_MODEL)),
                ('suggestion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feedback_events', to='smartInterviewApp.resumeaisuggestion')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='resumeailearningpattern',
            index=models.Index(fields=['role_family', 'section_key', 'suggestion_type', 'status'], name='rai_pattern_lookup_idx'),
        ),
        migrations.AddIndex(
            model_name='resumeailearningpattern',
            index=models.Index(fields=['confidence_score'], name='rai_pattern_conf_idx'),
        ),
        migrations.AddIndex(
            model_name='resumeaisuggestion',
            index=models.Index(fields=['role_family', 'section_key', 'suggestion_type', 'status'], name='rai_suggest_lookup_idx'),
        ),
        migrations.AddIndex(
            model_name='resumeaisuggestion',
            index=models.Index(fields=['candidate', 'created_at'], name='rai_suggest_cand_idx'),
        ),
        migrations.AddIndex(
            model_name='resumeaiprofessionalreview',
            index=models.Index(fields=['candidate', 'created_at'], name='rai_review_cand_idx'),
        ),
        migrations.AddIndex(
            model_name='resumeaifeedback',
            index=models.Index(fields=['candidate', 'created_at'], name='rai_feedback_cand_idx'),
        ),
    ]
