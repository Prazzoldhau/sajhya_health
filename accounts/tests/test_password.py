import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Account, Profession

from .helpers import PASSWORD, make_professional

NEW_PASSWORD = 'Brand-New-Pass-77'


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user, _ = make_professional('forgetful')
        self.url = reverse('accounts:password-reset')

    def request_reset(self, email='forgetful@example.com'):
        return self.client.post(self.url, {'email': email})

    def reset_link(self):
        body = mail.outbox[-1].body
        return re.search(r'https?://testserver(/\S+)', body).group(1)

    def test_login_page_links_to_forgot_password(self):
        self.assertContains(self.client.get(reverse('accounts:login')), reverse('accounts:password-reset'))
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_full_reset_flow(self):
        r = self.request_reset()
        self.assertRedirects(r, reverse('accounts:password-reset-done'))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual((message.to, message.subject), (['forgetful@example.com'], 'Reset your Sajhya Health password'))
        self.assertTrue(message.alternatives)  # HTML version too

        link = self.reset_link()
        step = self.client.get(link, follow=True)  # Django swaps the token into the session and redirects
        self.assertEqual(step.status_code, 200)
        self.assertContains(step, 'Choose a new password')
        form_url = step.redirect_chain[-1][0]
        done = self.client.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertRedirects(done, reverse('accounts:password-reset-complete'))

        self.assertFalse(self.client.login(username='forgetful', password=PASSWORD))  # old password is dead
        self.assertTrue(self.client.login(username='forgetful', password=NEW_PASSWORD))

    def test_link_works_only_once(self):
        self.request_reset()
        link = self.reset_link()
        first = self.client.get(link, follow=True)
        form_url = first.redirect_chain[-1][0]
        self.client.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        again = self.client_class().get(link, follow=True)
        self.assertContains(again, 'This link no longer works')

    def test_link_expires_after_an_hour(self):
        self.request_reset()
        link = self.reset_link()
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertContains(self.client.get(link, follow=True), 'This link no longer works')

    def test_tampered_link_is_rejected(self):
        self.request_reset()
        link = self.reset_link()
        bad = link[:-3] + ('aaa' if not link.endswith('aaa') else 'bbb')
        self.assertContains(self.client.get(bad, follow=True), 'This link no longer works')

    def test_weak_or_mismatched_passwords_are_rejected(self):
        self.request_reset()
        form_url = self.client.get(self.reset_link(), follow=True).redirect_chain[-1][0]
        for password, other in (('short', 'short'), ('12345678901', '12345678901'), (NEW_PASSWORD, 'different-Pass-1')):
            r = self.client.post(form_url, {'new_password1': password, 'new_password2': other})
            self.assertEqual(r.status_code, 200, password)
        self.assertTrue(self.client.login(username='forgetful', password=PASSWORD))  # unchanged

    def test_unknown_email_looks_identical_and_sends_nothing(self):
        r = self.request_reset('nobody@example.com')
        self.assertRedirects(r, reverse('accounts:password-reset-done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_email_match_ignores_case_and_inactive_accounts_get_nothing(self):
        self.request_reset('FORGETFUL@Example.COM')
        self.assertEqual(len(mail.outbox), 1)
        User.objects.filter(username='forgetful').update(is_active=False)
        self.request_reset()
        self.assertEqual(len(mail.outbox), 1)

    def test_requests_are_throttled_per_ip(self):
        for _ in range(5):
            self.assertEqual(self.request_reset().status_code, 302)
        blocked = self.request_reset()
        self.assertEqual(blocked.status_code, 429)
        self.assertContains(blocked, 'Too many requests', status_code=429)
        self.assertEqual(len(mail.outbox), 5)

    def test_a_mail_server_failure_is_swallowed_and_logged(self):
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='127.0.0.1', EMAIL_PORT=1):
            with self.assertLogs('django.contrib.auth', level='ERROR') as logs:
                r = self.request_reset()
        self.assertRedirects(r, reverse('accounts:password-reset-done'))
        self.assertTrue(any('Failed to send password reset email' in line for line in logs.output))

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_a_successful_reset_clears_the_sign_in_lockout(self):
        for _ in range(3):
            self.client.post(reverse('accounts:login'), {'username': 'forgetful', 'password': 'wrong'})
        self.assertEqual(self.client.post(reverse('accounts:login'), {'username': 'forgetful', 'password': PASSWORD}).status_code, 429)
        self.request_reset()
        form_url = self.client.get(self.reset_link(), follow=True).redirect_chain[-1][0]
        self.client.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        login = self.client.post(reverse('accounts:login'), {'username': 'forgetful', 'password': NEW_PASSWORD})
        self.assertEqual(login.status_code, 302)  # signed in, no longer locked

    def test_signup_requires_a_unique_email(self):
        profession = Profession.objects.first()
        r = self.client.post(reverse('accounts:signup', args=['professional', profession.pk]), {
            'first_name': 'Dup', 'last_name': 'Email', 'mobile': '98', 'title': 'PT', 'email': 'FORGETFUL@example.com',
            'username': 'dup', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='dup').exists())
        self.assertContains(r, 'already exists')


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user, _ = make_professional('changer')
        self.client.force_login(self.user)

    def test_change_password_while_signed_in(self):
        self.assertEqual(self.client.get(reverse('accounts:password-change')).status_code, 200)
        wrong = self.client.post(reverse('accounts:password-change'), {'old_password': 'nope', 'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertEqual(wrong.status_code, 200)
        r = self.client.post(reverse('accounts:password-change'), {'old_password': PASSWORD, 'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertRedirects(r, reverse('accounts:password-change-done'))
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)  # still signed in
        self.client.logout()
        self.assertTrue(self.client.login(username='changer', password=NEW_PASSWORD))

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:password-change')).status_code, 302)
