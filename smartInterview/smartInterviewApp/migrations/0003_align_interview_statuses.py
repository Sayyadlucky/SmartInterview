from django.db import migrations, models


def normalize_statuses(apps, schema_editor):
    Interview = apps.get_model('smartInterviewApp', 'Interview')

    status_map = {
        'assessment_Pending': 'assessment_pending',
        'assessment pending': 'assessment_pending',
        'assessment_pending': 'assessment_pending',
        'Assesment_Completed': 'assessment_completed',
        'assesment_completed': 'assessment_completed',
        'assesment completed': 'assessment_completed',
        'assessment completed': 'assessment_completed',
        'assessment_completed': 'assessment_completed',
        'Auto_screened': 'auto_screening_scheduled',
        'auto_screened': 'auto_screening_scheduled',
        'auto screened': 'auto_screening_scheduled',
        'auto screening': 'auto_screening_scheduled',
        'auto screening scheduled': 'auto_screening_scheduled',
        'auto_screening_scheduled': 'auto_screening_scheduled',
    }

    for old, new in status_map.items():
        Interview.objects.filter(status=old).update(status=new)


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0002_remove_vacancies_recruiter_vacancies_recruiter'),
    ]

    operations = [
        migrations.AlterField(
            model_name='interview',
            name='status',
            field=models.CharField(
                choices=[
                    ('scheduled', 'Scheduled'),
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                    ('shortlisted', 'Shortlisted'),
                    ('hired', 'Hired'),
                    ('assessment_pending', 'Assessment Pending'),
                    ('rejected', 'Rejected'),
                    ('assessment_completed', 'Assessment Completed'),
                    ('auto_screening_scheduled', 'Auto Screening Scheduled'),
                ],
                default='scheduled',
                max_length=30,
            ),
        ),
        migrations.RunPython(normalize_statuses, migrations.RunPython.noop),
    ]