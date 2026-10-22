"""One complete journey through the whole product, the way a real professional would use it.

If this test fails, something that works in isolation has stopped working together - start here when troubleshooting.
"""
import datetime
import json
import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Appointment, ClinicalFocus, Patient, Profession, ProfessionalProfile, ServiceType, Visit
from accounts.tests.helpers import PASSWORD, pdf, private_storage
from billing.models import BillingEntry, PatientPackage
from exercises.models import ExerciseMain, Prescription, Region, SubRegion
from lab.models import LabTest
from marketplace.models import PharmacyProduct
from profiles.models import LabEntry, MedicineEntry

NEW_PASSWORD = 'Another-Safe-Pass-42'


class FullJourneyTests(TestCase):
    def test_signup_to_daily_practice_to_password_reset(self):
        cache.clear()
        today = timezone.localdate()
        c = self.client

        # ---- 1. visitor -> landing -> packages -> professional signup ----
        self.assertEqual(c.get('/').status_code, 200)
        self.assertEqual(c.get(reverse('accounts:package')).status_code, 200)
        physio = Profession.objects.get(name='physiotherapist')
        r = c.post(reverse('accounts:signup', args=['professional', physio.pk]), {
            'first_name': 'Prajwol', 'last_name': 'Dhaubanjar', 'mobile': '9800000000', 'title': 'PT', 'email': 'prajwol@example.com',
            'username': 'drp', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertRedirects(r, reverse('accounts:professional-step', args=[2]))
        user = User.objects.get(username='drp')

        # ---- 2. onboarding: save & resume, documents, review by staff ----
        c.post(reverse('accounts:professional-step', args=[2]), {'action': 'later', 'license_number': 'N-1'})
        c.get(reverse('accounts:logout'))  # logout is POST-only; a GET must not sign anyone out by accident
        self.assertIn('_auth_user_id', c.session)
        c.post(reverse('accounts:logout'))
        self.assertNotIn('_auth_user_id', c.session)
        self.assertRedirects(c.post(reverse('accounts:login'), {'username': 'drp', 'password': PASSWORD}), reverse('accounts:welcome'), fetch_redirect_response=False)
        self.assertContains(c.get(reverse('accounts:welcome')), 'Continue onboarding')
        with private_storage():
            c.post(reverse('accounts:professional-step', args=[2]), {'action': 'continue', 'license_number': 'N-1', 'issuing_authority': 'NHPC', 'license_expiry': '2031-01-01'})
            c.post(reverse('accounts:professional-step', args=[3]), {'action': 'continue', 'id_document': pdf('i.pdf'), 'license_document': pdf('l.pdf'), 'indemnity_document': pdf('n.pdf'),
                                                                    'degree_document': pdf('d.pdf'), 'indemnity_policy_number': 'P', 'indemnity_expiry': '2031-01-01'})
            c.post(reverse('accounts:professional-step', args=[4]), {'action': 'continue', 'years_experience': 6, 'focus_areas': [ClinicalFocus.objects.first().pk], 'services': [ServiceType.objects.first().pk]})
            c.post(reverse('accounts:professional-step', args=[5]))
            profile = ProfessionalProfile.objects.get(account__user=user)
            self.assertEqual(profile.status, 'submitted')
            staff = User.objects.create_user('boss', password=PASSWORD, is_staff=True)
            reviewer = self.client_class()
            reviewer.force_login(staff)
            reviewer.post(reverse('accounts:review-detail', args=[profile.pk]), {'decision': 'approve'})
        profile.refresh_from_db()
        self.assertEqual(profile.status, 'approved')

        # ---- 3. workspace opens: dashboard, plan limit comes from the account plan ----
        self.assertRedirects(c.get(reverse('accounts:welcome')), reverse('accounts:dashboard'), fetch_redirect_response=False)
        self.assertEqual(c.get(reverse('accounts:dashboard')).context['stats']['total'], 0)

        # ---- 4. patient, picture, ICD-10 diagnosis ----
        c.post(reverse('accounts:patient-add'), {'name': 'Ram Shrestha', 'date_of_birth': '1980-05-05', 'gender': 'M', 'phone': '9841234567', 'diagnosis': 'Low back pain', 'icd10_code': 'M54.5'})
        patient = Patient.objects.get(name='Ram Shrestha')
        self.assertTrue(patient.patient_code.startswith('PAT-'))

        # ---- 5. billing package of 3 sessions, part paid ----
        c.post(reverse('billing:package-create'), {'patient': patient.pk, 'duration': '2_week', 'total_sessions': 3, 'total_amount': '3000', 'amount_paid_now': '1000', 'start_date': today.isoformat()})
        package = PatientPackage.objects.get()
        self.assertEqual((package.amount_due, package.sessions_used), (2000, 0))

        # ---- 6. three appointments, each marked attended -> visit + package session ----
        for offset in range(3):
            start = timezone.make_aware(datetime.datetime.combine(today, datetime.time(9 + offset, 0)))
            Appointment.objects.create(professional=profile, patient=patient, start=start, end=start + datetime.timedelta(minutes=30), session_type='treatment')
        for appt in Appointment.objects.all():
            c.post(reverse('accounts:appointment-action', args=[appt.pk]), {'action': 'attend'})
        package.refresh_from_db()
        self.assertEqual((package.sessions_used, package.status, Visit.objects.filter(patient=patient).count()), (3, 'completed', 3))
        self.assertEqual(patient.visits.count(), 3)  # the patient's completed-session count
        # a fourth completed session is not charged to the finished package
        c.post(reverse('accounts:patient-visit-add', args=[patient.pk]), {'date': today.isoformat(), 'session_type': 'follow_up'})
        package.refresh_from_db()
        self.assertEqual((package.sessions_used, patient.visits.count()), (3, 4))
        # the balance is settled in instalments; revenue shows up on the dashboard and the billing page
        c.post(reverse('billing:package-payment', args=[package.pk]), {'amount': '2000', 'payment_mode': 'cash'})
        package.refresh_from_db()
        self.assertTrue(package.is_fully_paid)
        c.post(reverse('billing:entry-create'), {'entry_date': today.isoformat(), 'patient': patient.pk, 'patient_name': patient.name, 'service': 'Consult', 'rate': '500', 'payment_mode': 'online'})
        self.assertEqual(c.get(reverse('accounts:dashboard')).context['stats']['revenue_today'], 3500)  # 1000 + 2000 package payments + 500 entry
        self.assertEqual(BillingEntry.objects.count(), 1)

        # ---- 7. exercises from the library, a treatment plan using them ----
        region = Region.objects.create(region_name='Spine')
        sub = SubRegion.objects.create(region_fk=region, sub_region_name='Lumbar')
        exercise = ExerciseMain.objects.create(sub_region_fk=sub, exercise_name='Bridge', exercise_type='Strengthening', difficulty_level=1, default_sets=3, default_reps=10, hold_time_sec=5)
        r = c.post(reverse('exercises:prescribe'), data=json.dumps({'patient_id': patient.pk, 'condition_label': 'LBP', 'exercises': [{'id': exercise.pk}]}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        plan = {'title': 'LBP plan', 'diagnosis': 'Low back pain', 'icd10_code': 'M54.5', 'start_date': today.isoformat(), 'onset_date': '', 'precautions': '', 'education': '',
                'goals': [{'text': 'Walk 30 minutes', 'term': 'short', 'target_date': ''}], 'measures': [{'name': 'Pain', 'unit': '/10', 'baseline': '7', 'target': '2'}],
                'phases': [{'name': 'Phase 1', 'week_start': 1, 'week_end': 2, 'frequency_per_week': 3, 'frequency_note': 'Clinic', 'goal': '',
                            'items': [{'kind': 'clinic', 'text': 'Mobilisation', 'dosage': ''}, {'kind': 'hep', 'text': 'Bridge', 'dosage': exercise.dose_label}]}], 'action': 'publish'}
        self.assertEqual(c.post(reverse('accounts:plan-create', args=[patient.pk]), data=json.dumps(plan), content_type='application/json').status_code, 200)

        # ---- 8. profile sections fed by the pharmacy and lab catalogues; physio pulled from the daily records ----
        PharmacyProduct.objects.create(name='Aceclofenac 100')
        LabTest.objects.create(name='CRP', category='biochemistry', price=700)
        product = PharmacyProduct.objects.get()
        c.post(reverse('profiles:add', args=[patient.pk, 'medicine']), {'pharmacy_product': product.pk, 'dosage': '1 tablet', 'morning': 'on', 'start_date': today.isoformat()})
        c.post(reverse('profiles:add', args=[patient.pk, 'labs']), {'lab_test': LabTest.objects.get().pk, 'ordered_on': today.isoformat(), 'status': 'advised'})
        self.assertEqual((MedicineEntry.objects.count(), LabEntry.objects.count()), (1, 1))
        rehab = c.get(reverse('accounts:patient-detail', args=[patient.pk]), {'tab': 'profile', 'section': 'rehab'})
        for text in ('LBP plan', 'Bridge', 'Mobilisation'):
            self.assertContains(rehab, text)
        for tab in ('overview', 'plan', 'exercises', 'visits', 'billing', 'profile', 'notes', 'documents'):
            self.assertEqual(c.get(reverse('accounts:patient-detail', args=[patient.pk]), {'tab': tab}).status_code, 200, tab)
        self.assertEqual(Prescription.objects.get().exercises.count(), 1)

        # ---- 9. forgot password: email -> link -> new password -> old one dead, workspace still there ----
        c.post(reverse('accounts:logout'))
        c.post(reverse('accounts:password-reset'), {'email': 'prajwol@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r'https?://testserver(/\S+)', mail.outbox[0].body).group(1)
        form_url = c.get(link, follow=True).redirect_chain[-1][0]
        c.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertFalse(self.client_class().login(username='drp', password=PASSWORD))
        self.assertTrue(c.login(username='drp', password=NEW_PASSWORD))
        self.assertEqual(c.get(reverse('accounts:patients')).context['counts']['total'], 1)

    def test_other_account_types_can_sign_up_and_sign_in(self):
        from accounts.models import ClinicType, EnterpriseType
        cases = [(reverse('accounts:signup-client'), {}),
                 (reverse('accounts:signup', args=['enterprise', EnterpriseType.objects.first().pk]), {'organization_name': 'City Hospital'})]
        for i, (url, extra) in enumerate(cases):
            client = self.client_class()
            r = client.post(url, {'username': f'acct{i}', 'email': f'acct{i}@example.com', 'password1': PASSWORD, 'password2': PASSWORD, **extra})
            self.assertEqual(r.status_code, 302, url)
            client.post(reverse('accounts:logout'))
            self.assertTrue(client.login(username=f'acct{i}', password=PASSWORD))
            welcome = client.get(reverse('accounts:welcome'), follow=True)
            self.assertEqual(welcome.status_code, 200)  # clients land on their patient dashboard, others on the welcome page
            self.assertEqual(client.get(reverse('accounts:patients')).status_code, 404)  # no clinical workspace for these types yet
