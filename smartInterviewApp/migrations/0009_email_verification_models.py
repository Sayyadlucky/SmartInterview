from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0008_alter_userprofile_profile_picture'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailOtpRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(db_index=True, max_length=254)),
                ('purpose', models.CharField(db_index=True, max_length=64)),
                ('status', models.CharField(choices=[('requested', 'Requested'), ('verified', 'Verified'), ('failed', 'Failed'), ('expired', 'Expired'), ('rate_limited', 'Rate Limited')], default='requested', max_length=20)),
                ('attempt_count', models.PositiveIntegerField(default=0)),
                ('max_attempts', models.PositiveIntegerField(default=5)),
                ('otp_hash', models.CharField(blank=True, max_length=255, null=True)),
                ('expires_at', models.DateTimeField()),
                ('next_resend_at', models.DateTimeField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='email_otp_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='usernotificationpreference',
            name='email_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
