from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0037_normalize_litio_interview_tokens'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InterviewCallSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('exotel_call_sid', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('status', models.CharField(choices=[('dialing_agent', 'Dialing Agent'), ('connecting_candidate', 'Connecting Candidate'), ('in_progress', 'In Progress'), ('completed', 'Completed'), ('failed', 'Failed'), ('busy', 'Busy'), ('no_answer', 'No Answer'), ('cancelled', 'Cancelled'), ('disconnected', 'Disconnected')], db_index=True, default='dialing_agent', max_length=30)),
                ('caller_phone', models.CharField(blank=True, default='', max_length=20)),
                ('candidate_phone', models.CharField(blank=True, default='', max_length=20)),
                ('billing_started_at', models.DateTimeField(blank=True, null=True)),
                ('candidate_connected_at', models.DateTimeField(blank=True, null=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('billable_seconds', models.PositiveIntegerField(default=0)),
                ('connected_seconds', models.PositiveIntegerField(default=0)),
                ('disconnect_requested_at', models.DateTimeField(blank=True, null=True)),
                ('provider_response', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('initiated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='initiated_call_sessions', to=settings.AUTH_USER_MODEL)),
                ('interview', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='call_sessions', to='smartInterviewApp.interview')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['interview', 'status'], name='smartInterv_intervie_0e71f0_idx'),
                    models.Index(fields=['initiated_by', 'created_at'], name='smartInterv_initiat_8af96e_idx'),
                    models.Index(fields=['exotel_call_sid'], name='smartInterv_exotel__50f7fd_idx'),
                ],
            },
        ),
    ]
