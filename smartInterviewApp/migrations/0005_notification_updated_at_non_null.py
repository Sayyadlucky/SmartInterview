from django.db import migrations, models
from django.utils import timezone


def backfill_notification_updated_at(apps, schema_editor):
    Notification = apps.get_model('smartInterviewApp', 'Notification')
    Notification.objects.filter(updated_at__isnull=True).update(updated_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0004_notification_system'),
    ]

    operations = [
        migrations.RunPython(backfill_notification_updated_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='notification',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
