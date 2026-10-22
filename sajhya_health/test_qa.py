"""Quality-assurance tests that sweep the whole site rather than one feature. They exist to catch what individual feature tests miss:

* every URL pattern, hit as an anonymous visitor, a Client (patient) account, an unapproved professional, an approved professional
  and staff - nothing may crash (500), and nothing private may answer anonymous visitors;
* every internal link on the main pages leads somewhere;
* hostile text (HTML/JS in names and notes) is escaped everywhere it is shown;
* state-changing URLs refuse GET; pages stay within a sane number of database queries (N+1 guard);
* awkward data (Nepali script, emoji, very long text, empty database) renders.

When you add a URL, this file tells you if it is public (add it to PUBLIC_WHEN_ANONYMOUS on purpose) or forgot its login check.
"""
import datetime
import re

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from accounts.models import Account, Appointment, Patient, Visit
from accounts.tests.helpers import PASSWORD, make_patient, make_professional

# Pages an anonymous visitor may open (GET -> 200). Anything else must redirect to sign-in, or answer 403/404/405.
PUBLIC_WHEN_ANONYMOUS = {
    '', 'healthz/', 'accounts/package/', 'accounts/login/', 'accounts/signup/client/', 'accounts/password/forgot/', 'accounts/password/forgot/sent/',
    'accounts/password/reset/done/', 'marketplace/', 'marketplace/cart/', 'marketplace/pharmacy/', 'marketplace/pharmacy/cart/', 'lab-tests/',
    'accounts/signup/professional/', 'accounts/signup/enterprise/', 'accounts/password/forgot/limited/',
    'accounts/password/reset/<uidb64>/<token>/',  # shows "this link no longer works" for a bad token
}
SKIP_PREFIXES = ('admin/', 'static/', 'media/', 'favicon')
# URLs that redirect after doing something are fine for anonymous users as long as they never return data
STATE_CHANGING = re.compile(r'(delete|remove|revoke|unlink|logout|toggle|action|invite|claim|leave|respond|add|create|save|update|publish|status|result|photo|visit|note|cancel|reschedule|attend|queue|feedback|done|link)')


def iter_patterns(patterns=None, prefix=''):
    """(route string, view name or None) for every URL pattern in the project."""
    for pattern in (patterns if patterns is not None else get_resolver().url_patterns):
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from iter_patterns(pattern.url_patterns, route)
        elif isinstance(pattern, URLPattern):
            yield route, pattern


def concrete(route):
    """A requestable path: <int:x> -> 1, <str:x> -> 'x', <slug:x> -> 'x'. Regex routes are skipped."""
    if '(?P' in route or '^' in route or '$' in route:
        return None
    path = re.sub(r'<int:[^>]+>', '1', route)
    path = re.sub(r'<(?:str|slug|path):[^>]+>', 'x', path)
    return '/' + path


def project_routes():
    seen = set()
    for route, pattern in iter_patterns():
        if route.startswith(SKIP_PREFIXES):
            continue
        path = concrete(route)
        if path and path not in seen:
            seen.add(path)
            yield route, path


class World(TestCase):
    """One of everything, so detail pages have something to show."""

    @classmethod
    def setUpTestData(cls):
        call_command('load_scales', verbosity=0)
        cls.staff = User.objects.create_superuser('qa_admin', 'a@example.com', PASSWORD)
        cls.pro_user, cls.pro = make_professional('qa_pro')
        cls.pending_user, cls.pending = make_professional('qa_pending', status='submitted')
        cls.client_user = User.objects.create_user('qa_client', 'c@example.com', PASSWORD)
        Account.objects.create(user=cls.client_user, account_type=Account.CLIENT)
        cls.patient = make_patient(cls.pro, 'Qa Patient', phone='9841000001')
        Visit.objects.create(patient=cls.patient, date=timezone.localdate(), therapist='QA')

    def login(self, user):
        c = self.client_class(raise_request_exception=False)
        c.force_login(user)
        return c


