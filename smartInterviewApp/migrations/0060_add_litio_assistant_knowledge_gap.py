"""Add LitioAssistantKnowledgeGap model.

Generated for Phase 3 knowledge gap tracking.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0059_repair_litio_assistant_knowledge_schema'),
    ]

    operations = [
        migrations.CreateModel(
            name='LitioAssistantKnowledgeGap',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_question', models.TextField(blank=True, null=True)),
                ('normalized_question', models.CharField(blank=True, db_index=True, max_length=512, null=True)),
                ('context', models.JSONField(blank=True, default=dict)),
                ('fallback_reason', models.CharField(default='no_matching_knowledge', max_length=120, db_index=True)),
                ('status', models.CharField(choices=[('open', 'Open'), ('reviewed', 'Reviewed'), ('resolved', 'Resolved'), ('ignored', 'Ignored')], db_index=True, default='open', max_length=30)),
                ('admin_notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('conversation', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='knowledge_gaps', to='smartInterviewApp.litioassistantconversation')),
                ('message', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='knowledge_gaps', to='smartInterviewApp.litioassistantmessage')),
                ('company', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='litio_assistant_knowledge_gaps', to='smartInterviewApp.companyprofile')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='litio_assistant_knowledge_gaps', to='auth.user')),
                ('resolved_by_knowledge', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='resolved_gaps', to='smartInterviewApp.litioassistantknowledge')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='litioassistantknowledgegap',
            index=models.Index(fields=['normalized_question', 'status'], name='smartInterviewApp_liti_norm_status_idx'),
        ),
        migrations.AddIndex(
            model_name='litioassistantknowledgegap',
            index=models.Index(fields=['fallback_reason', 'created_at'], name='smartInterviewApp_liti_fallback_created_idx'),
        ),
    ]
