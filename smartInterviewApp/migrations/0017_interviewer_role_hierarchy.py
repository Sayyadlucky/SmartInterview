from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0016_candidatesavedvacancy'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('candidate', 'Candidate'),
                    ('recruiter', 'Recruiter'),
                    ('interviewer', 'Interviewer'),
                    ('admin', 'Admin'),
                ],
                default='candidate',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='recruiter',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'profile__role': 'recruiter'},
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='assigned_interviewers',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='interview',
            name='interviewer',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'profile__role': 'interviewer'},
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='interviewer_interviews',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