class UrlSweepTests(World):
    def test_every_url_survives_every_kind_of_visitor(self):
        """GET and POST every route with placeholder ids as five kinds of visitor: nothing may answer 500."""
        visitors = {'anonymous': self.client_class(raise_request_exception=False), 'client': self.login(self.client_user), 'pending': self.login(self.pending_user),
                    'professional': self.login(self.pro_user), 'staff': self.login(self.staff)}
        crashes, count = [], 0
        for route, path in project_routes():
            for who, c in visitors.items():
                for method in ('get', 'post'):
                    try:
                        status = getattr(c, method)(path).status_code
                    except Exception as error:  # noqa: BLE001 - a raised exception is a crash too
                        status = f'EXC {type(error).__name__}: {error}'
                    count += 1
                    if isinstance(status, str) or status >= 500:
                        crashes.append(f'{who} {method.upper()} {path} -> {status}')
        self.assertGreater(count, 500)
        self.assertEqual(crashes, [], '\n'.join(crashes[:25]))

    def test_anonymous_visitors_only_get_the_public_pages(self):
        anonymous = self.client_class(raise_request_exception=False)
        leaks = []
        for route, path in project_routes():
            if route in PUBLIC_WHEN_ANONYMOUS or path.startswith('/marketplace/product/') or '/product/' in path:
                continue
            response = anonymous.get(path)
            if response.status_code == 200:
                leaks.append(f'{path} answers anonymous visitors (200) - add a login check, or list it in PUBLIC_WHEN_ANONYMOUS on purpose')
        self.assertEqual(leaks, [], '\n'.join(leaks))

    def test_workspace_urls_are_closed_to_clients_and_unapproved_professionals(self):
        workspace = ['/accounts/dashboard/', '/accounts/patients/', '/accounts/appointments/', '/accounts/plans/', '/accounts/reports/', '/accounts/settings/',
                     '/billing/', '/billing/packages/', '/exercises/', '/clinics/', f'/accounts/patients/{self.patient.pk}/', f'/soapnotes/patients/{self.patient.pk}/new/',
                     f'/assessments/patients/{self.patient.pk}/new/', f'/profiles/patients/{self.patient.pk}/general/']
        for who, user in (('client', self.client_user), ('pending', self.pending_user)):
            c = self.login(user)
            for path in workspace:
                status = c.get(path).status_code
                self.assertIn(status, (302, 403, 404), f'{who} got {status} on {path}')
        pro = self.login(self.pro_user)
        for path in workspace:
            self.assertEqual(pro.get(path).status_code, 200, path) if '/general/' not in path else None

    def test_a_get_request_never_changes_data(self):
        """Hit every route with GET as a professional (and staff): no row may be created, deleted or altered. This catches a delete /
        toggle / status endpoint that forgot to require POST, which a stray link or image tag could then trigger."""
        from django.apps import apps
        from django.db import models as dj_models

        def snapshot():
            data = {}
            for model in apps.get_models():
                if model._meta.app_label in ('sessions', 'admin', 'axes', 'contenttypes', 'auth') and model is not User:
                    continue
                fields = [f.attname for f in model._meta.concrete_fields if not isinstance(f, (dj_models.DateTimeField, dj_models.DateField)) or f.name == 'date']
                data[model.__name__] = sorted(map(str, model.objects.values_list(*fields)))
            return data

        before = snapshot()
        for who in (self.pro_user, self.staff, self.client_user):
            c = self.login(who)
            for route, path in project_routes():
                if 'logout' not in route:
                    c.get(path)
        after = snapshot()
        lazy_defaults = {'PatientAllowance', 'PatientProfile'}  # blank settings rows created the first time a page needs them (idempotent)
        changed = [name for name in before if before[name] != after[name] and name not in lazy_defaults]
        self.assertEqual(changed, [], f'GET requests changed data in: {changed}')


