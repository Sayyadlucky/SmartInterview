from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0042_blueprint_plan_skill_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='skillquestion',
            name='question_hash',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='codingquestion',
            name='prompt_hash',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='questiongenerationjob',
            name='skill',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='generation_jobs',
                to='smartInterviewApp.skill',
            ),
        ),
        migrations.AddConstraint(
            model_name='skillquestion',
            constraint=models.UniqueConstraint(
                condition=models.Q(('question_hash', ''), _negated=True),
                fields=('skill', 'question_hash'),
                name='unique_skill_question_hash',
            ),
        ),
        migrations.AddConstraint(
            model_name='codingquestion',
            constraint=models.UniqueConstraint(
                condition=models.Q(('prompt_hash', ''), _negated=True),
                fields=('skill', 'prompt_hash'),
                name='unique_skill_coding_prompt_hash',
            ),
        ),
        migrations.AddIndex(
            model_name='questiongenerationjob',
            index=models.Index(fields=['skill', 'task_type', 'status'], name='smartInterv_skill_i_f9000e_idx'),
        ),
    ]
