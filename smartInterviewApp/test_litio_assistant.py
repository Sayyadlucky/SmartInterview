from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from smartInterviewApp.models import (
    LitioAssistantConversation,
    LitioAssistantFeedback,
    LitioAssistantKnowledge,
    LitioAssistantMessage,
    UserProfile,
)


class LitioAssistantApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        knowledge_entries = [
            {
                'slug': 'create-vacancy',
                'category': 'vacancy',
                'title': 'Create a vacancy',
                'question_patterns': ['create vacancy', 'create job', 'post job', 'post a job', 'new vacancy', 'job posting', 'add job opening'],
                'short_answer': 'Create a vacancy when you want Shortlistii to track a role, match candidates, and coordinate assessments for that opening.',
                'steps': ['Open Vacancies or Job Postings.', 'Click Create Vacancy.', 'Add role details, experience, location, skills, and the job description.', 'Save the vacancy.'],
                'priority': 20,
            },
            {
                'slug': 'candidate-job-mapping',
                'category': 'candidate_workflow',
                'title': 'Candidate job mapping',
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
                'steps': ['Open Candidates or use the dashboard Assign Candidate action.', 'Create or find the candidate profile.', 'Search and select the target Role by title or role ID.', 'Select the recruiter or hiring owner for follow-up.', 'Save with Assign Candidate.'],
                'priority': 25,
            },
            {
                'slug': 'ai-talent-pool',
                'category': 'candidate',
                'title': 'AI Talent Pool',
                'question_patterns': ['ai talent pool', 'talent pool'],
                'short_answer': 'AI Talent Pool helps recruiters discover and compare candidates using resume information, role fit, matched skills, gaps, and hiring signals.',
                'priority': 40,
            },
            {
                'slug': 'resume-score',
                'category': 'score',
                'title': 'Resume score',
                'question_patterns': ['resume score', 'candidate score'],
                'short_answer': 'Resume score is a helpful fit indicator based on the information available in the candidate resume.',
                'priority': 50,
            },
            {
                'slug': 'role-fit-score',
                'category': 'score',
                'title': 'Role fit score',
                'question_patterns': ['role fit score', 'fit score', 'what is role fit', 'explain role score', 'candidate matching score', 'why score is low', 'why score is high'],
                'short_answer': 'Role fit score compares the candidate profile with the role requirements and highlights how closely the available information matches.',
                'priority': 60,
            },
            {
                'slug': 'aptitude-test',
                'category': 'assessment',
                'title': 'Aptitude test',
                'question_patterns': ['aptitude test', 'assign aptitude'],
                'short_answer': 'Aptitude tests can be assigned to candidates as timed assessments.',
                'priority': 90,
            },
            {
                'slug': 'candidate-did-not-receive-link',
                'category': 'troubleshooting',
                'title': 'Candidate did not receive link',
                'question_patterns': ['did not receive link', 'candidate link missing'],
                'short_answer': 'If a candidate did not receive a link, first confirm the candidate contact details and assignment status.',
                'priority': 120,
            },
        ]
        for entry in knowledge_entries:
            defaults = entry.copy()
            slug = defaults.pop('slug')
            LitioAssistantKnowledge.objects.update_or_create(slug=slug, defaults=defaults)

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='recruiter-litio',
            email='recruiter-litio@example.com',
            password='pass1234',
        )
        UserProfile.objects.create(user=self.user, role='recruiter', gender='other', phone='919999999900')
        self.client.force_authenticate(user=self.user)

    def test_chat_endpoint_returns_answer_for_known_feature_query(self):
        response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'How do I create a vacancy?', 'page_context': 'dashboard'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])
        data = response.data['data']
        self.assertIn('Create Vacancy', data['answer'])
        self.assertEqual(data['category'], 'vacancy')
        self.assertEqual(data['matched_knowledge_slug'], 'create-vacancy')
        self.assertTrue(data['show_feedback'])

    def test_chat_endpoint_returns_fallback_for_unknown_query(self):
        response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'Can you plan my office lunch menu?'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['intent'], 'unsupported')
        self.assertIn("couldn't find an approved Shortlistii help answer", response.data['data']['answer'])

    def test_sensitive_query_returns_safe_response_without_provider_details(self):
        response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'what AI model do you use'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['intent'], 'sensitive_internal_query')
        self.assertIn('internal system details are protected', data['answer'])
        self.assertNotIn('OpenAI', data['answer'])
        self.assertEqual(data['matched_knowledge_slug'], '')

    def assert_candidate_job_mapping_answer(self, query):
        response = self.client.post('/api/litio-assistant/chat/', {'message': query}, format='json')
        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['category'], 'candidate_workflow')
        self.assertEqual(data['intent'], 'workflow_recommendation')
        self.assertEqual(data['matched_knowledge_slug'], 'candidate-job-mapping')
        self.assertIn('Assign Candidate', data['answer'])
        self.assertIn('select the active role', data['answer'])
        self.assertNotIn('Click Create Vacancy', data['answer'])
        self.assertNotEqual(data['matched_knowledge_slug'], 'role-fit-score')

    def test_candidate_job_mapping_override_queries(self):
        for query in [
            'how to tag candiate with job rile',
            'tag candidate with job role',
            'assign candidate to role',
            'map candidate to vacancy',
            'link candidate with job',
        ]:
            with self.subTest(query=query):
                self.assert_candidate_job_mapping_answer(query)

    def test_post_a_job_still_returns_create_vacancy(self):
        response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'post a job'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['category'], 'vacancy')
        self.assertEqual(data['matched_knowledge_slug'], 'create-vacancy')
        self.assertIn('Create Vacancy', data['answer'])

    def test_typo_normalization_maps_candidate_to_vacancy_query(self):
        self.assert_candidate_job_mapping_answer('assign candiadte to vacnacy')

    def test_role_fit_score_query_returns_role_fit_answer(self):
        response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'what is role fit score'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['category'], 'score')
        self.assertEqual(data['intent'], 'score_explanation')
        self.assertEqual(data['matched_knowledge_slug'], 'role-fit-score')
        self.assertIn('Role fit score compares', data['answer'])

    def test_conversation_and_messages_are_saved(self):
        response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'Explain AI Talent Pool'},
            format='json',
        )

        conversation_id = response.data['data']['conversation_id']
        self.assertTrue(LitioAssistantConversation.objects.filter(id=conversation_id, user=self.user).exists())
        messages = LitioAssistantMessage.objects.filter(conversation_id=conversation_id)
        self.assertEqual(messages.count(), 2)
        self.assertEqual(messages.filter(sender=LitioAssistantMessage.Sender.USER).count(), 1)
        self.assertEqual(messages.filter(sender=LitioAssistantMessage.Sender.ASSISTANT).count(), 1)

    def test_feedback_endpoint_saves_feedback(self):
        chat_response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'Explain resume score'},
            format='json',
        )
        data = chat_response.data['data']

        response = self.client.post(
            '/api/litio-assistant/feedback/',
            {
                'conversation_id': data['conversation_id'],
                'message_id': data['message_id'],
                'rating': 'no',
                'comment': 'I needed more detail.',
                'page_context': 'dashboard',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['success'])
        feedback = LitioAssistantFeedback.objects.get(conversation_id=data['conversation_id'])
        self.assertEqual(feedback.rating, LitioAssistantFeedback.Rating.NO)
        self.assertEqual(feedback.comment, 'I needed more detail.')

    def test_unauthenticated_access_is_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            '/api/litio-assistant/chat/',
            {'message': 'Create a vacancy'},
            format='json',
        )

        self.assertIn(response.status_code, (401, 403))

    def test_seeded_knowledge_entries_exist(self):
        slugs = set(LitioAssistantKnowledge.objects.values_list('slug', flat=True))
        self.assertIn('create-vacancy', slugs)
        self.assertIn('candidate-job-mapping', slugs)
        self.assertIn('aptitude-test', slugs)
        self.assertIn('candidate-did-not-receive-link', slugs)