class LinkSweepTests(World):
    def internal_links(self, html):
        for href in re.findall(r'href="([^"#]+)"', html):
            if href.startswith(('http', 'mailto:', 'tel:', 'javascript:', '//')) or '{{' in href or href.startswith(('/static/', '/media/', '/admin/')):
                continue
            if href.startswith('/') or href.startswith('?'):
                yield href

    def test_no_broken_links_on_the_main_pages(self):
        c = self.login(self.pro_user)
        pid = self.patient.pk
        pages = ['/accounts/dashboard/', '/accounts/patients/', '/accounts/appointments/', '/accounts/plans/', '/accounts/reports/', '/accounts/settings/', '/billing/',
                 '/billing/packages/', '/exercises/', '/clinics/', f'/accounts/patients/{pid}/', f'/accounts/patients/{pid}/?tab=soap',
                 f'/accounts/patients/{pid}/?tab=assessments', f'/accounts/patients/{pid}/?tab=exercises', f'/accounts/patients/{pid}/?tab=profile',
                 '/accounts/settings/?tab=plan']
        broken, checked = [], set()
        for page in pages:
            html = c.get(page).content.decode()
            for href in self.internal_links(html):
                url = page.split('?')[0] + href if href.startswith('?') else href
                if url in checked or 'logout' in url:
                    continue
                checked.add(url)
                status = c.get(url).status_code
                if status >= 400 and status != 405:
                    broken.append(f'{page} -> {url} ({status})')
        self.assertGreater(len(checked), 30)
        self.assertEqual(broken, [], '\n'.join(broken[:25]))

    def test_public_pages_have_working_links(self):
        c = self.client_class(raise_request_exception=False)
        broken = []
        for page in ('/', '/accounts/package/', '/accounts/login/', '/marketplace/', '/marketplace/pharmacy/', '/lab-tests/'):
            html = c.get(page).content.decode()
            for href in self.internal_links(html):
                url = page.split('?')[0] + href if href.startswith('?') else href
                status = c.get(url).status_code
                if status >= 400 and not url.startswith(('/accounts/signup/client', '/accounts/password')):
                    broken.append(f'{page} -> {url} ({status})')
        self.assertEqual(broken, [], '\n'.join(broken[:25]))

    def test_the_patient_dashboard_links_work(self):
        c = self.login(self.client_user)
        for page in ('/portal/', '/portal/plan/', '/portal/exercises/', '/portal/advice/', '/portal/services/', '/portal/orders/', '/portal/lab/', '/portal/settings/'):
            html = c.get(page).content.decode()
            for href in self.internal_links(html):
                if 'logout' in href:
                    continue
                self.assertLess(c.get(href).status_code, 400, f'{page} -> {href}')


