from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0021_userprofile_company_link'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='company_url',
            field=models.URLField(blank=True, default=''),
        ),
    ]
