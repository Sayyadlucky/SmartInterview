from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0014_candidatepublicresume'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidatepublicresume',
            name='download_count',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
