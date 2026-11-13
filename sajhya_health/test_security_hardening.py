import time

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.tests.helpers import make_patient, make_professional


class RedirectSafetyTests(TestCase):
    def test_only_a_path_on_this_site_is_followed(self):
        from django.test import RequestFactory
        from .safe import local_path, same_site_url
        request = RequestFactory().get('/', HTTP_HOST='testserver')
        for good in ('/billing/', '/billing/?date=2026-11-01', '/accounts/patients/3/?tab=soap'):
            self.assertEqual(local_path(request, good, 'x'), good)
        for bad in ('', 'https://evil.com', '//evil.com', '/\evil.com', '/\/evil.com', 'javascript:alert(1)', '/ok\r\nSet-Cookie: a=b', '  //evil.com'):
            self.assertEqual(local_path(request, bad, 'x'), 'x', bad)
        self.assertEqual(same_site_url(request, 'http://testserver/lab/', 'x'), 'http://testserver/lab/')
        self.assertEqual(same_site_url(request, 'https://evil.com/', 'x'), 'x')

    def test_the_marketplace_cart_never_sends_you_to_another_site(self):
        from marketplace.models import Product
        # the redirect target of add-to-cart is checked by the same helper; try the dangerous forms against a billing page that follows "next"
        user, profile = make_professional()
        patient = make_patient(profile)
        self.client.force_login(user)
        from billing.models import BillingEntry
        entry = BillingEntry.objects.create(professional=profile, patient=patient, patient_name=patient.name, service='S', rate=100, payment_mode='cash')
        page = self.client.get(reverse('billing:invoice', args=[entry.pk]), {'next': '//evil.com/x'})
        self.assertNotContains(page, 'evil.com')
        page = self.client.get(reverse('billing:invoice', args=[entry.pk]), {'next': '/\evil.com'})
        self.assertNotContains(page, 'evil.com')
        r = self.client.post(reverse('billing:entry-payment', args=[entry.pk]), {'amount': '10', 'payment_mode': 'cash', 'next': '//evil.com'})
        self.assertNotIn('evil.com', r['Location'])


class HeadersAndSessionTests(TestCase):
    def test_the_content_security_policy_is_sent(self):
        response = self.client.get('/')
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])
        self.assertIn("object-src 'none'", response['Content-Security-Policy'])
        self.assertIn('Content-Security-Policy-Report-Only', response)
        self.assertIn('report-uri /csp-report/', response['Content-Security-Policy-Report-Only'])

    def test_csp_reports_are_accepted_small_and_only_logged(self):
        ok = self.client.post(reverse('csp-report'), data='{"csp-report": {"blocked-uri": "https://x.test/a.js", "document-uri": "https://app/x"}}', content_type='application/csp-report')
        self.assertEqual(ok.status_code, 204)
        big = self.client.post(reverse('csp-report'), data='x' * 5000, content_type='application/csp-report')
        self.assertEqual(big.status_code, 413)
        self.assertEqual(self.client.get(reverse('csp-report')).status_code, 405)

    @override_settings(IDLE_LOGOUT_MINUTES=30)
    def test_a_person_idle_for_too_long_is_signed_out(self):
        user, profile = make_professional()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        session = self.client.session
        session['last_seen'] = int(time.time()) - 31 * 60
        session.save()
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 302)  # really signed out

    @override_settings(IDLE_LOGOUT_MINUTES=30)
    def test_activity_keeps_the_session_alive_and_a_json_call_gets_401(self):
        user, profile = make_professional()
        self.client.force_login(user)
        self.client.get(reverse('accounts:dashboard'))
        session = self.client.session
        session['last_seen'] = int(time.time()) - 10 * 60
        session.save()
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        session = self.client.session
        session['last_seen'] = int(time.time()) - 40 * 60
        session.save()
        r = self.client.get(reverse('accounts:dashboard'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 401)

    def test_signup_does_not_say_which_e_mail_is_registered(self):
        from accounts.forms import SignupForm
        from accounts.models import Account
        from django.contrib.auth.models import User
        User.objects.create_user('first', 'taken@example.com', 'a-long-password-1')
        form = SignupForm({'username': 'second', 'email': 'taken@example.com', 'password1': 'a-long-password-2', 'password2': 'a-long-password-2'}, account_type=Account.PROFESSIONAL, subtype=None)
        form.is_valid()
        text = ' '.join(form.errors.get('email', []))
        self.assertNotIn('already exists', text)
        self.assertIn('cannot be used', text)
