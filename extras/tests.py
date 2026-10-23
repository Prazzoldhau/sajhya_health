import json
import tempfile
from io import StringIO
from pathlib import Path

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.tests.helpers import make_patient, make_professional

from . import live_map

SCHEMA_FILE = Path(__file__).resolve().parent / 'live_schema.json'


class LiveSchemaCoverageTests(TestCase):
    def schema(self):
        return json.loads(SCHEMA_FILE.read_text(encoding='utf-8'))['tables']

    def test_every_live_table_and_column_has_a_home(self):
        report = live_map.audit(self.schema())
        self.assertEqual(report['unmapped_tables'], [])
        self.assertEqual(report['unmapped_columns'], [])
        self.assertEqual(report['missing_models'], [])
        self.assertEqual(report['tables'], 85)
        self.assertGreater(report['columns'], 600)

    def test_the_audit_really_notices_gaps(self):
        schema = self.schema()
        schema['brand_new_live_table'] = ['id', 'name']
        schema['personal_account_addpatient'] = schema['personal_account_addpatient'] + ['shoe_size']
        schema['lab_app_labtest'] = schema['lab_app_labtest'] + ['barcode']
        report = live_map.audit(schema)
        self.assertEqual(report['unmapped_tables'], ['brand_new_live_table'])
        self.assertEqual(len(report['unmapped_columns']), 2)
        self.assertTrue(any('shoe_size' in c for c in report['unmapped_columns']))
        self.assertTrue(any('barcode' in c for c in report['unmapped_columns']))

    def test_the_command_passes_on_the_committed_schema_and_fails_on_a_gap(self):
        out = StringIO()
        call_command('audit_live_dump', stdout=out)
        self.assertIn('Every live table and column has a home', out.getvalue())
        broken = self.schema()
        broken['marketplace_app_order'].append('loyalty_points')
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as handle:
            json.dump({'tables': broken}, handle)
        with self.assertRaises(SystemExit):
            call_command('audit_live_dump', handle.name, stdout=StringIO(), stderr=StringIO())

    def test_sql_dumps_are_read_for_structure_only(self):
        sql = ('CREATE TABLE `demo_table` (\n  `id` bigint(20) NOT NULL,\n  `name` varchar(50) NOT NULL,\n  `notes` longtext DEFAULT NULL\n) ENGINE=InnoDB;\n'
               "INSERT INTO `demo_table` (`id`, `name`) VALUES\n(1, 'SECRET PATIENT');\n")
        with tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False, encoding='utf-8') as handle:
            handle.write(sql)
        self.assertEqual(live_map.parse_sql_schema(handle.name), {'demo_table': ['id', 'name', 'notes']})

    def test_every_extras_model_points_at_a_real_live_table(self):
        live = set(self.schema())
        documented = live_map.extras_tables()
        self.assertEqual(len(documented), len(list(apps.get_app_config('extras').get_models())))
        self.assertTrue(set(documented) <= live)

    def test_extras_model_columns_match_the_live_columns_exactly(self):
        """Each generated model carries every live column (and nothing the live table did not have, apart from its id)."""
        schema = self.schema()
        for table, label in live_map.extras_tables().items():
            model = apps.get_model(label)
            ours = {f.attname for f in model._meta.concrete_fields} - {'id'}
            live_cols = set(schema[table]) - {'id'}
            self.assertEqual(ours, live_cols, f'{table} vs {label}')


class ExtrasTablesWorkTests(TestCase):
    def test_new_tables_store_and_load_data(self):
        from .models import ActivationCard, BookingRequest, DeliveryZone, DonatableCategory, DonationPledge, Enterprise, PatientTestEntry, Referral, SpecialTestReference, VisitNote
        user, profile = make_professional('extras')
        patient = make_patient(profile, 'Live Patient')
        ActivationCard.objects.create(code='ABC-123', duration_days=30)
        enterprise = Enterprise.objects.create(enterprise_name='City Hospital', enterprise_code='ENT-1', address='x', phone='1', created_by=user)
        patient.enterprise = enterprise
        patient.qr_token = 'tok123'
        patient.legacy_username = 'old_user'
        patient.save()
        self.assertEqual(enterprise.patients.get(), patient)
        Referral.objects.create(referral_code='REF-1', patient_name='A', reason='knee', patient=patient, referred_by=profile)
        ref = SpecialTestReference.objects.create(region='knee', name='Lachman', order=1)
        PatientTestEntry.objects.create(patient=patient, reference=ref)
        pledge = DonationPledge.objects.create(pledge_number='P-1', donor_name='D')
        pledge.items.add(DonatableCategory.objects.create(name='Crutches'))
        self.assertEqual(pledge.items.count(), 1)
        BookingRequest.objects.create(patient_name='V', physio=profile)
        DeliveryZone.objects.create(name='Lalitpur')
        VisitNote.objects.create(patient=patient)
        self.assertEqual(Referral.objects.get().patient, patient)

    def test_unique_live_codes_are_still_unique(self):
        from django.db import IntegrityError, transaction
        from .models import ActivationCard
        ActivationCard.objects.create(code='SAME', duration_days=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ActivationCard.objects.create(code='SAME', duration_days=1)

    def test_old_site_columns_on_existing_tables_are_usable(self):
        from billing.models import PackagePayment
        from exercises.models import Prescription
        from lab.models import LabTestRequest
        from profiles.models import PatientProfile
        user, profile = make_professional('cols')
        patient = make_patient(profile, 'Cols Patient')
        rx = Prescription.objects.create(patient=patient, professional=profile, prescription_date=timezone.now())
        self.assertIsNotNone(rx.prescription_date)
        booking = LabTestRequest.objects.create(patient=patient, customer_name='x', customer_email='x@example.com', customer_phone='1', collection_address='y')
        self.assertEqual(booking.patient, patient)
        PatientProfile.objects.create(patient=patient, nursing_vitals='BP 120/80')
        self.assertEqual(patient.account if hasattr(patient, 'account') else None, None)
        self.assertTrue(hasattr(PackagePayment, 'recorded_by'))
