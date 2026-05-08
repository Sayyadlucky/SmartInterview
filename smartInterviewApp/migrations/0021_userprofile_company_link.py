from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0020_rename_smartinterv_industr_85fdb8_idx_smartinterv_industr_51cc76_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='user_profiles',
                to='smartInterviewApp.companyprofile',
            ),
        ),
    ]
