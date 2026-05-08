from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import smartInterviewApp.pgvector_compat


def enable_pgvector_extension(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('CREATE EXTENSION IF NOT EXISTS vector')


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0026_vacancies_job_type_vacancies_location'),
    ]

    operations = [
        migrations.RunPython(enable_pgvector_extension, migrations.RunPython.noop),
        migrations.CreateModel(
            name='CandidateSearchProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('normalized_title', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('normalized_skills', models.JSONField(blank=True, default=list)),
                ('role_family', models.CharField(blank=True, db_index=True, default='', max_length=80)),
                ('role_subfamily', models.CharField(blank=True, db_index=True, default='', max_length=80)),
                ('experience_years', models.DecimalField(blank=True, db_index=True, decimal_places=2, max_digits=5, null=True)),
                ('location_normalized', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('latest_role_summary', models.CharField(blank=True, default='', max_length=255)),
                ('recent_companies', models.JSONField(blank=True, default=list)),
                ('domain_exposure', models.JSONField(blank=True, default=list)),
                ('availability', models.CharField(blank=True, default='', max_length=120)),
                ('profile_quality_score', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('search_text', models.TextField(blank=True, default='')),
                ('embedding', smartInterviewApp.pgvector_compat.VectorField(blank=True, dimensions=384, null=True)),
                ('embedding_json', models.JSONField(blank=True, default=list)),
                ('search_metadata', models.JSONField(blank=True, default=dict)),
                ('parser_signature', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('source_signature', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('indexed_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('active_resume', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='search_profiles', to='smartInterviewApp.candidateresume')),
                ('candidate', models.OneToOneField(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='search_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-indexed_at', '-updated_at'],
                'indexes': [
                    models.Index(fields=['role_family', 'role_subfamily'], name='cand_search_family_idx'),
                    models.Index(fields=['location_normalized', 'experience_years'], name='cand_search_loc_exp_idx'),
                    smartInterviewApp.pgvector_compat.HnswIndex(fields=['embedding'], name='cand_search_embedding_hnsw'),
                ],
            },
        ),
        migrations.CreateModel(
            name='RoleSearchCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('query_signature', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('role_family', models.CharField(blank=True, db_index=True, default='', max_length=80)),
                ('role_subfamily', models.CharField(blank=True, db_index=True, default='', max_length=80)),
                ('location_normalized', models.CharField(blank=True, default='', max_length=255)),
                ('search_text', models.TextField(blank=True, default='')),
                ('embedding', smartInterviewApp.pgvector_compat.VectorField(blank=True, dimensions=384, null=True)),
                ('embedding_json', models.JSONField(blank=True, default=list)),
                ('search_metadata', models.JSONField(blank=True, default=dict)),
                ('indexed_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('vacancy', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='search_cache', to='smartInterviewApp.vacancies')),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
