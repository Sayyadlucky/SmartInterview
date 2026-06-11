from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


KNOWLEDGE_ENTRIES = [
    {
        'category': 'dashboard',
        'title': 'Dashboard overview',
        'slug': 'dashboard-overview',
        'question_patterns': ['dashboard', 'overview', 'hiring pipeline', 'open roles', 'candidate activity', 'action items'],
        'short_answer': 'The dashboard gives recruiters a single workspace for the hiring pipeline, open roles, candidate activity, interviews, reminders, and action items.',
        'detailed_answer': 'Use it to review candidate progress, spot pending actions, open role activity, and continue the workflows that need attention today.',
        'steps': ['Open Dashboard from the sidebar.', 'Review KPI cards, pipeline status, and needs-attention items.', 'Use the candidate table or quick actions to continue hiring work.'],
        'priority': 10,
    },
    {
        'category': 'vacancy',
        'title': 'Create a vacancy',
        'slug': 'create-vacancy',
        'question_patterns': ['create vacancy', 'create job', 'new vacancy', 'job creation', 'post job', 'role details', 'jd'],
        'short_answer': 'Create a vacancy when you want Shortlistii to track a role, match candidates, and coordinate assessments for that opening.',
        'steps': ['Open Vacancies or Job Postings.', 'Click Create Vacancy.', 'Add role details, experience, location, skills, and the job description.', 'Save the vacancy.', 'Add candidates or match candidates from the talent pool.'],
        'priority': 20,
    },
    {
        'category': 'candidate',
        'title': 'Add candidates',
        'slug': 'add-candidates',
        'question_patterns': ['add candidates', 'upload candidate', 'upload resume', 'candidate upload', 'parsed details', 'save candidate'],
        'short_answer': 'Add candidates by uploading their resume or profile details, then reviewing the parsed information before saving.',
        'steps': ['Open a vacancy or the candidate section.', 'Upload the resume or enter candidate profile details.', 'Review parsed details for accuracy.', 'Save the candidate.', 'Use the saved candidate for matching, interviews, tests, or status updates.'],
        'priority': 30,
    },
    {
        'category': 'candidate',
        'title': 'AI Talent Pool',
        'slug': 'ai-talent-pool',
        'question_patterns': ['ai talent pool', 'talent pool', 'recommended candidates', 'candidate matching', 'matched skills', 'skill gaps'],
        'short_answer': 'AI Talent Pool helps recruiters discover and compare candidates using resume information, role fit, matched skills, gaps, and hiring signals.',
        'detailed_answer': 'Use it as a decision-support view. It helps you shortlist stronger-fit candidates faster, but recruiters should still review candidate profiles and role context before taking final action.',
        'steps': ['Open AI Talent Pool from the dashboard navigation.', 'Select or search for the role you are hiring for.', 'Review recommended candidates, skill matches, gaps, and explanations.', 'Open a candidate profile or continue with interview and test assignment.'],
        'priority': 40,
    },
    {
        'category': 'score',
        'title': 'Resume score',
        'slug': 'resume-score',
        'question_patterns': ['resume score', 'candidate score', 'resume fit', 'resume rating'],
        'short_answer': 'Resume score is a helpful fit indicator based on the information available in the candidate resume.',
        'detailed_answer': 'It should be used as a screening signal, not as the only hiring decision. Review the candidate profile, skills, experience, and role context alongside the score.',
        'priority': 50,
    },
    {
        'category': 'score',
        'title': 'Role fit score',
        'slug': 'role-fit-score',
        'question_patterns': ['role fit score', 'fit score', 'role match', 'candidate role fit', 'matching score'],
        'short_answer': 'Role fit score compares the candidate profile with the role requirements and highlights how closely the available information matches.',
        'detailed_answer': 'The score is intended to guide review and prioritization. Exact formulas are protected, but recruiters can use the visible evidence, gaps, and profile details to understand the match.',
        'priority': 60,
    },
    {
        'category': 'interview',
        'title': 'Manual interview',
        'slug': 'manual-interview',
        'question_patterns': ['manual interview', 'schedule manual interview', 'interviewer', 'review manual interview'],
        'short_answer': 'Manual interviews let recruiters schedule human-led interview rounds and review the outcome inside the candidate workflow.',
        'steps': ['Open the candidate or role workflow.', 'Choose the manual interview action.', 'Select interviewer details and schedule information.', 'Share or confirm the interview details with the candidate.', 'Review feedback and update candidate status after the interview.'],
        'priority': 70,
    },
    {
        'category': 'interview',
        'title': 'Litio auto interview',
        'slug': 'litio-auto-interview',
        'question_patterns': ['litio interview', 'auto interview', 'assign interview', 'candidate interview link', 'guided interview', 'evaluation summary'],
        'short_answer': 'Litio auto interview helps recruiters assign a guided interview that candidates can complete through a secure link.',
        'steps': ['Assign the Litio interview from the candidate or workflow action.', 'The candidate receives an interview link.', 'The candidate completes the guided interview.', 'Recruiters review the evaluation summary, answers, strengths, gaps, and hiring signals.', 'Update candidate status or continue to the next assessment step.'],
        'priority': 80,
    },
    {
        'category': 'assessment',
        'title': 'Aptitude test',
        'slug': 'aptitude-test',
        'question_patterns': ['aptitude test', 'assign aptitude', 'aptitude assessment', 'timed test', 'passing score', '50 questions', '60 minutes'],
        'short_answer': 'Aptitude tests can be assigned to candidates as timed assessments. Current default setup is 50 questions, 100 marks, 70% passing, and 60 minutes.',
        'steps': ['Assign the aptitude test from the candidate workflow.', 'The candidate receives a test link.', 'The candidate completes the timed assessment.', 'Recruiters review score, status, and assessment summary.', 'Use the result with the candidate profile and interview signals.'],
        'priority': 90,
    },
    {
        'category': 'reports',
        'title': 'Reports and evaluation summary',
        'slug': 'reports-evaluation-summary',
        'question_patterns': ['reports', 'evaluation summary', 'candidate report', 'strengths', 'gaps', 'answers', 'hiring signals'],
        'short_answer': 'Reports and evaluation summaries help recruiters review candidate performance, strengths, gaps, answers, scores, and hiring signals depending on the completed modules.',
        'steps': ['Open the candidate profile or completed interview record.', 'Open the evaluation summary or report view.', 'Review the summary, skills, evidence, answers, scores, and recommended follow-ups.', 'Use the report to decide the next candidate status or assessment step.'],
        'priority': 100,
    },
    {
        'category': 'reminders',
        'title': 'Reminders and status updates',
        'slug': 'reminders-status-updates',
        'question_patterns': ['reminders', 'status updates', 'whatsapp', 'sms', 'email', 'send reminder', 'candidate status'],
        'short_answer': 'Shortlistii can help send or update reminders through configured communication channels such as SMS, WhatsApp, or email, depending on your workspace setup.',
        'detailed_answer': 'Candidate status updates help recruiters track where each candidate is in the hiring workflow and decide the next action.',
        'steps': ['Open the candidate or interview workflow.', 'Check the current assignment or interview status.', 'Use resend invite or reminder if available.', 'Update the candidate status after the action is completed.'],
        'priority': 110,
    },
    {
        'category': 'troubleshooting',
        'title': 'Candidate did not receive link',
        'slug': 'candidate-did-not-receive-link',
        'question_patterns': ['did not receive link', 'candidate link missing', 'resend invite', 'not received email', 'not received sms', 'not received whatsapp'],
        'short_answer': 'If a candidate did not receive a link, first confirm the candidate contact details and assignment status.',
        'steps': ['Check the candidate email and phone number.', 'Confirm the interview or assessment assignment status.', 'Use resend invite or reminder if available.', 'Confirm your workspace communication setup is active.', 'Ask the candidate to check spam, blocked messages, or alternate inboxes.'],
        'priority': 120,
    },
    {
        'category': 'troubleshooting',
        'title': 'Camera or microphone issue',
        'slug': 'camera-microphone-issue',
        'question_patterns': ['camera issue', 'mic issue', 'microphone issue', 'browser permission', 'device selection', 'network issue', 'supported browser'],
        'short_answer': 'For camera or microphone issues, check browser permissions, selected devices, network stability, and whether the candidate is using a supported browser.',
        'steps': ['Allow camera and microphone permissions in the browser.', 'Select the correct camera and microphone device.', 'Close other apps that may be using the device.', 'Refresh the page after permissions are enabled.', 'Try a stable network and a current supported browser.'],
        'priority': 130,
    },
    {
        'category': 'feedback',
        'title': 'Share feedback',
        'slug': 'share-feedback',
        'question_patterns': ['share feedback', 'feedback', 'confusing', 'missing', 'not working', 'suggestion', 'need help'],
        'short_answer': 'You can share what is confusing, missing, or not working so the Shortlistii team can improve the workflow.',
        'detailed_answer': 'Use feedback for unclear screens, missing workflow options, confusing scores, notification problems, or ideas that would make hiring work faster.',
        'steps': ['Describe what you were trying to do.', 'Mention the feature area, candidate, role, or page if relevant.', 'Share what result you expected.', 'Add any error text or missing option you noticed.'],
        'priority': 140,
    },
]


