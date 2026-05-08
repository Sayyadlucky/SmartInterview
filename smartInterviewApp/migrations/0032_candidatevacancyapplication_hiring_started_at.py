from django.db import migrations, models


def backfill_hiring_started_at(apps, schema_editor):
    CandidateVacancyApplication = apps.get_model('smartInterviewApp', 'CandidateVacancyApplication')
    Interview = apps.get_model('smartInterviewApp', 'Interview')

    CandidateVacancyApplication.objects.filter(
        hiring_started_at__isnull=True,
        applied_at__isnull=False,
    ).update(hiring_started_at=models.F('applied_at'))

    CandidateVacancyApplication.objects.filter(
        hiring_started_at__isnull=True,
        created_at__isnull=False,
    ).update(hiring_started_at=models.F('created_at'))

    remaining = (
        CandidateVacancyApplication.objects
        .filter(hiring_started_at__isnull=True)
        .values_list('id', 'candidate_id', 'vacancy_id')
    )
    fallback_pairs = {
        (candidate_id, vacancy_id): application_id
        for application_id, candidate_id, vacancy_id in remaining
        if candidate_id and vacancy_id
    }
    if not fallback_pairs:
        return

    interview_rows = (
        Interview.objects
        .filter(
            candidate_id__in={pair[0] for pair in fallback_pairs},
            role_id__in={pair[1] for pair in fallback_pairs},
        )
        .exclude(status__in=['hired', 'completed'])
        .exclude(date__isnull=True)
        .values('candidate_id', 'role_id')
        .annotate(first_seen_at=models.Min('date'))
    )

    updates = []
    for row in interview_rows:
        application_id = fallback_pairs.get((row['candidate_id'], row['role_id']))
        if not application_id:
            continue
        updates.append((application_id, row['first_seen_at']))

    for application_id, first_seen_at in updates:
        CandidateVacancyApplication.objects.filter(
            id=application_id,
            hiring_started_at__isnull=True,
        ).update(hiring_started_at=first_seen_at)


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0031_interview_hired_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidatevacancyapplication',
            name='hiring_started_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_hiring_started_at, migrations.RunPython.noop),
    ]
