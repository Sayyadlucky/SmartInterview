from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0003_align_interview_statuses'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OtpRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(db_index=True, max_length=20)),
                ('purpose', models.CharField(db_index=True, max_length=64)),
                ('provider', models.CharField(default='msg91_otp', max_length=40)),
                ('provider_request_id', models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ('status', models.CharField(choices=[('requested', 'Requested'), ('verified', 'Verified'), ('failed', 'Failed'), ('expired', 'Expired'), ('rate_limited', 'Rate Limited')], default='requested', max_length=20)),
                ('attempt_count', models.PositiveIntegerField(default=0)),
                ('max_attempts', models.PositiveIntegerField(default=5)),
                ('otp_hash', models.CharField(blank=True, max_length=255, null=True)),
                ('expires_at', models.DateTimeField()),
                ('next_resend_at', models.DateTimeField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='otp_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='UserNotificationPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('whatsapp_opt_in', models.BooleanField(default=True)),
                ('sms_opt_in', models.BooleanField(default=True)),
                ('voice_opt_in', models.BooleanField(default=True)),
                ('phone_verified_at', models.DateTimeField(blank=True, null=True)),
                ('preferred_language', models.CharField(default='en', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='notification_preference', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='notification',
            name='event_type',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='notification',
            name='final_channel',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='notification',
            name='idempotency_key',
            field=models.CharField(blank=True, max_length=128, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='metadata',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='notification',
            name='payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='notification',
            name='severity',
            field=models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('critical', 'Critical')], default='low', max_length=20),
        ),
        migrations.AddField(
            model_name='notification',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed'), ('partial', 'Partial'), ('delivered', 'Delivered'), ('read', 'Read'), ('escalated', 'Escalated')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='notification',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='notification',
            name='message',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='notification',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notifications', to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name='NotificationAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('channel', models.CharField(choices=[('whatsapp', 'WhatsApp'), ('sms', 'SMS'), ('voice', 'Voice')], max_length=20)),
                ('provider', models.CharField(max_length=40)),
                ('provider_message_id', models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('sent', 'Sent'), ('delivered', 'Delivered'), ('read', 'Read'), ('failed', 'Failed'), ('callback_received', 'Callback Received')], default='queued', max_length=30)),
                ('response_payload', models.JSONField(blank=True, default=dict)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('attempted_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('notification', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempts', to='smartInterviewApp.notification')),
            ],
            options={
                'ordering': ['attempted_at'],
            },
        ),
    ]
