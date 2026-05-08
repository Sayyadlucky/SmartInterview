from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0009_email_verification_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='CandidateIdentityVerification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('verification_method', models.CharField(blank=True, choices=[('offline_xml', 'Offline XML'), ('document_upload', 'Document Upload')], default='', max_length=30)),
                ('status', models.CharField(choices=[('not_started', 'Not Started'), ('processing', 'Processing'), ('xml_verified', 'XML Verified'), ('document_matched', 'Document Matched'), ('document_mismatch', 'Document Mismatch'), ('failed', 'Failed')], default='not_started', max_length=30)),
                ('uploaded_xml', models.FileField(blank=True, null=True, upload_to='identity/offline_xml/')),
                ('uploaded_pdf', models.FileField(blank=True, null=True, upload_to='identity/documents/')),
                ('uploaded_front_image', models.FileField(blank=True, null=True, upload_to='identity/documents/')),
                ('uploaded_back_image', models.FileField(blank=True, null=True, upload_to='identity/documents/')),
                ('aadhaar_name', models.CharField(blank=True, default='', max_length=255)),
                ('aadhaar_gender', models.CharField(blank=True, default='', max_length=20)),
                ('aadhaar_dob', models.CharField(blank=True, default='', max_length=40)),
                ('aadhaar_reference', models.CharField(blank=True, default='', max_length=80)),
                ('raw_text', models.TextField(blank=True, default='')),
                ('extracted_data', models.JSONField(blank=True, default=dict)),
                ('comparison', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True, default='')),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.OneToOneField(limit_choices_to={'profile__role': 'candidate'}, on_delete=django.db.models.deletion.CASCADE, related_name='identity_verification', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
