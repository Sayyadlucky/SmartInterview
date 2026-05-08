from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0017_interviewer_role_hierarchy'),
    ]

    operations = [
        migrations.AddField(
            model_name='interview',
            name='interview_type',
            field=models.CharField(
                choices=[('manual', 'Manual Interview'), ('auto', 'Auto Interview')],
                default='manual',
                max_length=20,
            ),
        ),
    ]
