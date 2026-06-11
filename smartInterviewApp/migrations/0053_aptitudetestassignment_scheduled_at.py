from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0052_alter_aptitudeintegrityevent_event_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='aptitudetestassignment',
            name='scheduled_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
