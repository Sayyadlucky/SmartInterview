import secrets

from django.db import migrations, models


def populate_litio_interview_tokens(apps, schema_editor):
    Interview = apps.get_model('smartInterviewApp', 'Interview')
    existing_tokens = set(
        Interview.objects.exclude(litio_interview_token__isnull=True)
        .exclude(litio_interview_token='')
        .values_list('litio_interview_token', flat=True)
    )

    for interview in Interview.objects.filter(models.Q(litio_interview_token__isnull=True) | models.Q(litio_interview_token='')).iterator():
        token = secrets.token_urlsafe(24)
        while token in existing_tokens:
            token = secrets.token_urlsafe(24)
        existing_tokens.add(token)
        interview.litio_interview_token = token
        interview.save(update_fields=['litio_interview_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0034_interview_offer_statuses'),
    ]

    operations = [
        migrations.AddField(
            model_name='interview',
            name='litio_interview_token',
            field=models.CharField(blank=True, db_index=True, max_length=80, null=True, unique=True),
        ),
        migrations.RunPython(populate_litio_interview_tokens, migrations.RunPython.noop),
    ]
