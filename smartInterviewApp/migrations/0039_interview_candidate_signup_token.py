from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0038_interviewcallsession'),
    ]

    operations = [
        migrations.AddField(
            model_name='interview',
            name='candidate_signup_token',
            field=models.CharField(blank=True, db_index=True, max_length=80, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='interview',
            name='candidate_signup_token_created_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
