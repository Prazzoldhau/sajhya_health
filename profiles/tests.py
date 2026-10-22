import datetime
import os
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import PlanMeasure, TreatmentPlan, Visit
from accounts.tests.helpers import make_patient, make_professional, pdf, private_storage
from exercises.models import ExerciseMain, Prescription, PrescriptionExercise, Region, SubRegion
from lab.models import LabTest, LabTestPanel
from marketplace.models import Category, PharmacyProduct, Product

from .models import AidEntry, LabEntry, MedicineEntry, NursingEntry, PatientProfile, TherapyNote
from .rehab import physio_summary


class ProfileBase(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.today = timezone.localdate()

    def page(self, section='general', **params):
        return self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'profile', 'section': section, **params})

    def add(self, section, data):
        return self.client.post(reverse('profiles:add', args=[self.patient.pk, section]), data)


class ProfileTabTests(ProfileBase):
    def test_every_section_renders(self):
        for section in ('general', 'medicine', 'nursing', 'aids', 'rehab', 'labs', 'bogus'):
            self.assertEqual(self.page(section).status_code, 200, section)
        for therapy in ('physio', 'occupational', 'speech', 'behavioural', 'bogus'):
            self.assertEqual(self.page('rehab', therapy=therapy).status_code, 200, therapy)

    def test_standing_info_and_allergy_banner_on_every_tab(self):
        r = self.client.post(reverse('profiles:standing-save', args=[self.patient.pk]), {
            'allergies': 'Penicillin - rash', 'medical_history': 'Appendectomy 2015', 'wound_catheter_care': '', 'mobility_assistance': 'Needs a frame'})
        self.assertEqual(r.status_code, 302)
        info = PatientProfile.objects.get(patient=self.patient)
        self.assertEqual((info.allergies, info.updated_by), ('Penicillin - rash', self.user))
        for tab in ('overview', 'visits', 'billing'):
            page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': tab})
            self.assertContains(page, 'Allergies: Penicillin - rash')

    def test_everything_is_private_to_the_owning_professional(self):
        entry = MedicineEntry.objects.create(patient=self.patient, custom_name='Secret')
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertEqual(other.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'profile'}).status_code, 404)
        for url in (reverse('profiles:add', args=[self.patient.pk, 'medicine']), reverse('profiles:delete', args=[self.patient.pk, 'medicine', entry.pk]),
                    reverse('profiles:medicine-status', args=[self.patient.pk, entry.pk]), reverse('profiles:standing-save', args=[self.patient.pk])):
            self.assertEqual(other.post(url, {'custom_name': 'x'}).status_code, 404, url)
        self.assertTrue(MedicineEntry.objects.filter(pk=entry.pk).exists())
        self.client.logout()
        self.assertEqual(self.client.get(reverse('profiles:medicine-search'), {'q': 'abc'}).status_code, 302)

    def test_unknown_section_is_a_404(self):
        self.assertEqual(self.client.post(reverse('profiles:add', args=[self.patient.pk, 'bogus']), {}).status_code, 404)


class MedicineTests(ProfileBase):
    def test_add_from_the_pharmacy_catalogue_and_free_text(self):
        product = PharmacyProduct.objects.create(name='Aceclofenac 100', requires_prescription=True)
        self.add('medicine', {'pharmacy_product': product.pk, 'dosage': '1 tablet', 'morning': 'on', 'night': 'on', 'instructions': 'after food', 'start_date': self.today.isoformat()})
        self.add('medicine', {'custom_name': 'Local herbal tonic', 'start_date': self.today.isoformat()})
        catalogue, free = MedicineEntry.objects.order_by('id')
        self.assertEqual((catalogue.display_name, catalogue.times_label, catalogue.recorded_by), ('Aceclofenac 100', 'Morning · Night', self.user))
        self.assertEqual((free.display_name, free.pharmacy_product, free.times_label), ('Local herbal tonic', None, 'As needed'))
        self.assertContains(self.page('medicine'), 'From the pharmacy catalogue')

    def test_validation(self):
        self.add('medicine', {'start_date': self.today.isoformat()})  # no medicine named
        self.add('medicine', {'custom_name': 'X', 'start_date': '2026-10-10', 'end_date': '2026-10-01'})  # ends before it starts
        self.add('medicine', {'custom_name': 'X', 'pharmacy_product': 99999, 'start_date': self.today.isoformat()})
        self.assertEqual(MedicineEntry.objects.count(), 0)

    def test_status_changes_and_derived_completion(self):
        entry = MedicineEntry.objects.create(patient=self.patient, custom_name='Course', end_date=self.today - datetime.timedelta(days=1))
        self.assertEqual(entry.effective_status, 'completed')  # past its end date: derived, no scheduled job
        entry.end_date = None
        entry.save()
        status = reverse('profiles:medicine-status', args=[self.patient.pk, entry.pk])
        self.client.post(status, {'status': 'stopped'})
        entry.refresh_from_db()
        self.assertEqual((entry.status, entry.end_date), ('stopped', self.today))
        self.client.post(status, {'status': 'active'})
        entry.refresh_from_db()
        self.assertEqual((entry.status, entry.end_date), ('active', None))
        self.client.post(status, {'status': 'bogus'})
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'active')
        self.client.post(reverse('profiles:delete', args=[self.patient.pk, 'medicine', entry.pk]))
        self.assertEqual(MedicineEntry.objects.count(), 0)

    def test_medicine_search_uses_the_pharmacy_catalogue(self):
        PharmacyProduct.objects.create(name='Amlodipine 5')
        PharmacyProduct.objects.create(name='Aspirin 75')
        url = reverse('profiles:medicine-search')
        self.assertEqual([r['name'] for r in self.client.get(url, {'q': 'amlo'}).json()['results']], ['Amlodipine 5'])
        self.assertEqual(self.client.get(url, {'q': 'a'}).json()['results'], [])


