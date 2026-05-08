from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0007_candidate_resume_models'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='profile_picture',
            field=models.FileField(blank=True, null=True, upload_to='profile_pictures/'),
        ),
    ]