def seed_litio_assistant_knowledge(apps, schema_editor):
    Knowledge = apps.get_model('smartInterviewApp', 'LitioAssistantKnowledge')
    for entry in KNOWLEDGE_ENTRIES:
        defaults = entry.copy()
        slug = defaults.pop('slug')
        Knowledge.objects.update_or_create(slug=slug, defaults=defaults)


def unseed_litio_assistant_knowledge(apps, schema_editor):
    Knowledge = apps.get_model('smartInterviewApp', 'LitioAssistantKnowledge')
    Knowledge.objects.filter(slug__in=[entry['slug'] for entry in KNOWLEDGE_ENTRIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0054_aptitude_candidate_result_payload_support'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LitioAssistantKnowledge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(db_index=True, max_length=80)),
                ('title', models.CharField(max_length=180)),
                ('slug', models.SlugField(max_length=120, unique=True)),
                ('question_patterns', models.JSONField(blank=True, default=list)),
                ('short_answer', models.TextField()),
                ('detailed_answer', models.TextField(blank=True, default='')),
                ('steps', models.JSONField(blank=True, default=list)),
                ('related_links', models.JSONField(blank=True, default=list)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('priority', models.PositiveIntegerField(db_index=True, default=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['priority', 'title', 'id'],
                'indexes': [
                    models.Index(fields=['category', 'is_active'], name='smartInterv_categor_4e75d0_idx'),
                    models.Index(fields=['priority', 'is_active'], name='smartInterv_priorit_853338_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='LitioAssistantConversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_context', models.CharField(blank=True, default='', max_length=160)),
                ('page_url', models.TextField(blank=True, default='')),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('last_message_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('status', models.CharField(choices=[('open', 'Open'), ('closed', 'Closed'), ('archived', 'Archived')], db_index=True, default='open', max_length=20)),
                ('feedback_rating', models.CharField(blank=True, default='', max_length=20)),
                ('feedback_summary', models.TextField(blank=True, default='')),
                ('company', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='litio_assistant_conversations', to='smartInterviewApp.companyprofile')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='litio_assistant_conversations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-last_message_at', '-id'],
                'indexes': [
                    models.Index(fields=['user', '-last_message_at'], name='smartInterv_user_id_55a42a_idx'),
                    models.Index(fields=['company', '-last_message_at'], name='smartInterv_company_37e140_idx'),
                    models.Index(fields=['status', '-last_message_at'], name='smartInterv_status_985c02_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='LitioAssistantMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sender', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant'), ('system', 'System')], db_index=True, max_length=20)),
                ('message', models.TextField()),
                ('intent', models.CharField(blank=True, db_index=True, default='', max_length=60)),
                ('confidence', models.FloatField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='smartInterviewApp.litioassistantconversation')),
                ('matched_knowledge', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='matched_messages', to='smartInterviewApp.litioassistantknowledge')),
            ],
            options={
                'ordering': ['created_at', 'id'],
                'indexes': [
                    models.Index(fields=['conversation', 'created_at'], name='smartInterv_convers_6a68ce_idx'),
                    models.Index(fields=['sender', 'created_at'], name='smartInterv_sender_75a912_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='LitioAssistantFeedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.CharField(choices=[('yes', 'Yes'), ('no', 'No'), ('needs_help', 'Need More Help')], db_index=True, max_length=20)),
                ('comment', models.TextField(blank=True, default='')),
                ('page_context', models.CharField(blank=True, default='', max_length=160)),
                ('page_url', models.TextField(blank=True, default='')),
                ('feature_area', models.CharField(blank=True, db_index=True, default='', max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feedback_events', to='smartInterviewApp.litioassistantconversation')),
                ('message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='feedback_events', to='smartInterviewApp.litioassistantmessage')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='litio_assistant_feedback', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['user', '-created_at'], name='smartInterv_user_id_5dce1c_idx'),
                    models.Index(fields=['conversation', '-created_at'], name='smartInterv_convers_9086a9_idx'),
                    models.Index(fields=['rating', '-created_at'], name='smartInterv_rating_5e1b4b_idx'),
                ],
            },
        ),
        migrations.RunPython(seed_litio_assistant_knowledge, unseed_litio_assistant_knowledge),
    ]