class NursingTests(ProfileBase):
    def test_vitals_summary_and_attention_flags(self):
        self.add('nursing', {'category': 'vitals', 'recorded_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'), 'bp_systolic': 170, 'bp_diastolic': 105, 'pulse': 88, 'temperature_c': '38.4', 'spo2': 97})
        entry = NursingEntry.objects.get()
        self.assertEqual(entry.vitals_summary, 'BP 170/105 · Pulse 88 · Temp 38.4°C · SpO₂ 97%')
        self.assertTrue(entry.needs_attention)
        self.assertContains(self.page('nursing'), 'Outside the usual range')
        self.add('nursing', {'category': 'vitals', 'recorded_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'), 'bp_systolic': 120, 'bp_diastolic': 80, 'pulse': 72, 'temperature_c': '36.8', 'spo2': 98})
        self.assertFalse(NursingEntry.objects.latest('id').needs_attention)

    def test_validation(self):
        now = timezone.localtime().strftime('%Y-%m-%dT%H:%M')
        self.add('nursing', {'category': 'vitals', 'recorded_at': now})  # nothing recorded
        self.add('nursing', {'category': 'vitals', 'recorded_at': now, 'bp_systolic': 120})  # half a blood pressure
        self.add('nursing', {'category': 'wound_care', 'recorded_at': 'garbage', 'notes': 'x'})
        self.assertEqual(NursingEntry.objects.count(), 0)
        self.add('nursing', {'category': 'wound_care', 'recorded_at': now, 'notes': 'Dressing changed'})
        self.assertEqual(NursingEntry.objects.count(), 1)

    def test_standing_care_needs_show_on_the_nursing_tab(self):
        PatientProfile.objects.create(patient=self.patient, wound_catheter_care='Change dressing daily')
        self.assertContains(self.page('nursing'), 'Change dressing daily')


class AidTests(ProfileBase):
    def test_add_status_and_delete(self):
        self.add('aids', {'custom_name': 'Walking frame', 'category': 'mobility', 'side': '', 'size': 'M', 'issued_on': self.today.isoformat()})
        aid = AidEntry.objects.get()
        self.assertEqual((aid.display_name, aid.status), ('Walking frame', 'in_use'))
        self.client.post(reverse('profiles:aid-status', args=[self.patient.pk, aid.pk]), {'status': 'returned'})
        aid.refresh_from_db()
        self.assertEqual(aid.status, 'returned')
        self.add('aids', {'custom_name': '  ', 'category': 'mobility', 'issued_on': self.today.isoformat()})
        self.assertEqual(AidEntry.objects.count(), 1)
        self.client.post(reverse('profiles:delete', args=[self.patient.pk, 'aids', aid.pk]))
        self.assertEqual(AidEntry.objects.count(), 0)


    def test_aid_search_finds_marketplace_products_not_pharmacy_items(self):
        cat = Category.objects.create(name='Mobility')
        Product.objects.create(name='Folding Walker', category=cat, price=3500)
        PharmacyProduct.objects.create(name='Walker Cough Syrup')
        url = reverse('profiles:aid-search')
        self.assertEqual(self.client.get(url, {'q': 'walker'}).json()['results'], [{'id': Product.objects.get().pk, 'name': 'Folding Walker', 'detail': 'Mobility'}])
        self.assertEqual(self.client.get(url, {'q': 'w'}).json()['results'], [])

    def test_aid_can_be_linked_to_a_marketplace_product(self):
        product = Product.objects.create(name='Aluminium Crutches', price=2200)
        self.add('aids', {'product': product.pk, 'custom_name': '', 'category': 'mobility', 'issued_on': self.today.isoformat()})
        aid = AidEntry.objects.get()
        self.assertEqual((aid.product, aid.display_name), (product, 'Aluminium Crutches'))


