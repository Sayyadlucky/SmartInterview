from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0035_interview_litio_interview_token'),
    ]

    operations = [
        migrations.CreateModel(
            name='InterviewReminderDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reminder_type', models.CharField(choices=[('one_hour', '60 Minutes Before'), ('thirty_min', '30 Minutes Before'), ('fifteen_min', '15 Minutes Before')], max_length=20)),
                ('channel', models.CharField(choices=[('sms', 'SMS'), ('whatsapp', 'WhatsApp')], max_length=20)),
                ('scheduled_for', models.DateTimeField(db_index=True)),
                ('expected_interview_time', models.DateTimeField(db_index=True)),
                ('cloud_task_name', models.CharField(blank=True, max_length=500, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed'), ('cancelled', 'Cancelled'), ('skipped', 'Skipped')], db_index=True, default='pending', max_length=20)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, default='')),
                ('provider_response', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('interview', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='reminder_deliveries', to='smartInterviewApp.interview')),
            ],
            options={
                'ordering': ['scheduled_for', 'id'],
                'indexes': [
                    models.Index(fields=['status', 'scheduled_for'], name='smartInterv_status_e76320_idx'),
                    models.Index(fields=['interview', 'status'], name='smartInterv_intervi_4ebaf4_idx'),
                    models.Index(fields=['channel', 'status'], name='smartInterv_channel_b2a8fc_idx'),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name='interviewreminderdelivery',
            constraint=models.UniqueConstraint(fields=('interview', 'reminder_type', 'channel', 'expected_interview_time'), name='uniq_interview_reminder_delivery'),
        ),
    ]