class HostileTextTests(World):
    """HTML and script injected into every free-text field must come out escaped on every page that shows it."""
    PAYLOAD = '"><script>alert("xss")</script><img src=x onerror=alert(1)>'

    def assert_escaped(self, response, where):
        body = response.content.decode()
        self.assertNotIn('<script>alert("xss")', body, f'unescaped script on {where}')
        self.assertNotIn('<img src=x onerror', body, f'unescaped tag on {where}')

    def test_patient_and_clinical_text_is_escaped_everywhere(self):
        from clinics.models import Clinic, ClinicSubscription
        from exercises.models import Prescription, PrescriptionExercise
        from soapnotes.models import SoapNote
        from accounts.models import TreatmentPlan
        evil = self.PAYLOAD
        patient = make_patient(self.pro, evil, phone='9841000002', diagnosis=evil, address=evil, notes=evil)
        SoapNote.objects.create(patient=patient, author=self.pro, author_name=evil, chief_complaint=evil, history=evil, impression=evil, hep=evil, precautions=evil,
                                rom=[{'movement': evil, 'side': '', 'active': evil, 'passive': '', 'pain': False, 'note': evil}], status='final',
                                measures=[{'name': evil, 'unit': evil, 'baseline': '1', 'target': '2'}], goals=[{'text': evil, 'term': 'short', 'target_date': ''}])
        plan = TreatmentPlan.objects.create(patient=patient, professional=self.pro, title=evil, diagnosis=evil, precautions=evil, education=evil, status='active')
        rx = Prescription.objects.create(patient=patient, professional=self.pro, condition_label=evil)
        PrescriptionExercise.objects.create(prescription=rx, exercise_name=evil)
        clinic = Clinic.objects.create(owner=self.pro, name=evil, short_bio=evil, phone='015550001', ward_street=evil, district=evil, website='')
        ClinicSubscription.objects.create(professional=self.pro, status='active')
        c = self.login(self.pro_user)
        pages = ['/accounts/dashboard/', '/accounts/patients/', f'/accounts/patients/{patient.pk}/', f'/accounts/patients/{patient.pk}/?tab=soap',
                 f'/accounts/patients/{patient.pk}/?tab=exercises', f'/accounts/patients/{patient.pk}/?tab=plan', f'/accounts/patients/{patient.pk}/?tab=profile',
                 f'/accounts/patients/{patient.pk}/edit/', f'/accounts/plans/{plan.pk}/', f'/accounts/plans/{plan.pk}/edit/', f'/soapnotes/{SoapNote.objects.get().pk}/',
                 '/clinics/', f'/clinics/{clinic.pk}/', f'/clinics/{clinic.pk}/?tab=settings', '/accounts/reports/', '/exercises/', '/accounts/settings/']
        for page in pages:
            self.assert_escaped(c.get(page), page)

    def test_patient_dashboard_and_storefront_text_is_escaped(self):
        from marketplace.models import Order
        Order.objects.create(order_type='marketplace', user=self.client_user, customer_name=self.PAYLOAD, customer_email='e@example.com', customer_phone='1',
                             delivery_address=self.PAYLOAD, notes=self.PAYLOAD, total_amount=10)
        c = self.login(self.client_user)
        for page in ('/portal/', '/portal/orders/', '/portal/settings/'):
            self.assert_escaped(c.get(page), page)
        order = Order.objects.get()
        self.assert_escaped(c.get(reverse('marketplace:order-success', args=[order.order_number])), 'order-success')

    def test_hostile_text_survives_a_save_round_trip_through_the_forms(self):
        c = self.login(self.pro_user)
        r = c.post(reverse('accounts:patient-add'), {'name': self.PAYLOAD, 'date_of_birth': '1990-01-01', 'gender': 'F', 'phone': '9841000003', 'diagnosis': self.PAYLOAD})
        patient = Patient.objects.get(name=self.PAYLOAD)
        for tab in ('overview', 'visits', 'notes', 'documents'):
            self.assert_escaped(c.get(f'/accounts/patients/{patient.pk}/?tab={tab}'), tab)
        self.assert_escaped(c.get('/accounts/patients/', {'q': self.PAYLOAD}), 'search echo')
        self.assert_escaped(c.get('/marketplace/', {'search': self.PAYLOAD}), 'store search echo')
        self.assert_escaped(self.client_class().get('/lab-tests/', {'search': self.PAYLOAD}), 'lab search echo')


