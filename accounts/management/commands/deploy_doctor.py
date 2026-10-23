"""Checks a server before (and during) a deployment and says in plain words what is wrong and what to do about it.

    python manage.py deploy_doctor

It never prints passwords or the secret key. Exit status 1 if anything must be fixed, so the deploy script stops before touching the database.
"""
import getpass
import os
import re
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError

OK, WARN, FAIL = 'OK  ', 'WARN', 'FAIL'


def raw_env_file(base_dir):
    """{name: value} exactly as written in .env (first occurrence wins, like the loader)."""
    path = Path(base_dir) / '.env'
    values = {}
    if not path.exists():
        return None
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)=(.*)$', line)
        if m and m.group(1) not in values:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            values[m.group(1)] = v
    return values


class Command(BaseCommand):
    help = 'Check the server configuration (settings file, database login, folders, virtual environment) and explain any problem.'

    def handle(self, *args, **options):
        results = []

        def report(level, text, hint=''):
            results.append(level)
            self.stdout.write(f'  [{level}] {text}')
            if hint:
                for line in hint.splitlines():
                    self.stdout.write(f'         -> {line}')

        base = Path(settings.BASE_DIR)
        account = getpass.getuser()
        self.stdout.write(f'Sajhya Health deploy doctor   (account: {account}, folder: {base})\n')

        # --- Python / virtual environment: the right one for THIS app?
        venv = os.environ.get('VIRTUAL_ENV', '') or sys.prefix
        app_name = base.name
        if f'/virtualenv/{app_name}/' in venv.replace('\\', '/') or settings.DEBUG:
            report(OK, f'Python {sys.version.split()[0]} in {venv}')
        elif '/virtualenv/' in venv.replace('\\', '/'):
            report(FAIL, f'This is another app\'s virtual environment: {venv}',
                   f'Packages would be installed into that other site. Use: source ~/virtualenv/{app_name}/<python version>/bin/activate')
        else:
            report(WARN, f'Python {sys.version.split()[0]} is not a cPanel app virtual environment ({venv})', f'Activate the one for this app: ls ~/virtualenv/{app_name}/')

        # --- the settings file
        raw = raw_env_file(base)
        if raw is None:
            report(FAIL, 'There is no .env file in the app folder.', 'Create it: cp .env.example .env   (only once!), then edit it with the cPanel File Manager.')
        else:
            mode = oct(os.stat(base / '.env').st_mode & 0o777)
            if os.name == 'posix' and (os.stat(base / '.env').st_mode & 0o077):
                report(WARN, f'.env can be read by other accounts (mode {mode}).', 'Run: chmod 600 .env')
            else:
                report(OK, f'.env found (mode {mode}).')
            for key in ('DATABASE_URL', 'SECRET_KEY', 'ALLOWED_HOSTS', 'DEBUG'):
                shell = os.environ.get(key)
                if key in raw and shell is not None and shell != raw[key]:
                    report(FAIL, f'The environment variable {key} overrides the value in .env.',
                           'It comes from cPanel > Setup Python App > Environment variables (or your shell). Delete it there, then run:\n'
                           'deactivate; source ~/virtualenv/<app>/<version>/bin/activate   (open a new Terminal tab if needed)')
            if sum(1 for line in (base / '.env').read_text(encoding='utf-8', errors='replace').splitlines() if line.lstrip().startswith('DATABASE_URL=')) > 1:
                report(FAIL, 'DATABASE_URL appears more than once in .env.', 'Only the first one is used. Delete the others.')

        # --- core settings
        if settings.DEBUG:
            report(WARN, 'DEBUG is on.', 'Production must have DEBUG=False in .env.')
        else:
            report(OK, 'DEBUG is off.')
        hosts = [h for h in settings.ALLOWED_HOSTS]
        report(OK if hosts else FAIL, f'ALLOWED_HOSTS: {", ".join(hosts) or "(empty)"}', '' if hosts else 'Set ALLOWED_HOSTS=app.sajhya.com in .env')
        report(OK if len(settings.SECRET_KEY) >= 40 else FAIL, f'SECRET_KEY is {len(settings.SECRET_KEY)} characters long.',
               '' if len(settings.SECRET_KEY) >= 40 else 'It must be 40+ random characters: python -c "import secrets; print(secrets.token_urlsafe(60))"')
        if not settings.DEBUG and not getattr(settings, 'CSRF_TRUSTED_ORIGINS', []):
            report(WARN, 'CSRF_TRUSTED_ORIGINS is empty.', 'Behind HTTPS set CSRF_TRUSTED_ORIGINS=https://app.sajhya.com or forms will fail with 403.')

        # --- database: show what we resolved, then really try to connect
        db = settings.DATABASES['default']
        engine = db['ENGINE'].rsplit('.', 1)[-1]
        if engine == 'mysql':
            user, name, host = db.get('USER', ''), db.get('NAME', ''), db.get('HOST', '')
            self.stdout.write(f'  [info] database: user={user!r} name={name!r} host={host!r}')
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1')
                report(OK, 'The database accepts the login.')
                cursor_names = connection.introspection.table_names()
                report(OK, f'The database has {len(cursor_names)} tables.' + (' (empty: the first migrate will create them)' if not cursor_names else ''))
            except OperationalError as exc:
                code = exc.args[0] if exc.args else 0
                prefix = account + '_'
                hints = []
                if not user.startswith(prefix):
                    hints.append(f'The user name {user!r} has no "{prefix}" in front. cPanel always adds your account name: it is probably {prefix}{user}.')
                if not name.startswith(prefix):
                    hints.append(f'The database name {name!r} has no "{prefix}" in front: it is probably {prefix}{name}.')
                if code == 1045:
                    hints += ['Wrong user or password. Check MySQL Databases > Current Users, and that the password in .env is the one set there (letters and digits only avoids quoting problems).',
                              'Also make sure the user is added to the database: MySQL Databases > Add User To Database > ALL PRIVILEGES.']
                elif code == 1049:
                    hints.append('That database does not exist: look in MySQL Databases > Current Databases for its exact name.')
                elif code in (2002, 2003):
                    hints.append('Cannot reach the database server: the host in DATABASE_URL should be localhost.')
                report(FAIL, f'Cannot log in to the database (MySQL error {code}).', '\n'.join(hints))
        else:
            report(WARN if not settings.DEBUG else OK, f'The database is {engine}, not MySQL.', 'Production should use DATABASE_URL=mysql://...')

        # --- folders the app writes to
        private = Path(settings.PRIVATE_MEDIA_ROOT)
        for label, folder in (('PRIVATE_MEDIA_ROOT (credentials, patient photos)', private), ('media/ (public pictures)', Path(settings.MEDIA_ROOT)), ('logs/', base / 'logs')):
            try:
                folder.mkdir(parents=True, exist_ok=True)
                probe = folder / '.write_test'
                probe.write_text('x')
                probe.unlink()
                report(OK, f'{label} is writable: {folder}')
            except OSError as exc:
                report(FAIL, f'{label} is not writable: {folder} ({exc.strerror})', 'Create it and make sure your account owns it.')
        if not settings.DEBUG and str(private).startswith(str(base)):
            report(WARN, 'PRIVATE_MEDIA_ROOT is inside the app folder.', 'Better outside it, e.g. PRIVATE_MEDIA_ROOT=/home2/<account>/sajhya_private')

        # --- cPanel gotchas
        wsgi = base / 'passenger_wsgi.py'
        if wsgi.exists() and 'imp.load_source' in wsgi.read_text(encoding='utf-8', errors='replace'):
            report(FAIL, 'passenger_wsgi.py is cPanel\'s template (it uses "imp", which Python 3.12 does not have).', 'Restore ours: git checkout -- passenger_wsgi.py   then restart the app.')
        elif wsgi.exists():
            report(OK, 'passenger_wsgi.py is the project\'s own file.')
        if os.name == 'posix':
            if '/repositories/' in str(base):
                report(FAIL, 'The app folder is inside ~/repositories/.', 'cPanel makes that folder private and the web server cannot start the app there. Use the Application root folder (~/sajhya_health).')
            elif os.stat(base).st_mode & 0o005 == 0:
                report(FAIL, f'The app folder is closed to the web server (mode {oct(os.stat(base).st_mode & 0o777)}).', f'Run: chmod 755 {base}')
            else:
                report(OK, 'The app folder can be entered by the web server.')

        failed = results.count(FAIL)
        warned = results.count(WARN)
        self.stdout.write('')
        if failed:
            self.stdout.write(self.style.ERROR(f'{failed} problem(s) must be fixed before deploying ({warned} warning(s)). Fix the FAIL lines above and run it again.'))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(f'Everything needed for a deploy looks right ({warned} warning(s)).'))
