from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0041_interview_question_bank'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobinterviewblueprint',
            name='blueprint_plan',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='jobinterviewskill',
            name='skill_role',
            field=models.CharField(
                choices=[
                    ('primary', 'Primary'),
                    ('primary_candidate', 'Primary Candidate'),
                    ('sub_skill', 'Sub Skill'),
                    ('optional', 'Optional'),
                ],
                db_index=True,
                default='sub_skill',
                max_length=30,
            ),
        ),
        migrations.AddIndex(
            model_name='jobinterviewskill',
            index=models.Index(fields=['blueprint', 'skill_role'], name='smartInterv_bluepri_84fd1f_idx'),
        ),
    ]
