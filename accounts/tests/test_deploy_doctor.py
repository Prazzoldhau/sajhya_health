import getpass
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db.utils import OperationalError
from django.test import SimpleTestCase, override_settings

MYSQL = {'default': {'ENGINE': 'django.db.backends.mysql', 'NAME': 'shealth', 'USER': 'suser', 'HOST': 'localhost', 'PORT': '3306'}}


def run(**kwargs):
    out = StringIO()
    code = 0
    try:
        call_command('deploy_doctor', stdout=out, **kwargs)
    except SystemExit as exit_:
        code = exit_.code
    return code, out.getvalue()


class DeployDoctorTests(SimpleTestCase):
    def test_passes_on_a_healthy_development_setup_and_never_prints_secrets(self):
        with override_settings(SECRET_KEY='k' * 60):
            code, text = run()
        self.assertIn('deploy doctor', text)
        self.assertNotIn('k' * 60, text)
        self.assertNotIn('FAIL', text.split('Everything needed')[0] if 'Everything needed' in text else '')

    def test_missing_account_prefix_is_explained_when_the_database_refuses_the_login(self):
        broken = mock.MagicMock()
        broken.cursor.side_effect = OperationalError(1045, "Access denied for user 'suser'@'localhost' (using password: YES)")
        with override_settings(DATABASES=MYSQL, DEBUG=False, ALLOWED_HOSTS=['app.sajhya.com'], SECRET_KEY='k' * 60), \
                mock.patch('accounts.management.commands.deploy_doctor.connection', broken):
            code, text = run()
        account = getpass.getuser()
        self.assertEqual(code, 1)
        self.assertIn('MySQL error 1045', text)
        self.assertIn(f'probably {account}_suser', text)
        self.assertIn(f'probably {account}_shealth', text)
        self.assertIn('Add User To Database', text)
        self.assertIn('problem(s) must be fixed', text)

    def test_unknown_database_and_unreachable_server_have_their_own_advice(self):
        for error, advice in ((OperationalError(1049, "Unknown database"), 'does not exist'), (OperationalError(2003, "Can't connect"), 'should be localhost')):
            broken = mock.MagicMock()
            broken.cursor.side_effect = error
            with override_settings(DATABASES=MYSQL, DEBUG=False, ALLOWED_HOSTS=['x'], SECRET_KEY='k' * 60), mock.patch('accounts.management.commands.deploy_doctor.connection', broken):
                code, text = run()
            self.assertEqual(code, 1)
            self.assertIn(advice, text)

    def test_a_short_secret_key_and_empty_hosts_are_failures(self):
        with override_settings(SECRET_KEY='short', ALLOWED_HOSTS=[], DEBUG=False):
            code, text = run()
        self.assertEqual(code, 1)
        self.assertIn('ALLOWED_HOSTS', text)
        self.assertIn('SECRET_KEY is 5 characters', text)

    def test_the_deploy_script_runs_the_doctor_first(self):
        from pathlib import Path
        script = (Path(__file__).resolve().parents[2] / 'deploy' / 'cpanel_deploy.sh').read_text(encoding='utf-8')
        self.assertLess(script.index('deploy_doctor'), script.index('Backing up the database'))
        self.assertIn('virtualenv/$APP_NAME', script)  # only the app's own virtualenv is used
