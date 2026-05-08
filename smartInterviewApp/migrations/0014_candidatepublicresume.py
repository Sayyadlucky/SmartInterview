from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0013_candidatevacancyapplication_not_interested'),
    ]

    operations = [
        migrations.CreateModel(
            name='CandidatePublicResume',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('short_code', models.CharField(db_index=True, max_length=16, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_shared_at', models.DateTimeField(blank=True, null=True)),
                ('last_viewed_at', models.DateTimeField(blank=True, null=True)),
                ('view_count', models.PositiveIntegerField(default=0)),
                ('candidate', models.OneToOneField(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='public_resume', to='auth.user')),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