class TherapyTests(ProfileBase):
    def test_each_therapy_keeps_its_own_notes(self):
        for therapy in ('occupational', 'speech', 'behavioural'):
            self.add('therapy', {'therapy': therapy, 'session_date': self.today.isoformat(), 'goal': f'{therapy} goal', 'intervention': 'Did a thing'})
        self.assertEqual(TherapyNote.objects.count(), 3)
        speech = self.page('rehab', therapy='speech')
        self.assertContains(speech, 'speech goal')
        self.assertNotContains(speech, 'occupational goal')
        self.assertEqual(list(speech.context['therapy_notes'].values_list('therapy', flat=True)), ['speech'])

    def test_validation_and_redirect_back_to_the_right_tab(self):
        r = self.add('therapy', {'therapy': 'speech', 'session_date': self.today.isoformat()})  # everything empty
        self.assertEqual(TherapyNote.objects.count(), 0)
        self.assertIn('therapy=speech', r['Location'])
        self.add('therapy', {'therapy': 'physio', 'session_date': self.today.isoformat(), 'goal': 'x'})  # physio is not a note type
        self.assertEqual(TherapyNote.objects.count(), 0)


class LabTests(ProfileBase):
    def setUp(self):
        super().setUp()
        self.cbc = LabTest.objects.create(name='CBC', category='hematology', price=Decimal('400'))
        self.panel = LabTestPanel.objects.create(name='Diabetes Panel', price=Decimal('1000'))

    def test_add_from_the_catalogue_panel_and_free_text(self):
        self.add('labs', {'lab_test': self.cbc.pk, 'custom_name': 'CBC', 'ordered_on': self.today.isoformat(), 'status': 'advised'})
        self.add('labs', {'lab_panel': self.panel.pk, 'ordered_on': self.today.isoformat(), 'status': 'booked'})
        self.add('labs', {'custom_name': 'Vitamin D (outside lab)', 'ordered_on': self.today.isoformat(), 'status': 'advised'})
        self.add('labs', {'ordered_on': self.today.isoformat(), 'status': 'advised'})  # nothing named
        self.assertEqual(sorted(e.display_name for e in LabEntry.objects.all()), ['CBC', 'Diabetes Panel', 'Vitamin D (outside lab)'])

    def test_status_flow_and_result_entry(self):
        self.add('labs', {'lab_test': self.cbc.pk, 'ordered_on': self.today.isoformat(), 'status': 'advised'})
        entry = LabEntry.objects.get()
        status = reverse('profiles:lab-status', args=[self.patient.pk, entry.pk])
        self.client.post(status, {'status': 'booked'})
        self.client.post(status, {'status': 'collected'})
        self.client.post(status, {'status': 'resulted'})  # not settable directly: results come through the result form
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'collected')
        result = reverse('profiles:lab-result', args=[self.patient.pk, entry.pk])
        self.client.post(result, {})  # nothing entered
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'collected')
        self.client.post(result, {'result_value': '13.2', 'result_unit': 'g/dL', 'reference_range': '12-16', 'flag': 'normal'})
        entry.refresh_from_db()
        self.assertEqual((entry.status, entry.result_value, entry.resulted_on), ('resulted', '13.2', self.today))
        self.assertContains(self.page('labs'), '13.2 g/dL')

    def test_report_upload_is_validated_private_and_cleaned_up(self):
        entry = LabEntry.objects.create(patient=self.patient, lab_test=self.cbc)
        url = reverse('profiles:lab-result', args=[self.patient.pk, entry.pk])
        with private_storage():
            self.client.post(url, {'report': SimpleUploadedFile('r.exe', b'MZ')})
            self.client.post(url, {'report': SimpleUploadedFile('r.pdf', b'<html>not a pdf</html>')})
            entry.refresh_from_db()
            self.assertFalse(entry.report)
            self.client.post(url, {'report': pdf('r.pdf'), 'result_value': 'see report'})
            entry.refresh_from_db()
            self.assertTrue(entry.report)
            first = entry.report.path
            self.assertNotIn('r.pdf', os.path.basename(first))  # stored under a random name
            report_url = reverse('profiles:lab-report', args=[self.patient.pk, entry.pk])
            self.assertEqual(self.client.get(report_url).status_code, 200)
            stranger, _ = make_professional('stranger')
            other = self.client_class()
            other.force_login(stranger)
            self.assertEqual(other.get(report_url).status_code, 404)
            self.assertEqual(self.client_class().get(report_url).status_code, 302)
            self.client.post(url, {'report': pdf('again.pdf'), 'result_value': 'see report'})
            entry.refresh_from_db()
            self.assertFalse(os.path.exists(first))  # the replaced report is deleted
            second = entry.report.path
            self.client.post(reverse('profiles:delete', args=[self.patient.pk, 'labs', entry.pk]))
            self.assertFalse(os.path.exists(second))  # and so is the report when the entry goes

    def test_catalogue_search_endpoint(self):
        results = self.client.get(reverse('lab:search'), {'q': 'diab'}).json()['results']
        self.assertEqual([(r['kind'], r['name']) for r in results], [('panel', 'Diabetes Panel')])


