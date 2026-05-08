from django.test import RequestFactory, SimpleTestCase

from smartInterviewApp.templatetags.host_links import host_link


class HostLinkTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_shortlistii_candidate_header_links_use_expected_subdomains(self):
        request = self.factory.get("/", secure=True, HTTP_HOST="shortlistii.com")

        self.assertEqual(host_link(request, "jobs"), "https://jobs.shortlistii.com/")
        self.assertEqual(host_link(request, "candidate_login"), "https://candidates.shortlistii.com/")
        self.assertEqual(host_link(request, "candidate_signup"), "https://candidates.shortlistii.com/signup/")

    def test_lvh_candidate_header_links_preserve_local_port(self):
        request = self.factory.get("/", HTTP_HOST="candidates.lvh.me:8000")

        self.assertEqual(host_link(request, "jobs"), "http://jobs.lvh.me:8000/")
        self.assertEqual(host_link(request, "candidate_login"), "http://candidates.lvh.me:8000/")
        self.assertEqual(host_link(request, "candidate_signup"), "http://candidates.lvh.me:8000/signup/")

    def test_legacy_candidate_typo_host_resolves_to_shortlistii_candidate_domain(self):
        request = self.factory.get("/", secure=True, HTTP_HOST="candidate.sshortlistii.com")

        self.assertEqual(host_link(request, "candidate_login"), "https://candidates.shortlistii.com/")
        self.assertEqual(host_link(request, "candidate_signup"), "https://candidates.shortlistii.com/signup/")
