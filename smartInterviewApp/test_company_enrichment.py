from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from smartInterviewApp.models import CompanyProfile, UserProfile
from smartInterviewApp.services.company_enrichment import ensure_company_profile_for_user


class CompanyEnrichmentBootstrapTests(TestCase):
    @patch('smartInterviewApp.services.company_enrichment._trigger_company_enrichment_in_background')
    def test_existing_company_profile_does_not_retrigger_dashboard_enrichment(self, trigger_mock):
        user = User.objects.create_user(username='admin-company', password='pass1234', email='admin-company@example.com')
        profile = UserProfile.objects.create(user=user, role='admin', company_url='https://example.com')
        company = CompanyProfile.objects.create(
            admin=user,
            legal_name='Example Inc',
            display_name='Example',
            website='https://example.com',
            description='TBD',
            contact_email='TBD',
            contact_phone='TBD',
            address_line_1='TBD',
            city='TBD',
            state='TBD',
            postal_code='TBD',
            headquarters='TBD',
        )

        result = ensure_company_profile_for_user(user)

        profile.refresh_from_db()
        self.assertEqual(result.id, company.id)
        self.assertEqual(profile.company_id, company.id)
        trigger_mock.assert_not_called()

    @patch('smartInterviewApp.services.company_enrichment._trigger_company_enrichment_in_background')
    def test_new_company_profile_triggers_bootstrap_enrichment_once(self, trigger_mock):
        user = User.objects.create_user(username='admin-bootstrap', password='pass1234', email='admin-bootstrap@example.com')
        profile = UserProfile.objects.create(user=user, role='admin', company_url='https://example.com')

        result = ensure_company_profile_for_user(user)

        profile.refresh_from_db()
        self.assertIsNotNone(result)
        self.assertEqual(profile.company_id, result.id)
        trigger_mock.assert_called_once_with(user.id, 'https://example.com')
