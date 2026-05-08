from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0022_userprofile_company_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyprofile',
            name='logo_url',
            field=models.URLField(blank=True, default=''),
        ),
    ]
