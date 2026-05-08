from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0015_candidatepublicresume_download_count'),
    ]

    operations = [
        migrations.CreateModel(
            name='CandidateSavedVacancy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.ForeignKey(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='saved_vacancies', to=settings.AUTH_USER_MODEL)),
                ('vacancy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_by_candidates', to='smartInterviewApp.vacancies')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='candidatesavedvacancy',
            constraint=models.UniqueConstraint(fields=('candidate', 'vacancy'), name='unique_candidate_saved_vacancy'),
        ),
    ]