class DataEdgeTests(World):
    def test_nepali_emoji_and_long_text(self):
        c = self.login(self.pro_user)
        name = 'सीता गुरुङ 🌿'
        r = c.post(reverse('accounts:patient-add'), {'name': name, 'date_of_birth': '1990-02-28', 'gender': 'F', 'phone': '9841000004', 'address': 'काठमाडौं, ' * 40,
                                                       'diagnosis': 'पिठ्यूँको दुखाइ', 'notes': 'x' * 5000})
        patient = Patient.objects.get(phone='9841000004')
        self.assertEqual(patient.name, name)
        for tab in ('overview', 'soap', 'plan', 'exercises', 'visits', 'billing', 'notes', 'documents', 'assessments', 'profile'):
            response = c.get(f'/accounts/patients/{patient.pk}/?tab={tab}')
            self.assertEqual(response.status_code, 200, tab)
        self.assertContains(c.get('/accounts/patients/', {'q': 'सीता'}), name)

    def test_over_long_values_are_rejected_not_crashed(self):
        c = self.login(self.pro_user)
        r = c.post(reverse('accounts:patient-add'), {'name': 'N' * 500, 'date_of_birth': '1990-01-01', 'gender': 'F', 'phone': '9' * 60})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Patient.objects.filter(name__startswith='NNNN').exists())

    def test_weird_dates_and_ages(self):
        c = self.login(self.pro_user)
        for dob in ('2000-02-29', '1900-01-01', timezone.localdate().isoformat()):
            r = c.post(reverse('accounts:patient-add'), {'name': f'Born {dob}', 'date_of_birth': dob, 'gender': 'M', 'phone': '9841000005'})
            self.assertIn(r.status_code, (200, 302), dob)
        future = (timezone.localdate() + datetime.timedelta(days=30)).isoformat()
        r = c.post(reverse('accounts:patient-add'), {'name': 'Future Baby', 'date_of_birth': future, 'gender': 'M', 'phone': '9841000006'})
        self.assertFalse(Patient.objects.filter(name='Future Baby').exists(), 'a date of birth in the future must be refused')
        self.assertEqual(c.get('/accounts/patients/').status_code, 200)

    def test_empty_world_renders_every_main_page(self):
        user, profile = make_professional('qa_empty')
        c = self.login(user)
        for page in ('/accounts/dashboard/', '/accounts/patients/', '/accounts/appointments/', '/accounts/plans/', '/accounts/reports/', '/accounts/reports/?period=week',
                     '/accounts/reports/?period=custom', '/billing/', '/billing/packages/', '/exercises/', '/clinics/', '/accounts/settings/', '/accounts/settings/?tab=plan'):
            self.assertEqual(c.get(page).status_code, 200, page)

    def test_report_periods_with_odd_input(self):
        c = self.login(self.pro_user)
        for params in ({'period': 'month', 'month': '2026-13'}, {'period': 'month', 'month': 'abc'}, {'period': 'week', 'date': '31/12/2026'}, {'period': 'custom', 'start': '2026-12-31', 'end': '2026-01-01'},
                       {'period': 'custom', 'start': '1900-01-01', 'end': '2999-01-01'}, {'period': 'x'}):
            self.assertEqual(c.get('/accounts/reports/', params).status_code, 200, params)
            self.assertEqual(c.get('/accounts/reports/', {**params, 'export': 'csv'}).status_code, 200, params)


class QueryBudgetTests(World):
    """Fail if a page's query count balloons with the amount of data (an N+1 slipped in)."""

    def build(self, patients=25):
        from exercises.models import Prescription, PrescriptionExercise
        from soapnotes.models import SoapNote
        for i in range(patients):
            p = make_patient(self.pro, f'Bulk {i}', phone=f'98410{i:05d}', last_visit=timezone.localdate())
            Visit.objects.create(patient=p, date=timezone.localdate(), therapist='QA')
            SoapNote.objects.create(patient=p, author=self.pro, author_name='QA', chief_complaint='c', measures=[], goals=[])
        rx = Prescription.objects.create(patient=self.patient, professional=self.pro)
        for i in range(8):
            PrescriptionExercise.objects.create(prescription=rx, exercise_name=f'Ex {i}')

    def queries(self, c, url):
        with CaptureQueriesContext(connection) as ctx:
            response = c.get(url)
        self.assertEqual(response.status_code, 200, url)
        return len(ctx)

    def test_pages_stay_within_their_query_budget(self):
        self.build()
        c = self.login(self.pro_user)
        budget = {'/accounts/dashboard/': 40, '/accounts/patients/': 35, '/accounts/patients/?page=3': 35, '/accounts/appointments/': 40, '/accounts/reports/': 60,
                  f'/accounts/patients/{self.patient.pk}/': 45, f'/accounts/patients/{self.patient.pk}/?tab=exercises': 45, f'/accounts/patients/{self.patient.pk}/?tab=soap': 40,
                  '/billing/': 40, '/exercises/': 40, '/clinics/': 40}
        over = {url: n for url, limit in budget.items() if (n := self.queries(c, url)) > limit}
        self.assertEqual(over, {}, f'query budget exceeded (url: queries): {over}')

    def test_patient_list_query_count_does_not_grow_with_the_number_of_patients(self):
        c = self.login(self.pro_user)
        small = self.queries(c, '/accounts/patients/')
        self.build(40)
        large = self.queries(c, '/accounts/patients/')
        self.assertLessEqual(large, small + 3, f'patients page went from {small} to {large} queries: N+1')


