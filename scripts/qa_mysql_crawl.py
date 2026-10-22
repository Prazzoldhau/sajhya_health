"""GET-crawl every route as a professional, a client and staff against the REAL database (MySQL) and report any 500.
Usage (project root, venv active):  python scripts/qa_mysql_crawl.py   - read-only apart from "recent patients" touches."""
import os, re, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'sajhya_health.settings'
sys.path.insert(0, '.')
django.setup()
from django.conf import settings
print('DB engine:', settings.DATABASES['default']['ENGINE'])
from django.test import Client
from django.test.utils import setup_test_environment
setup_test_environment()
from django.contrib.auth.models import User
from accounts.models import Patient, TreatmentPlan, Account
from sajhya_health.test_qa import project_routes

pro = User.objects.filter(account__profile__status='approved', is_active=True).first()
client_user = User.objects.filter(account__account_type='client').first()
staff = User.objects.filter(is_staff=True).first()
print('users:', pro, client_user, staff)
patients = list(Patient.objects.filter(professional=pro.account.profile).values_list('pk', flat=True)[:3]) if pro else []
ids = patients + [1, 2, 3]
results = {}
bad = []
for who, user in (('pro', pro), ('client', client_user), ('staff', staff)):
    if not user:
        continue
    c = Client(HTTP_HOST='127.0.0.1', raise_request_exception=False)
    c.force_login(user)
    n = 0
    for route, path in project_routes():
        if 'logout' in route or 'admin/' in route:
            continue
        for pid in (ids if '/1' in path or 'x' in path else [None]):
            url = path if pid is None else re.sub(r'/1(?=/|$)', f'/{pid}', path)
            try:
                status = c.get(url).status_code
            except Exception as error:
                status = f'EXC {type(error).__name__}: {str(error)[:150]}'
            n += 1
            if isinstance(status, str) or status >= 500:
                bad.append(f'{who} GET {url} -> {status}')
    results[who] = n
# extra: tabs and report variants on a real patient
if pro and patients:
    c = Client(HTTP_HOST='127.0.0.1', raise_request_exception=False); c.force_login(pro)
    extras = [f'/accounts/patients/{patients[0]}/?tab={t}' for t in ('overview', 'soap', 'plan', 'exercises', 'visits', 'billing', 'notes', 'documents', 'assessments', 'profile')]
    extras += [f'/accounts/patients/{patients[0]}/?tab=profile&section={s}' for s in ('general', 'medicine', 'nursing', 'aids', 'rehab', 'labs')]
    extras += ['/accounts/reports/?period=month', '/accounts/reports/?period=week', '/accounts/reports/?period=custom&start=2026-01-01&end=2026-12-31', '/accounts/reports/?export=csv',
               '/accounts/settings/?tab=plan', '/accounts/patients/?q=a&status=active&age=adult&sort=name', '/accounts/appointments/?days=7', '/billing/?date=2026-10-01', '/exercises/?q=knee', '/clinics/']
    for url in extras:
        status = c.get(url).status_code
        if status >= 500:
            bad.append(f'pro GET {url} -> {status}')
print('requests:', results)
print('PROBLEMS:' if bad else 'no 500s')
for b in bad[:40]:
    print(' ', b)
