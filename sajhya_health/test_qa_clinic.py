"""Sweeps for the clinic side of the site, added after the clinic login, front desk, advances, invoices and messages arrived.

test_qa.py sweeps the site as an anonymous visitor, a client, an unapproved and an approved professional and staff. This does the same as the
roles that came later - a clinic's own login and each kind of front-desk staff - with data in every new corner (bills, advances, packages,
messages, a staff-registered patient), so a crash, a leak or a GET that changes data shows up here instead of on a live clinic.
"""
import datetime
import pathlib
import re

from django.apps import apps
from django.contrib.auth.models import User
from django.db import models as dj_models
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.appointments import aware
from accounts.models import Appointment, MessageTemplate, Patient, Visit
from accounts.tests.helpers import PASSWORD, make_patient, make_professional
from billing.models import BillingEntry, PatientAdvance, PatientPackage
from clinics.models import Clinic, ClinicMember, ClinicSubscription, QueueEntry
from clinics.login import set_clinic_login, set_staff_login

from .test_qa import project_routes

EVIL = '"><script>alert("xss")</script><img src=x onerror=alert(1)>'


class ClinicWorld(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner_user, cls.owner = make_professional('cw_owner')
        ClinicSubscription.objects.create(professional=cls.owner, status='active')
        cls.clinic = Clinic.objects.create(owner=cls.owner, name='Sweep Clinic', phone='015550001', ward_street='Ward 1', district='Lalitpur')
        cls.clinic_user = set_clinic_login(cls.clinic, 'cw_clinic', PASSWORD)
        cls.clinic.refresh_from_db()
        cls.staff_users = {}
        for role in ('receptionist', 'assistant', 'manager', 'other'):
            member = ClinicMember.objects.create(clinic=cls.clinic, role=role, name=f'Sweep {role}', status=ClinicMember.ACTIVE)
            cls.staff_users[role] = set_staff_login(member, f'cw_{role}', PASSWORD)
        cls.receptionist = ClinicMember.objects.get(role='receptionist')
        cls.outsider_user, cls.outsider = make_professional('cw_outsider')
        # a patient the front desk registered (belongs to the owner, tagged to the clinic), with everything hanging off it
        cls.patient = make_patient(cls.owner, 'Desk Patient', phone='9841000123', clinic=cls.clinic, registered_by_name='Sweep receptionist', registered_by_role='Receptionist',
                                   messaging_app='viber', date_of_birth=datetime.date(1990, 1, 1), dob_is_estimate=True)
        Visit.objects.create(patient=cls.patient, date=timezone.localdate(), therapist='QA')
        QueueEntry.objects.create(clinic=cls.clinic, patient=cls.patient)
        today = timezone.localdate()
        start = aware(today + datetime.timedelta(days=1), datetime.time(10, 0))
        cls.appointment = Appointment.objects.create(professional=cls.clinic.workspace, patient=cls.patient, start=start, end=start + datetime.timedelta(hours=1))
        cls.bill = BillingEntry.objects.create(professional=cls.clinic.workspace, patient=cls.patient, patient_name='Desk Patient', rate=700, entry_date=today,
                                               created_by_name='Sweep receptionist', created_by_role='Receptionist')
        cls.bill.record_payment(300, 'cash')
        cls.bill.carry_over(100, 'cash')
        PatientAdvance.objects.create(patient=cls.patient, professional=cls.clinic.workspace, kind='deposit', amount=500, payment_mode='cash')
        cls.package = PatientPackage.objects.create(patient=cls.patient, professional=cls.clinic.workspace, duration='custom', custom_days=12, total_sessions=6,
                                                    total_amount=3000, start_date=today)
        MessageTemplate.objects.create(professional=cls.clinic.workspace, key='appointment_booked', title='x', body='Hi {patient} {date} {time} {contact}')
        MessageTemplate.objects.create(professional=cls.clinic.workspace, key='custom-abc12345', title='Notice', body='Closed on {date}', is_custom=True)

    def login(self, user):
        c = self.client_class(raise_request_exception=False)
        c.force_login(user)
        return c

    def visitors(self):
        people = {'clinic_login': self.clinic_user, 'owner': self.owner_user, 'outsider': self.outsider_user}
        people.update({f'staff_{role}': user for role, user in self.staff_users.items()})
        return {who: self.login(user) for who, user in people.items()}


class ClinicRoleSweepTests(ClinicWorld):
    def test_every_url_survives_the_clinic_login_and_every_kind_of_staff(self):
        crashes, count = [], 0
        for who, c in self.visitors().items():
            for route, path in project_routes():
                for method in ('get', 'post'):
                    try:
                        status = getattr(c, method)(path).status_code
                    except Exception as error:  # noqa: BLE001 - a raised exception is a crash too
                        status = f'EXC {type(error).__name__}: {error}'
                    count += 1
                    if isinstance(status, str) or status >= 500:
                        crashes.append(f'{who} {method.upper()} {path} -> {status}')
        self.assertGreater(count, 1000)
        self.assertEqual(crashes, [], '\n'.join(crashes[:25]))

    def test_real_ids_work_for_the_pages_staff_and_the_clinic_use(self):
        """The sweep above uses id 1 for everything; this uses the real rows so the pages are fully rendered."""
        pid, bid, cid = self.patient.pk, self.bill.pk, self.clinic.pk
        clinic_pages = ['/accounts/dashboard/', '/accounts/patients/', f'/accounts/patients/{pid}/', f'/accounts/patients/{pid}/?tab=billing', f'/accounts/patients/{pid}/?tab=visits',
                        f'/accounts/patients/{pid}/edit/', '/accounts/appointments/', '/accounts/messages/', '/accounts/messages/send/?audience=all', '/accounts/reports/',
                        '/billing/', '/billing/?patient=%d' % pid, '/billing/packages/', '/billing/advances/', f'/billing/entry/{bid}/invoice/', f'/billing/entry/{bid}/invoice.pdf',
                        f'/billing/entry/{bid}/invoice.png', f'/clinics/{cid}/', f'/clinics/{cid}/?tab=team', f'/clinics/{cid}/?tab=patients', f'/clinics/{cid}/?tab=queue',
                        f'/clinics/{cid}/?tab=settings', '/clinics/']
        c = self.login(self.clinic_user)
        for page in clinic_pages:
            self.assertLess(c.get(page).status_code, 400, f'clinic login: {page}')
        for role in ('receptionist', 'manager'):
            c = self.login(self.staff_users[role])
            for tab in ('overview', 'queue', 'patients', 'register', 'billing', 'team'):
                status = c.get(reverse('clinics:desk'), {'tab': tab}).status_code
                self.assertEqual(status, 200, f'{role} desk {tab}')
        for role in ('assistant', 'other'):
            c = self.login(self.staff_users[role])
            self.assertEqual(c.get(reverse('clinics:desk')).status_code, 200, role)
            self.assertIn(c.get(reverse('clinics:desk'), {'tab': 'billing'}).status_code, (200,), role)  # falls back to a tab they may see
        self.assertNotContains(self.login(self.staff_users['assistant']).get(reverse('clinics:desk'), {'tab': 'billing'}), 'New bill')
        outsider = self.login(self.outsider_user)
        for page in (f'/accounts/patients/{pid}/', f'/billing/entry/{bid}/invoice/', f'/billing/entry/{bid}/invoice.pdf', f'/billing/entry/{bid}/invoice.png', f'/clinics/{cid}/'):
            self.assertEqual(outsider.get(page).status_code, 404, f'outsider: {page}')

    def test_staff_never_reach_the_clinical_workspace(self):
        pid = self.patient.pk
        for role, user in self.staff_users.items():
            c = self.login(user)
            pages = ['/accounts/dashboard/', '/accounts/patients/', f'/accounts/patients/{pid}/', f'/soapnotes/patients/{pid}/new/', '/accounts/messages/', '/accounts/reports/']
            if role not in ('receptionist', 'manager'):  # the two roles that bill use the billing pages; nobody else may
                pages.append('/billing/')
            for page in pages:
                self.assertIn(c.get(page).status_code, (302, 403, 404), f'{role} reached {page}')

    def test_a_get_request_never_changes_data_for_the_clinic_roles(self):
        def snapshot():
            data = {}
            for model in apps.get_models():
                if model._meta.app_label in ('sessions', 'admin', 'axes', 'contenttypes', 'auth') and model is not User:
                    continue
                fields = [f.attname for f in model._meta.concrete_fields if not isinstance(f, (dj_models.DateTimeField, dj_models.DateField)) or f.name == 'date']
                data[model.__name__] = sorted(map(str, model.objects.values_list(*fields)))
            return data

        before = snapshot()
        for who, c in self.visitors().items():
            for route, path in project_routes():
                if 'logout' not in route:
                    c.get(path)
        after = snapshot()
        lazy = {'PatientAllowance', 'PatientProfile', 'ClinicMonthlyUsage'}  # blank rows created the first time a page needs them (idempotent)
        changed = [name for name in before if before[name] != after[name] and name not in lazy]
        self.assertEqual(changed, [], f'GET requests changed data in: {changed}')


class ClinicHostileTextTests(ClinicWorld):
    def test_text_typed_by_staff_and_in_messages_is_escaped_where_it_is_shown(self):
        self.patient.name = EVIL
        self.patient.registered_by_name = EVIL
        self.patient.save()
        self.bill.patient_name, self.bill.service, self.bill.created_by_name, self.bill.notes = EVIL, EVIL, EVIL, EVIL
        self.bill.save()
        PatientAdvance.objects.create(patient=self.patient, professional=self.clinic.workspace, kind='deposit', amount=5, payment_mode='cash', notes=EVIL)
        MessageTemplate.objects.filter(key='custom-abc12345').update(title=EVIL, body=EVIL)
        self.clinic.name = EVIL
        self.clinic.save()
        pid, bid, cid = self.patient.pk, self.bill.pk, self.clinic.pk
        pages = {'clinic_login': ['/accounts/patients/', f'/accounts/patients/{pid}/', f'/accounts/patients/{pid}/?tab=billing', '/accounts/messages/', '/accounts/messages/send/?audience=all',
                                  '/billing/', f'/billing/?patient={pid}', '/billing/advances/', f'/billing/entry/{bid}/invoice/', '/accounts/appointments/', f'/clinics/{cid}/?tab=patients'],
                 'staff_receptionist': [f'/clinics/desk/?tab={t}' for t in ('overview', 'queue', 'patients', 'billing')]}
        for who, urls in pages.items():
            c = self.login(self.clinic_user if who == 'clinic_login' else self.staff_users['receptionist'])
            for url in urls:
                body = c.get(url).content.decode()
                self.assertNotIn('<script>alert("xss")', body, f'{who} {url}')
                self.assertNotIn('<img src=x onerror', body, f'{who} {url}')


class ScopeGuardTests(TestCase):
    """The clinic login sees patients registered under other people (the front desk registers them for the owner), so a list or a form
    that asks only for `profile.patients` or `Patient.objects.filter(professional=...)` silently hides them - the cause of several bugs. Use
    profile.workspace_patients() for lists and choices, accessible_patients() / own_patient() for opening one."""
    ALLOWED = {'accounts/access.py', 'accounts/models.py', 'billing/models.py'}  # where the scoping itself is defined, and the free-patient slot count
    PATTERN = re.compile(r'\bprofile\.patients\b|Patient\.objects\.filter\(\s*professional\s*=|\.professional\.patients\b')

    def test_no_view_or_form_scopes_patients_by_owner_alone(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in root.rglob('*.py'):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(('venv/', 'staticfiles/')) or '/tests' in rel or 'migrations/' in rel or rel.startswith(('sajhya_health/test', 'scripts/')) or rel.endswith('tests.py'):
                continue
            if rel in self.ALLOWED:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if self.PATTERN.search(line) and '# scope-ok' not in line:
                    offenders.append(f'{rel}:{number}: {line.strip()}')
        self.assertEqual(offenders, [], 'Use profile.workspace_patients() (or add "# scope-ok" with a reason):\n' + '\n'.join(offenders))
