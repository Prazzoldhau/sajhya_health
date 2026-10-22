from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class SiteTests(TestCase):
    def test_landing_page_and_navigation(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse('accounts:package'))  # "Get Started" leads to the packages
        self.assertContains(r, reverse('accounts:login'))

    def test_health_check_reports_database_ok(self):
        r = self.client.get(reverse('healthz'))
        self.assertEqual((r.status_code, r.json()), (200, {'status': 'ok'}))

    def test_custom_error_pages(self):
        r = self.client.get('/no/such/page/')
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, 'could not find that page', status_code=404)

    def test_admin_requires_staff(self):
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_security_headers_present(self):
        r = self.client.get('/')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(r['X-Frame-Options'], 'DENY')


class ProductionSettingsTests(SimpleTestCase):
    """Run the settings module in a clean process with DEBUG off to prove it refuses an unsafe setup."""

    def run_settings(self, **env):
        import os
        import subprocess
        import sys
        from pathlib import Path
        base = Path(__file__).resolve().parent.parent
        clean = {k: v for k, v in os.environ.items() if k not in ('SECRET_KEY', 'DEBUG', 'ALLOWED_HOSTS', 'DATABASE_URL')}
        clean.update(env, DJANGO_SETTINGS_MODULE='sajhya_health.settings', ENV_FILE_DISABLED='1')
        # the project's .env is read relative to manage.py, so point at an empty directory copy of settings via a shim
        code = ("import environ, sys; environ.Env.read_env = staticmethod(lambda *a, **k: None); "
                "import sajhya_health.settings as s; print('OK')")
        return subprocess.run([sys.executable, '-c', code], cwd=base, env=clean, capture_output=True, text=True)

    def test_refuses_to_start_without_a_real_secret_key(self):
        r = self.run_settings(DEBUG='False', ALLOWED_HOSTS='example.com', DATABASE_URL='mysql://u:p@localhost/db')
        self.assertIn('SECRET_KEY', r.stderr)
        self.assertNotIn('OK', r.stdout)

    def test_refuses_to_start_without_allowed_hosts_or_database(self):
        key = 'x' * 60
        self.assertIn('ALLOWED_HOSTS', self.run_settings(DEBUG='False', SECRET_KEY=key, DATABASE_URL='mysql://u:p@localhost/db').stderr)
        self.assertIn('DATABASE_URL', self.run_settings(DEBUG='False', SECRET_KEY=key, ALLOWED_HOSTS='example.com').stderr)

    def test_starts_with_a_safe_configuration(self):
        r = self.run_settings(DEBUG='False', SECRET_KEY='k' * 60 + 'Z9', ALLOWED_HOSTS='example.com', DATABASE_URL='sqlite:///x.db')
        self.assertIn('OK', r.stdout, r.stderr)
