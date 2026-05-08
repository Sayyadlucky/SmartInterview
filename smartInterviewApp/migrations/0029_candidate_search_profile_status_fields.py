from django.db import migrations, models


def cleanup_placeholder_profiles(apps, schema_editor):
    CandidateSearchProfile = apps.get_model('smartInterviewApp', 'CandidateSearchProfile')
    CandidateSearchProfile.objects.filter(
        is_active=False,
        active_resume__isnull=True,
        normalized_title='',
        role_family='',
        role_subfamily='',
        location_normalized='',
        search_text='',
        source_signature='',
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0028_alter_interview_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidatesearchprofile',
            name='inactive_reason',
            field=models.CharField(blank=True, db_index=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='candidatesearchprofile',
            name='active_resume_found',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='candidatesearchprofile',
            name='searchable_profile_built',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='candidatesearchprofile',
            name='missing_fields_summary',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(cleanup_placeholder_profiles, migrations.RunPython.noop),
    ]
