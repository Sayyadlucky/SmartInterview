from django.db import migrations


CANDIDATE_JOB_MAPPING_ENTRY = {
    'category': 'candidate_workflow',
    'title': 'Candidate job mapping',
    'slug': 'candidate-job-mapping',
    'question_patterns': [
        'how to tag candidate with job role',
        'assign candidate to job',
        'map candidate to vacancy',
        'link candidate with role',
        'attach candidate to job',
        'candidate job mapping',
        'move candidate to job pipeline',
        'add candidate to vacancy',
        'assign candidate to vacancy',
        'candidate with job role',
        'map candidate to role',
        'assign candidate role',
    ],
    'short_answer': 'To link a candidate with a job role, use Assign Candidate to create or find the candidate profile, select the active role, assign the hiring owner, and save the candidate into that role workflow.',
    'detailed_answer': 'Once the candidate is mapped to the role, the candidate appears with that role in the candidate pipeline and can move into interviews, aptitude tests, reports, or status updates.',
    'steps': [
        'Open Candidates or use the dashboard Assign Candidate action.',
        'Create or find the candidate profile.',
        'Search and select the target Role by title or role ID.',
        'Select the recruiter or hiring owner for follow-up.',
        'Save with Assign Candidate.',
        'Review the candidate under that role in Candidate Management or the role pipeline.',
    ],
    'priority': 25,
}

CREATE_VACANCY_PATTERNS = [
    'create vacancy',
    'create job',
    'post job',
    'post a job',
    'new vacancy',
    'job posting',
    'add job opening',
]


def add_candidate_job_mapping(apps, schema_editor):
    Knowledge = apps.get_model('smartInterviewApp', 'LitioAssistantKnowledge')
    defaults = CANDIDATE_JOB_MAPPING_ENTRY.copy()
    slug = defaults.pop('slug')
    Knowledge.objects.update_or_create(slug=slug, defaults=defaults)
    Knowledge.objects.filter(slug='create-vacancy').update(question_patterns=CREATE_VACANCY_PATTERNS)


def remove_candidate_job_mapping(apps, schema_editor):
    Knowledge = apps.get_model('smartInterviewApp', 'LitioAssistantKnowledge')
    Knowledge.objects.filter(slug='candidate-job-mapping').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('smartInterviewApp', '0055_litio_assistant'),
    ]

    operations = [
        migrations.RunPython(add_candidate_job_mapping, remove_candidate_job_mapping),
    ]
