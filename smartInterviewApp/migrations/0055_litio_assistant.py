# Generated manually for Litio Assistant chatbot support.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0051_aptitude_question_generation_job'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LitioAssistantKnowledge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=180)),
                ('intent_key', models.CharField(max_length=120, unique=True)),
                ('category', models.CharField(choices=[('workflow', 'Workflow'), ('feature', 'Feature'), ('policy', 'Policy')], default='feature', max_length=30)),
                ('question_patterns', models.JSONField(blank=True, default=list)),
                ('keywords', models.JSONField(blank=True, default=list)),
                ('answer', models.TextField()),
                ('priority', models.PositiveSmallIntegerField(db_index=True, default=50)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['priority', 'title'],
                'indexes': [
                    models.Index(fields=['is_active', 'priority'], name='smartInterv_is_acti_3697aa_idx'),
                    models.Index(fields=['intent_key'], name='smartInterv_intent__305cce_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='LitioAssistantConversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, default='', max_length=180)),
                ('status', models.CharField(db_index=True, default='open', max_length=30)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='litio_assistant_conversations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at', '-id'],
                'indexes': [
                    models.Index(fields=['user', 'updated_at'], name='smartInterv_user_id_f18ae7_idx'),
                    models.Index(fields=['status', 'updated_at'], name='smartInterv_status_c1c4ab_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='LitioAssistantMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sender', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant')], db_index=True, max_length=20)),
                ('content', models.TextField()),
                ('intent_key', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('confidence', models.DecimalField(decimal_places=2, default=0, max_digits=4)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='smartInterviewApp.litioassistantconversation')),
            ],
            options={
                'ordering': ['created_at', 'id'],
                'indexes': [
                    models.Index(fields=['conversation', 'created_at'], name='smartInterv_convers_971546_idx'),
                    models.Index(fields=['sender', 'created_at'], name='smartInterv_sender_edb28b_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='LitioAssistantFeedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.CharField(choices=[('helpful', 'Helpful'), ('not_helpful', 'Not Helpful')], max_length=20)),
                ('comment', models.TextField(blank=True, default='')),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feedback', to='smartInterviewApp.litioassistantconversation')),
                ('message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='feedback', to='smartInterviewApp.litioassistantmessage')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='litio_assistant_feedback', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['conversation', 'created_at'], name='smartInterv_convers_cec8f6_idx'),
                    models.Index(fields=['rating', 'created_at'], name='smartInterv_rating_168020_idx'),
                ],
            },
        ),
    ]