class RehabPhysioTests(ProfileBase):
    def test_empty_state(self):
        summary = physio_summary(self.patient)
        self.assertFalse(summary['has_data'])
        self.assertContains(self.page('rehab'), 'No physiotherapy has been recorded yet')

    def test_pulls_assessment_exercises_and_interventions_from_daily_records(self):
        Visit.objects.create(patient=self.patient, therapist='Asha Rai', date=self.today - datetime.timedelta(days=9), session_type='initial', notes='Painful abduction')
        Visit.objects.create(patient=self.patient, therapist='Asha Rai', date=self.today - datetime.timedelta(days=2), session_type='treatment', progress='improving', notes='Better ROM')
        plan = TreatmentPlan.objects.create(patient=self.patient, professional=self.profile, title='Shoulder plan', status='active')
        measure = PlanMeasure.objects.create(plan=plan, name='Abduction', unit='°', baseline=110, target=170)
        measure.readings.create(value=140)
        phase = plan.phases.create(name='Phase 1', week_start=1, week_end=2, status='current')
        phase.items.create(kind='clinic', text='Passive ROM', order=0)
        phase.items.create(kind='hep', text='Pendulum', order=1)
        region = Region.objects.create(region_name='Upper')
        sub = SubRegion.objects.create(region_fk=region, sub_region_name='Shoulder')
        exercise = ExerciseMain.objects.create(sub_region_fk=sub, exercise_name='Wand flexion', exercise_type='ROM', difficulty_level=1, default_sets=3, default_reps=10, hold_time_sec=0)
        rx = Prescription.objects.create(patient=self.patient, professional=self.profile, condition_label='Shoulder')
        PrescriptionExercise.objects.create(prescription=rx, exercise=exercise, exercise_name='Wand flexion', is_completed=True)

        summary = physio_summary(self.patient)
        self.assertTrue(summary['has_data'])
        self.assertEqual([v.notes for v in summary['initial_assessments']], ['Painful abduction'])
        self.assertEqual((summary['measures'][0]['latest'], summary['measures'][0]['progress']), (140, 50))
        self.assertEqual(summary['current_phase'], phase)
        self.assertEqual([i.text for i in summary['clinic_by_phase'][0]['items']], ['Passive ROM'])  # home exercises are not interventions
        self.assertEqual([v.notes for v in summary['recent_treatments']], ['Better ROM'])
        page = self.page('rehab')
        for text in ('Painful abduction', 'Abduction', 'Wand flexion', 'Passive ROM', 'Better ROM', 'Shoulder plan'):
            self.assertContains(page, text)

    def test_the_active_plan_is_preferred_and_discontinued_ones_ignored(self):
        TreatmentPlan.objects.create(patient=self.patient, professional=self.profile, title='Old plan', status='completed')
        TreatmentPlan.objects.create(patient=self.patient, professional=self.profile, title='Dropped', status='discontinued')
        TreatmentPlan.objects.create(patient=self.patient, professional=self.profile, title='Current plan', status='active')
        self.assertEqual(physio_summary(self.patient)['plan'].title, 'Current plan')
        TreatmentPlan.objects.filter(title='Current plan').delete()
        self.assertEqual(physio_summary(self.patient)['plan'].title, 'Old plan')
