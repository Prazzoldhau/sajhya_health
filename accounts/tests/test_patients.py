import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Icd10Code, Patient, Visit

from .helpers import make_patient, make_professional

NEW_PATIENT = {'name': 'Ram Shrestha', 'date_of_birth': '1980-05-05', 'gender': 'M', 'phone': '9841234567'}


class PatientAccessTests(TestCase):
    def test_anonymous_users_are_redirected_to_login(self):
        for name in ('patients', 'dashboard', 'appointments', 'plans', 'billing:billing', 'exercises:library'):
            url = reverse(name if ':' in name else f'accounts:{name}')
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, name)
            self.assertIn('/accounts/login/', r['Location'])

    def test_unfinished_professional_is_sent_back_to_onboarding(self):
        user, _ = make_professional(status='draft', completed_step=1)
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse('accounts:patients')), reverse('accounts:welcome'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('accounts:dashboard')), reverse('accounts:welcome'), fetch_redirect_response=False)

    def test_clients_without_a_professional_profile_get_404(self):
        from django.contrib.auth.models import User
        from accounts.models import Account
        user = User.objects.create_user('plain', password='x')
        Account.objects.create(user=user, account_type='client')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('accounts:patients')).status_code, 404)


class PatientTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)

    def test_add_patient_generates_code_and_validates_required_fields(self):
        r = self.client.post(reverse('accounts:patient-add'), {'name': 'No Phone'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Patient.objects.count(), 0)
        r = self.client.post(reverse('accounts:patient-add'), {**NEW_PATIENT, 'diagnosis': 'Sciatica', 'icd10_code': 'M54.3'})
        self.assertRedirects(r, reverse('accounts:patients'))
        patient = Patient.objects.get()
        self.assertTrue(patient.patient_code.startswith('PAT-'))
        self.assertEqual((patient.status, patient.diagnosis), ('active', 'Sciatica'))
        self.assertEqual(patient.professional, self.profile)

    def test_patients_are_private_to_their_professional(self):
        mine = make_patient(self.profile, 'Mine')
        other_user, other_profile = make_professional('other')
        theirs = make_patient(other_profile, 'Theirs')
        page = self.client.get(reverse('accounts:patients'))
        self.assertContains(page, 'Mine')
        self.assertNotContains(page, 'Theirs')
        for name in ('patient-detail', 'patient-edit'):
            self.assertEqual(self.client.get(reverse(f'accounts:{name}', args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:patient-visit-add', args=[theirs.pk]), {'date': '2026-01-01', 'session_type': 'treatment'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[mine.pk])).status_code, 200)

    def test_search_status_age_filters_and_sorting(self):
        today = timezone.localdate()
        def born(years):
            return today.replace(year=today.year - years) - datetime.timedelta(days=1)
        make_patient(self.profile, 'Young Yam', date_of_birth=born(10), phone='111', status='active')
        make_patient(self.profile, 'Adult Anu', date_of_birth=born(30), phone='222', status='on_hold')
        make_patient(self.profile, 'Senior Sam', date_of_birth=born(70), phone='333', status='discharged')

        def names(**params):
            r = self.client.get(reverse('accounts:patients'), params)
            return [p.name for p in r.context['page_obj']] if r.context else None
        self.assertEqual(sorted(names()), ['Adult Anu', 'Senior Sam', 'Young Yam'])
        self.assertEqual(names(q='anu'), ['Adult Anu'])
        self.assertEqual(names(q='333'), ['Senior Sam'])
        self.assertEqual(names(status='on_hold'), ['Adult Anu'])
        self.assertEqual(names(age='child'), ['Young Yam'])
        self.assertEqual(names(age='adult'), ['Adult Anu'])
        self.assertEqual(names(age='senior'), ['Senior Sam'])
        self.assertEqual(names(sort='name'), ['Adult Anu', 'Senior Sam', 'Young Yam'])

    def test_pagination(self):
        for i in range(12):
            make_patient(self.profile, f'Patient {i:02d}')
        page1 = self.client.get(reverse('accounts:patients'))
        self.assertEqual(len(page1.context['page_obj']), 10)
        page2 = self.client.get(reverse('accounts:patients'), {'page': 2})
        self.assertEqual(len(page2.context['page_obj']), 2)

    def test_recent_patients_follow_adding_opening_and_visits(self):
        a, b = make_patient(self.profile, 'Alpha'), make_patient(self.profile, 'Bravo')
        recent = lambda: [p.name for p in self.client.get(reverse('accounts:patients')).context['recent_patients']]
        self.assertEqual(recent(), ['Bravo', 'Alpha'])  # newly added patients are recent straight away
        self.client.get(reverse('accounts:patient-detail', args=[a.pk]))
        self.assertEqual(recent(), ['Alpha', 'Bravo'])  # opening one moves it to the top
        self.assertEqual([p.name for p in self.client.get(reverse('accounts:dashboard')).context['recent']], ['Alpha', 'Bravo'])

    def test_recording_a_visit_updates_last_visit_and_recent_patients(self):
        patient = make_patient(self.profile)
        r = self.client.post(reverse('accounts:patient-visit-add', args=[patient.pk]), {'date': '2026-10-01', 'session_type': 'treatment', 'progress': 'improving', 'notes': 'ok'})
        self.assertEqual(r.status_code, 302)
        patient.refresh_from_db()
        self.assertEqual(patient.last_visit, datetime.date(2026, 10, 1))
        visit = Visit.objects.get()
        self.assertEqual((visit.therapist, visit.progress), (self.profile.full_name, 'improving'))
        self.assertEqual(list(self.client.get(reverse('accounts:patients')).context['recent_patients']), [patient])

    def test_older_visit_does_not_move_last_visit_backwards(self):
        patient = make_patient(self.profile, last_visit=datetime.date(2026, 10, 10))
        self.client.post(reverse('accounts:patient-visit-add', args=[patient.pk]), {'date': '2026-09-01', 'session_type': 'treatment'})
        patient.refresh_from_db()
        self.assertEqual(patient.last_visit, datetime.date(2026, 10, 10))

    def test_detail_tabs_edit_and_notes(self):
        patient = make_patient(self.profile)
        for tab in ('overview', 'plan', 'exercises', 'visits', 'billing', 'notes', 'documents', 'bogus'):
            self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk]), {'tab': tab}).status_code, 200, tab)
        edit = self.client.post(reverse('accounts:patient-edit', args=[patient.pk]), {
            'name': 'Sita G', 'date_of_birth': '1990-01-02', 'gender': 'F', 'phone': '9841000000', 'status': 'on_hold',
            'diagnosis': 'LBP', 'icd10_code': 'M54.5', 'insurance': 'N/A'})
        self.assertRedirects(edit, reverse('accounts:patient-detail', args=[patient.pk]))
        patient.refresh_from_db()
        self.assertEqual((patient.name, patient.status), ('Sita G', 'on_hold'))
        self.client.post(reverse('accounts:patient-notes', args=[patient.pk]), {'notes': 'Responds well'})
        patient.refresh_from_db()
        self.assertEqual(patient.notes, 'Responds well')

    def test_icd10_search(self):
        Icd10Code.objects.bulk_create([Icd10Code(code='M54.5', title='Low back pain'), Icd10Code(code='M54.3', title='Sciatica'), Icd10Code(code='S83.5', title='Knee ligament sprain')])
        url = reverse('accounts:icd10-search')
        self.assertEqual(self.client.get(url, {'q': 'x'}).json()['results'], [])  # too short
        by_code = [r['code'] for r in self.client.get(url, {'q': 'm54'}).json()['results']]
        self.assertEqual(sorted(by_code), ['M54.3', 'M54.5'])
        by_title = self.client.get(url, {'q': 'low back'}).json()['results']
        self.assertEqual(by_title[0]['code'], 'M54.5')
        self.client.logout()
        self.assertEqual(self.client.get(url, {'q': 'm54'}).status_code, 302)


class DashboardTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)

    def test_empty_dashboard_renders_friendly_empty_states(self):
        r = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No upcoming appointments')
        self.assertContains(r, 'No patients yet')
        self.assertEqual(r.context['stats']['total'], 0)

    def test_dashboard_numbers_reflect_real_data(self):
        today = timezone.localdate()
        seen = make_patient(self.profile, 'Seen Recently', last_visit=today - datetime.timedelta(days=2))
        stale = make_patient(self.profile, 'Stale Case', last_visit=today - datetime.timedelta(days=30))
        make_patient(self.profile, 'Held', status='on_hold')
        Visit.objects.create(patient=seen, therapist='x', date=today)
        stats = self.client.get(reverse('accounts:dashboard')).context['stats']
        self.assertEqual((stats['total'], stats['active']), (3, 2))
        self.assertEqual(stats['followups_due'], 1)  # only the stale active patient
        self.assertEqual(stats['visits_week'], 1)
        recent = self.client.get(reverse('accounts:dashboard')).context['recent']
        self.assertEqual([p.name for p in recent], ['Held', 'Stale Case', 'Seen Recently'])  # most recently added or opened first
        self.assertEqual([p.name for p in self.client.get(reverse('accounts:dashboard')).context['reminders']], ['Stale Case'])

    def test_pending_professional_sees_verification_status_instead_of_dashboard(self):
        self.profile.status = 'submitted'
        self.profile.save()
        self.assertRedirects(self.client.get(reverse('accounts:dashboard')), reverse('accounts:welcome'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('accounts:welcome')), 'Submitted')
