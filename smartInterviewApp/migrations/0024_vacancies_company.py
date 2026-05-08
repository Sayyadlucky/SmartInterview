from django.db import migrations, models


def backfill_vacancy_company(apps, schema_editor):
    Vacancies = apps.get_model('smartInterviewApp', 'Vacancies')
    CompanyProfile = apps.get_model('smartInterviewApp', 'CompanyProfile')

    company_by_admin_id = {
        company.admin_id: company.id
        for company in CompanyProfile.objects.exclude(admin_id__isnull=True)
    }

    for vacancy in Vacancies.objects.filter(company_id__isnull=True).exclude(admin_id__isnull=True):
        company_id = company_by_admin_id.get(vacancy.admin_id)
        if company_id:
            vacancy.company_id = company_id
            vacancy.save(update_fields=['company'])


def clear_vacancy_company(apps, schema_editor):
    Vacancies = apps.get_model('smartInterviewApp', 'Vacancies')
    Vacancies.objects.update(company_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0023_companyprofile_logo_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancies',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name='vacancies',
                to='smartInterviewApp.companyprofile',
            ),
        ),
        migrations.RunPython(backfill_vacancy_company, clear_vacancy_company),
    ]
