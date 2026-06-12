from io import StringIO

from django.contrib import admin
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from smartInterviewApp import admin as admin_module
from smartInterviewApp.models import (
    LitioAssistantKnowledge,
    LitioAssistantKnowledgeGap,
    LitioAssistantConversation,
)


class LitioAssistantAdminTests(TestCase):
    def setUp(self):
        self.knowledge_cls = LitioAssistantKnowledge
        self.gap_cls = LitioAssistantKnowledgeGap
        # prepare a fake request with messages storage for admin actions
        from django.test import RequestFactory
        rf = RequestFactory()
        self.request = rf.get('/')
        setattr(self.request, 'user', None)

        class DummyMessages:
            def add(self, level, message, extra_tags=None, fail_silently=False):
                return None

        # simple no-op message storage for admin.message_user calls in tests
        self.request._messages = DummyMessages()

    def test_mark_active_inactive_actions(self):
        k1 = self.knowledge_cls.objects.create(title='A', intent_key='ak_test_1', category='feature', answer='a', is_active=False)
        k2 = self.knowledge_cls.objects.create(title='B', intent_key='ak_test_2', category='feature', answer='b', is_active=False)
        admin_inst = admin_module.LitioAssistantKnowledgeAdmin(self.knowledge_cls, admin.site)
        qs = self.knowledge_cls.objects.filter(id__in=[k1.id, k2.id])
        admin_inst.mark_selected_active(self.request, qs)
        self.assertTrue(self.knowledge_cls.objects.get(id=k1.id).is_active)
        admin_inst.mark_selected_inactive(self.request, qs)
        self.assertFalse(self.knowledge_cls.objects.get(id=k2.id).is_active)

    def test_create_draft_from_gap_action(self):
        conv = LitioAssistantConversation.objects.create(user=None, title='t')
        gap = self.gap_cls.objects.create(
            conversation=conv,
            original_question='How do I do X?',
            normalized_question='how do i do x',
            context={'page': 'vacancy_detail', 'vacancyId': '12'},
            fallback_reason='no_matching_knowledge',
            status=self.gap_cls.Status.OPEN,
        )
        admin_inst = admin_module.LitioAssistantKnowledgeGapAdmin(self.gap_cls, admin.site)
        qs = self.gap_cls.objects.filter(id=gap.id)
        admin_inst.create_draft_knowledge_from_selected_gaps(self.request, qs)
        # draft created and inactive
        self.assertTrue(self.knowledge_cls.objects.filter(intent_key=f'gap_review_{gap.id}', is_active=False).exists())
        gap.refresh_from_db()
        self.assertEqual(gap.status, self.gap_cls.Status.REVIEWED)
        self.assertIsNotNone(gap.resolved_by_knowledge)

    def test_create_draft_skips_if_already_linked(self):
        conv = LitioAssistantConversation.objects.create(user=None, title='t2')
        gap = self.gap_cls.objects.create(
            conversation=conv,
            original_question='Q',
            normalized_question='q',
            context={},
            fallback_reason='no_matching_knowledge',
            status=self.gap_cls.Status.OPEN,
        )
        # create knowledge and link
        k = self.knowledge_cls.objects.create(title='pre', intent_key=f'gap_review_{gap.id}', category='knowledge_gap', answer='x', is_active=False)
        gap.resolved_by_knowledge = k
        gap.save()
        admin_inst = admin_module.LitioAssistantKnowledgeGapAdmin(self.gap_cls, admin.site)
        qs = self.gap_cls.objects.filter(id=gap.id)
        admin_inst.create_draft_knowledge_from_selected_gaps(self.request, qs)
        # should not create a duplicate
        self.assertEqual(self.knowledge_cls.objects.filter(intent_key=f'gap_review_{gap.id}').count(), 1)

    def test_management_command_summary_runs(self):
        out = StringIO()
        call_command('litio_assistant_gap_summary', stdout=out)
        text = out.getvalue()
        self.assertIn('Litio Assistant Knowledge Gap Summary', text)

    def test_management_command_with_gaps_counts(self):
        # create some gaps
        now = timezone.now()
        for i in range(3):
            self.gap_cls.objects.create(original_question=f'q{i}', normalized_question=f'q{i}', context={'page': 'p1'}, fallback_reason='no_matching_knowledge')
        out = StringIO()
        call_command('litio_assistant_gap_summary', '--days', '7', '--limit', '5', stdout=out)
        text = out.getvalue()
        self.assertIn('Total gaps:', text)
        self.assertIn('Top 5 normalized questions', text)
