"""Render the main pages with the real database and take headless-Edge screenshots (wide and phone width) into a temp folder.
Usage (from the project root, venv active):  python scripts/qa_screenshots.py
Open the PNGs and look for overlaps, cut-off text, unreadable buttons, broken layouts."""
import os
import pathlib
import subprocess
import sys
import tempfile

import django

os.environ['DJANGO_SETTINGS_MODULE'] = 'sajhya_health.settings'
sys.path.insert(0, '.')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402

from accounts.models import Patient  # noqa: E402
from clinics.models import Clinic  # noqa: E402

setup_test_environment()
pro = User.objects.filter(account__profile__status='approved', is_active=True).first()
c = Client(HTTP_HOST='127.0.0.1')
c.force_login(pro)
pid = Patient.objects.filter(professional=pro.account.profile).first().pk
clinic = Clinic.objects.filter(owner=pro.account.profile).first()
pages = {
    'dashboard': '/accounts/dashboard/', 'patients': '/accounts/patients/', 'patient_soap': f'/accounts/patients/{pid}/?tab=soap', 'soap_form': f'/soapnotes/patients/{pid}/new/',
    'plan_builder': f'/accounts/patients/{pid}/plan/new/', 'reports': '/accounts/reports/', 'settings_plan': '/accounts/settings/?tab=plan', 'clinic_new': '/clinics/new/',
    'assess_choose': f'/assessments/patients/{pid}/new/', 'billing': '/billing/', 'hub': '/clinics/',
}
if clinic:
    pages['clinic_dash'] = f'/clinics/{clinic.pk}/'
    pages['clinic_patients'] = f'/clinics/{clinic.pk}/?tab=patients'

static = str(pathlib.Path('static').resolve()).replace('\\', '/')
out = pathlib.Path(tempfile.gettempdir()) / 'sajhya_qa'
out.mkdir(exist_ok=True)
edge = next((p for p in (r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe') if os.path.exists(p)), 'msedge')
for name, url in pages.items():
    resp = c.get(url)
    html = resp.content.decode().replace('/static/', f'file:///{static}/')
    page = out / f'{name}.html'
    page.write_text(html, encoding='utf-8')
    for width, height, tag in ((1366, 800, 'wide'), (520, 900, 'narrow')):
        subprocess.run([edge, '--headless=new', '--disable-gpu', f'--window-size={width},{height}', f'--screenshot={out / f"{name}_{tag}.png"}', page.as_uri()], capture_output=True)
    print(name, resp.status_code)
print('screenshots in', out)
