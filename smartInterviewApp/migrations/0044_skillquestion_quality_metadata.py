from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0043_skill_question_bank_generation'),
    ]

    operations = [
        migrations.AddField(
            model_name='skillquestion',
            name='coverage_area',
            field=models.CharField(blank=True, db_index=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='skillquestion',
            name='quality_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('needs_review', 'Needs Review'),
                    ('approved', 'Approved'),
                    ('rejected', 'Rejected'),
                ],
                db_index=True,
                default='approved',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='skillquestion',
            name='quality_score',
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name='skillquestion',
            name='jd_relevance_score',
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name='skillquestion',
            name='quality_notes',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='skillquestion',
            name='generation_batch_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddIndex(
            model_name='skillquestion',
            index=models.Index(fields=['skill', 'coverage_area'], name='smartInterv_skill_i_b15dce_idx'),
        ),
        migrations.AddIndex(
            model_name='skillquestion',
            index=models.Index(fields=['skill', 'quality_status', 'is_active'], name='smartInterv_skill_i_cc0bb5_idx'),
        ),
    ]