class DeployChecklistTests(TestCase):
    def test_migrations_are_complete(self):
        """Every model change has its migration (otherwise deploy breaks on the server's database)."""
        from io import StringIO
        out = StringIO()
        try:
            call_command('makemigrations', '--check', '--dry-run', stdout=out, stderr=out)
        except SystemExit:
            self.fail('Models changed without a migration:\n' + out.getvalue())

    def test_error_pages_render_and_leak_nothing(self):
        c = self.client_class(raise_request_exception=False)
        missing = c.get('/definitely-not-a-page/')
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn('Traceback', missing.content.decode())
        self.assertEqual(c.get('/healthz/').status_code, 200)

    def test_health_check_and_security_headers(self):
        response = self.client.get('/')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertNotIn('Server', response.headers.get('X-Powered-By', ''))


class ThrottleTests(TestCase):
    """Public forms are rate limited per IP (off in the normal test run, switched on here)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_guest_signups_are_limited(self):
        from django.test import override_settings
        with override_settings(THROTTLE_ENABLED=True):
            for i in range(12):
                self.client.post(reverse('accounts:signup-client'), {'username': f'bot{i}', 'email': f'bot{i}@example.com', 'password1': PASSWORD, 'password2': PASSWORD})
                self.client.logout()
        self.assertEqual(User.objects.filter(username__startswith='bot').count(), 10)

    def test_lab_bookings_and_orders_are_limited(self):
        from django.test import override_settings
        from lab.models import LabTest, LabTestRequest
        from marketplace.models import Order, PharmacyProduct
        test = LabTest.objects.create(name='CBC', price=400, category='blood')
        medicine = PharmacyProduct.objects.create(name='Paracetamol', price=30)
        form = {'customer_name': 'Ram', 'customer_email': 'r@example.com', 'customer_phone': '9800000000', 'delivery_address': 'Lalitpur'}
        with override_settings(THROTTLE_ENABLED=True):
            for _ in range(18):
                self.client.post(reverse('lab:tests'), {'items': [f'test-{test.pk}'], **form})
                self.client.post(reverse('marketplace:pharmacy-add-to-cart', args=[medicine.pk]), {'quantity': 1})
                self.client.post(reverse('marketplace:pharmacy-checkout'), form)
        self.assertEqual(LabTestRequest.objects.count(), 15)
        self.assertEqual(Order.objects.count(), 15)

    def test_the_limit_is_per_connection_not_global(self):
        from django.test import override_settings
        with override_settings(THROTTLE_ENABLED=True):
            for i in range(10):
                self.client.post(reverse('accounts:signup-client'), {'username': f'a{i}', 'email': f'a{i}@example.com', 'password1': PASSWORD, 'password2': PASSWORD})
                self.client.logout()
            other = self.client_class(REMOTE_ADDR='203.0.113.7')
            other.post(reverse('accounts:signup-client'), {'username': 'elsewhere', 'email': 'e@example.com', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertTrue(User.objects.filter(username='elsewhere').exists())
