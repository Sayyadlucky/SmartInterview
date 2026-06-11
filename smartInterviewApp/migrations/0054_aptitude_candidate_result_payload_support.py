from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0053_aptitudetestassignment_scheduled_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='aptitudetestassignment',
            name='early_exit',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='aptitudetestassignment',
            name='early_exit_reason',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AlterField(
            model_name='aptitudeintegrityevent',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('tab_switch', 'Tab Switch'),
                    ('window_blur', 'Window Blur'),
                    ('fullscreen_exit', 'Fullscreen Exit'),
                    ('copy_attempt', 'Copy Attempt'),
                    ('paste_attempt', 'Paste Attempt'),
                    ('right_click', 'Right Click'),
                    ('refresh', 'Refresh'),
                    ('devtools_suspected', 'Devtools Suspected'),
                    ('network_reconnect', 'Network Reconnect'),
                    ('camera_missing', 'Camera Missing'),
                    ('camera_disabled', 'Camera Disabled'),
                    ('microphone_disabled', 'Microphone Disabled'),
                    ('face_missing', 'Face Missing'),
                    ('multiple_face_suspected', 'Multiple Face Suspected'),
                    ('gaze_lost', 'Gaze Lost'),
                    ('multiple_voice_suspected', 'Multiple Voice Suspected'),
                    ('voice_activity_suspicious', 'Voice Activity Suspicious'),
                    ('external_device_suspected', 'External Device Suspected'),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]
