from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0024_vacancies_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancies',
            name='experience_required',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='vacancies',
            name='salary_range',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
