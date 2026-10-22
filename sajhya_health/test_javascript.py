"""Syntax-check every inline <script> block and our own static JS.

There is no browser in the test run, so a typo in a page script would otherwise only be found by clicking through the
site. This renders the real pages and parses their scripts with a pure-Python JavaScript parser (esprima, listed in
requirements-dev.txt). The test is skipped when esprima is not installed.
"""
import re
import unittest
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import TreatmentPlan
from accounts.tests.helpers import make_patient, make_professional

try:
    import esprima
except ImportError:  # pragma: no cover
    esprima = None

SCRIPT_RE = re.compile(r'<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>', re.S | re.I)


@unittest.skipIf(esprima is None, 'esprima is not installed (pip install -r requirements-dev.txt)')
class JavaScriptSyntaxTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.plan = TreatmentPlan.objects.create(patient=self.patient, professional=self.profile, title='P', status='active')
        self.plan.phases.create(name='Phase 1', week_start=1, week_end=2)

    def parse(self, url, client=None):
        response = (client or self.client).get(url)
        self.assertEqual(response.status_code, 200, url)
        html = response.content.decode()
        checked = 0
        for match in SCRIPT_RE.finditer(html):
            attrs, body = match.group('attrs'), match.group('body').strip()
            if 'src=' in attrs or 'json' in attrs.lower() or not body:  # external files, JSON data blocks, empty
                continue
            try:
                esprima.parseScript(body)
            except Exception as error:  # noqa: BLE001 - report which page and script failed
                self.fail(f'JavaScript syntax error in {url}: {error}\n--- script starts ---\n{body[:300]}')
            checked += 1
        return checked

    def test_inline_scripts_in_every_page_parse(self):
        pid = self.patient.pk
        public = ['/', reverse('accounts:package'), reverse('accounts:login'), reverse('accounts:password-reset'),
                  reverse('marketplace:marketplace'), reverse('marketplace:pharmacy'), reverse('lab:tests')]
        anonymous = self.client_class()
        total = sum(self.parse(u, anonymous) for u in public)
        urls = [reverse('accounts:dashboard'), reverse('accounts:patients'), reverse('accounts:appointments'), reverse('accounts:plans'),
                reverse('accounts:plan-new', args=[pid]), reverse('accounts:plan-detail', args=[self.plan.pk]), reverse('accounts:plan-edit', args=[self.plan.pk]),
                reverse('billing:billing'), reverse('billing:packages'), reverse('exercises:library'), reverse('accounts:patient-add')]
        urls += [f"{reverse('accounts:patient-detail', args=[pid])}?tab={t}" for t in ('overview', 'plan', 'exercises', 'visits', 'billing', 'notes', 'documents')]
        urls += [f"{reverse('accounts:patient-detail', args=[pid])}?tab=profile&section={s}" for s in ('general', 'medicine', 'nursing', 'aids', 'rehab', 'labs')]
        urls += [f"{reverse('accounts:patient-detail', args=[pid])}?tab=profile&section=rehab&therapy={t}" for t in ('occupational', 'speech', 'behavioural')]
        from django.core.management import call_command
        from assessments.models import AssessmentScale
        call_command('load_scales', verbosity=0)
        ids = ','.join(str(s.pk) for s in AssessmentScale.objects.filter(code__in=('berg', 'odi', 'tug')))
        urls += [f"{reverse('accounts:patient-detail', args=[pid])}?tab=assessments", reverse('assessments:choose', args=[pid]),
                 f"{reverse('assessments:fill', args=[pid])}?scales={ids}"]
        from soapnotes.models import SoapNote
        note = SoapNote.objects.create(patient=self.patient, author=self.profile, author_name='x', chief_complaint='JS note')
        urls += [f"{reverse('accounts:patient-detail', args=[pid])}?tab=soap", reverse('soapnotes:new', args=[pid]), reverse('soapnotes:edit', args=[note.pk]), reverse('soapnotes:detail', args=[note.pk])]
        from clinics.models import Clinic, ClinicSubscription
        ClinicSubscription.objects.create(professional=self.profile, status='active')
        clinic = Clinic.objects.create(owner=self.profile, name='JS Clinic', phone='015550001', province='Bagmati', district='Lalitpur')
        urls += [reverse('clinics:hub'), reverse('clinics:create')]
        urls += [f"{reverse('clinics:detail', args=[clinic.pk])}?tab={t}" for t in ('overview', 'team', 'patients', 'queue', 'settings')]
        total += sum(self.parse(u) for u in urls)
        self.assertGreater(total, 20)  # the pages really do carry scripts, so this is not vacuously passing

    def test_static_javascript_files_parse(self):
        files = list((Path(settings.BASE_DIR) / 'static' / 'js').glob('*.js'))
        self.assertTrue(files)
        for path in files:
            try:
                esprima.parseScript(path.read_text(encoding='utf-8'))
            except Exception as error:  # noqa: BLE001
                self.fail(f'JavaScript syntax error in {path.name}: {error}')
