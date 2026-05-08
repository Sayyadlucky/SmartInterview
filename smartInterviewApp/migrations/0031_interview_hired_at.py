from django.db import migrations, models


def backfill_hired_at(apps, schema_editor):
    Interview = apps.get_model('smartInterviewApp', 'Interview')
    Interview.objects.filter(
        status__in=['hired', 'completed'],
        hired_at__isnull=True,
        date__isnull=False,
    ).update(hired_at=models.F('date'))


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0030_repair_pgvector_embeddings'),
    ]

    operations = [
        migrations.AddField(
            model_name='interview',
            name='hired_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_hired_at, migrations.RunPython.noop),
    ]
