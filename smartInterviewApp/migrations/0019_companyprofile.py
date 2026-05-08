from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('smartInterviewApp', '0018_interview_interview_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanyProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('legal_name', models.CharField(max_length=255)),
                ('display_name', models.CharField(blank=True, default='', max_length=255)),
                ('company_code', models.CharField(blank=True, db_index=True, default='', max_length=50)),
                ('description', models.TextField(blank=True, default='')),
                ('industry', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('sub_industry', models.CharField(blank=True, default='', max_length=120)),
                ('company_type', models.CharField(choices=[('private', 'Private Limited'), ('public', 'Public Company'), ('llp', 'LLP'), ('partnership', 'Partnership'), ('sole_proprietorship', 'Sole Proprietorship'), ('non_profit', 'Non Profit'), ('government', 'Government'), ('agency', 'Agency / Consultancy'), ('other', 'Other')], default='private', max_length=30)),
                ('company_stage', models.CharField(blank=True, choices=[('bootstrapped', 'Bootstrapped'), ('seed', 'Seed'), ('series_a', 'Series A'), ('series_b', 'Series B'), ('series_c', 'Series C+'), ('growth', 'Growth'), ('enterprise', 'Enterprise'), ('public_market', 'Public Market'), ('other', 'Other')], default='', max_length=30)),
                ('company_size', models.CharField(blank=True, choices=[('1_10', '1-10'), ('11_50', '11-50'), ('51_200', '51-200'), ('201_500', '201-500'), ('501_1000', '501-1,000'), ('1001_5000', '1,001-5,000'), ('5001_10000', '5,001-10,000'), ('10000_plus', '10,000+')], default='', max_length=20)),
                ('employee_count', models.PositiveIntegerField(blank=True, null=True)),
                ('founded_year', models.PositiveIntegerField(blank=True, null=True)),
                ('website', models.URLField(blank=True, default='')),
                ('careers_page', models.URLField(blank=True, default='')),
                ('linkedin_url', models.URLField(blank=True, default='')),
                ('twitter_url', models.URLField(blank=True, default='')),
                ('logo', models.FileField(blank=True, null=True, upload_to='company_logos/')),
                ('contact_email', models.EmailField(blank=True, default='', max_length=254)),
                ('contact_phone', models.CharField(blank=True, default='', max_length=20)),
                ('alternate_phone', models.CharField(blank=True, default='', max_length=20)),
                ('address_line_1', models.CharField(blank=True, default='', max_length=255)),
                ('address_line_2', models.CharField(blank=True, default='', max_length=255)),
                ('landmark', models.CharField(blank=True, default='', max_length=255)),
                ('city', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('state', models.CharField(blank=True, default='', max_length=120)),
                ('postal_code', models.CharField(blank=True, default='', max_length=20)),
                ('country', models.CharField(blank=True, default='India', max_length=120)),
                ('headquarters', models.CharField(blank=True, default='', max_length=255)),
                ('timezone', models.CharField(blank=True, default='Asia/Kolkata', max_length=80)),
                ('registration_number', models.CharField(blank=True, default='', max_length=120)),
                ('tax_identifier', models.CharField(blank=True, default='', max_length=120)),
                ('currency_code', models.CharField(blank=True, default='INR', max_length=10)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('admin', models.OneToOneField(limit_choices_to={'profile__role': 'admin'}, on_delete=django.db.models.deletion.CASCADE, related_name='company_profile', to='auth.user')),
            ],
            options={
                'ordering': ['legal_name', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='companyprofile',
            index=models.Index(fields=['industry', 'city'], name='smartInterv_industr_85fdb8_idx'),
        ),
        migrations.AddIndex(
            model_name='companyprofile',
            index=models.Index(fields=['company_code'], name='smartInterv_company_aac1ac_idx'),
        ),
        migrations.AddIndex(
            model_name='companyprofile',
            index=models.Index(fields=['legal_name'], name='smartInterv_legal_n_7869b0_idx'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='user_profiles', to='smartInterviewApp.companyprofile'),
        ),
    ]
