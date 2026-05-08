from django.db import migrations, models


def backfill_pipeline_source(apps, schema_editor):
    CandidateVacancyApplication = apps.get_model('smartInterviewApp', 'CandidateVacancyApplication')

    CandidateVacancyApplication.objects.filter(
        pipeline_source='',
        source='candidate_dashboard',
    ).update(pipeline_source='self_applied')


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0032_candidatevacancyapplication_hiring_started_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidatevacancyapplication',
            name='pipeline_source',
            field=models.CharField(blank=True, choices=[('self_applied', 'Self Applied'), ('direct', 'Direct'), ('referral', 'Referral')], db_index=True, default='', max_length=20),
        ),
        migrations.RunPython(backfill_pipeline_source, migrations.RunPython.noop),
    ]
