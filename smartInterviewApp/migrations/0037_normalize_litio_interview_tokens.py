import secrets

from django.db import migrations


def generate_short_code(existing_tokens: set[str], length: int = 8) -> str:
    alphabet = '23456789abcdefghjkmnpqrstuvwxyz'
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if code not in existing_tokens:
            existing_tokens.add(code)
            return code


def normalize_litio_interview_tokens(apps, schema_editor):
    Interview = apps.get_model('smartInterviewApp', 'Interview')
    existing_tokens = set(
        token
        for token in Interview.objects.exclude(litio_interview_token__isnull=True)
        .exclude(litio_interview_token='')
        .values_list('litio_interview_token', flat=True)
        if token and len(token) <= 16
    )

    for interview in Interview.objects.exclude(litio_interview_token__isnull=True).exclude(litio_interview_token='').iterator():
        token = (interview.litio_interview_token or '').strip()
        if token and len(token) <= 16:
            existing_tokens.add(token)
            continue
        interview.litio_interview_token = generate_short_code(existing_tokens)
        interview.save(update_fields=['litio_interview_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0036_interviewreminderdelivery'),
    ]

    operations = [
        migrations.RunPython(normalize_litio_interview_tokens, migrations.RunPython.noop),
    ]
