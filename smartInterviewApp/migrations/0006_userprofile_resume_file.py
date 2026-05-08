from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0005_notification_updated_at_non_null'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='resume',
            field=models.FileField(blank=True, null=True, upload_to='resumes/'),
        ),
    ]
