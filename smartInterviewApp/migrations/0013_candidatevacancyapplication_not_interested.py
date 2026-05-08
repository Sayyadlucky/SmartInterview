from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0012_candidatevacancyapplication'),
    ]

    operations = [
        migrations.AlterField(
            model_name='candidatevacancyapplication',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending_review', 'Pending Review'),
                    ('approved', 'Approved'),
                    ('rejected', 'Rejected'),
                    ('withdrawn', 'Withdrawn'),
                    ('not_interested', 'Not Interested'),
                ],
                default='pending_review',
                max_length=30,
            ),
        ),
    ]
