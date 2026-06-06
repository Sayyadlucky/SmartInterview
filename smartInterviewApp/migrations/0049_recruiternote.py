# Generated manually for recruiter workspace notes.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0048_interviewcallsession_notes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RecruiterNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('note', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='authored_recruiter_workspace_notes', to=settings.AUTH_USER_MODEL)),
                ('recruiter', models.ForeignKey(limit_choices_to={'profile__role': 'recruiter'}, on_delete=django.db.models.deletion.CASCADE, related_name='recruiter_workspace_notes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['recruiter', '-created_at'], name='smartIntervi_recrui_0ebce5_idx')],
            },
        ),
    ]
