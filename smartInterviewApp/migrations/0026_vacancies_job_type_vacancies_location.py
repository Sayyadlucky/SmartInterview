from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0025_vacancies_salary_range_vacancies_experience_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancies',
            name='job_type',
            field=models.CharField(blank=True, choices=[('full_time', 'Full Time'), ('part_time', 'Part Time'), ('intern', 'Intern')], default='', max_length=20),
        ),
        migrations.AddField(
            model_name='vacancies',
            name='location',
            field=models.CharField(blank=True, default='', max_length=160),
        ),
    ]
