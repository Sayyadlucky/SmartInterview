from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0033_candidatevacancyapplication_pipeline_source'),
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
                    ('offer_made', 'Offer Made'),
                    ('offer_accepted', 'Offer Accepted'),
                    ('offer_declined', 'Offer Declined'),
                    ('hired', 'Hired'),
                    ('assessment_pending', 'Assessment Pending'),
                    ('rejected', 'Rejected'),
                    ('assessment_completed', 'Assessment Completed'),
                    ('auto_screening_scheduled', 'Auto Screening Scheduled'),
                ],
                default='scheduled',
                max_length=50,
            ),
        ),
    ]
