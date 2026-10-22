from django.test import TestCase
from django.urls import reverse

from .helpers import PASSWORD, make_patient, make_professional

# every workspace page (GET) and every workspace action (POST) that must stay closed until credentials are approved
PAGES = ['accounts:dashboard', 'accounts:patients', 'accounts:patient-add', 'accounts:appointments', 'accounts:plans',
         'billing:billing', 'billing:packages', 'exercises:library']
JSON_GETS = ['accounts:icd10-search', 'accounts:appointment-patient-search', 'profiles:medicine-search', 'lab:search', 'exercises:search']


class VerificationGateTests(TestCase):
    def sign_in(self, status):
        user, self.profile = make_professional('gated', status=status)
        self.patient = make_patient(self.profile)
        self.client.login(username='gated', password=PASSWORD)

    def test_unapproved_professional_is_kept_out_of_every_workspace_page(self):
        for status in ('draft', 'submitted', 'rejected'):
            self.profile = None
            user, self.profile = make_professional(f'u_{status}', status=status)
            self.client.login(username=f'u_{status}', password=PASSWORD)
            for name in PAGES:
                response = self.client.get(reverse(name))
                self.assertRedirects(response, reverse('accounts:welcome'), fetch_redirect_response=False, msg_prefix=f'{status} {name}')
            for path in (f'/accounts/patients/{make_patient(self.profile).pk}/', '/exercises/', '/billing/packages/'):
                self.assertEqual(self.client.get(path).status_code, 302, path)
            self.client.logout()

    def test_unapproved_professional_cannot_use_search_or_post_endpoints(self):
        self.sign_in('submitted')
        for name in JSON_GETS:
            self.assertIn(self.client.get(reverse(name), {'q': 'abc'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, (403,), name)
        response = self.client.post(reverse('accounts:patient-add'), {'name': 'Sneaky', 'phone': '9800000001', 'gender': 'F'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.profile.patients.filter(name='Sneaky').exists())

    def test_welcome_page_explains_the_wait_and_dashboard_opens_after_approval(self):
        self.sign_in('submitted')
        self.assertContains(self.client.get(reverse('accounts:welcome')), 'Submitted')
        self.profile.status = 'approved'
        self.profile.save()
        self.assertRedirects(self.client.get(reverse('accounts:welcome')), reverse('accounts:dashboard'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:patients')).status_code, 200)

    def test_helpers_refuse_even_without_the_middleware(self):
        from django.core.exceptions import PermissionDenied
        from django.test import RequestFactory
        from accounts.access import own_patient, require_workspace
        self.sign_in('rejected')
        request = RequestFactory().get('/')
        request.user = self.profile.account.user
        with self.assertRaises(PermissionDenied):
            require_workspace(request)
        with self.assertRaises(PermissionDenied):
            own_patient(request, self.patient.pk)
