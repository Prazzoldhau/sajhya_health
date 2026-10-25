import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Patient, Visit
from accounts.tests.helpers import PASSWORD, make_patient, make_professional

from .models import Clinic, ClinicMember, ClinicSubscription, QueueEntry


CLINIC_DATA = {'name': 'Himal Clinic', 'phone': '015550001', 'province': 'Bagmati', 'district': 'Lalitpur', 'ward_street': 'Ward 3, Pulchowk', 'slot_minutes': '30'}


class Base(TestCase):
    def setUp(self):
        self.owner_user, self.owner = make_professional('owner')
        self.client.login(username='owner', password=PASSWORD)

    def activate(self, profile=None, **kwargs):
        return ClinicSubscription.objects.update_or_create(professional=profile or self.owner, defaults={'status': 'active', **kwargs})[0]

    def make_clinic(self, name='Himal Clinic'):
        self.activate()
        self.client.post(reverse('clinics:create'), {**CLINIC_DATA, 'name': name})
        return Clinic.objects.get(name=name)

    def as_user(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)


class RegistrationTests(Base):
    def test_register_link_sends_anonymous_visitors_to_sign_in_then_the_clinic_form(self):
        self.client.logout()
        r = self.client.get(reverse('clinics:register'))
        self.assertRedirects(r, f"{reverse('accounts:login')}?next={reverse('clinics:create')}", fetch_redirect_response=False)
        self.client.login(username='owner', password=PASSWORD)
        self.assertRedirects(self.client.get(reverse('clinics:register')), reverse('clinics:create'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('accounts:package')), reverse('clinics:register'))

    def test_old_clinic_signup_paths_point_to_professional_registration(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse('accounts:select-type', args=['clinic'])), reverse('clinics:register'), fetch_redirect_response=False)

    def test_unapproved_professional_cannot_register_a_clinic(self):
        make_professional('waiting', status='submitted')
        self.as_user('waiting')
        self.assertRedirects(self.client.get(reverse('clinics:create')), reverse('accounts:welcome'), fetch_redirect_response=False)

    def test_submitting_the_form_creates_the_clinic_requests_the_plan_and_opens_the_dashboard(self):
        r = self.client.post(reverse('clinics:create'), CLINIC_DATA)
        clinic = Clinic.objects.get()
        self.assertRedirects(r, reverse('clinics:detail', args=[clinic.pk]) + '?tab=overview', fetch_redirect_response=False)
        self.assertTrue(clinic.code.startswith('CLI-') and len(clinic.code) == 10)
        self.assertEqual((clinic.owner, clinic.address, clinic.slot_minutes), (self.owner, 'Ward 3, Pulchowk, Lalitpur, Bagmati', 30))
        sub = ClinicSubscription.objects.get()
        self.assertEqual((sub.status, sub.contact_phone), ('requested', '015550001'))
        page = self.client.get(reverse('clinics:detail', args=[clinic.pk]))
        self.assertContains(page, 'Registration received')
        self.assertContains(page, 'complete')  # profile completeness card
        # until staff activate the plan, team and queue are locked
        for tab in ('team', 'queue', 'patients'):
            self.assertContains(self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': tab}), 'Waiting for plan activation')
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'name': 'Ram', 'role': 'receptionist'})
        self.assertFalse(ClinicMember.objects.exists())
        # one pending registration only
        self.client.post(reverse('clinics:create'), {**CLINIC_DATA, 'name': 'Second'})
        self.assertEqual(Clinic.objects.count(), 1)
        # activation unlocks everything
        ClinicSubscription.objects.update(status='active')
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'name': 'Ram', 'role': 'receptionist'})
        self.assertEqual(ClinicMember.objects.count(), 1)

    def test_only_a_few_fields_are_required_and_bad_values_are_rejected(self):
        bad = self.client.post(reverse('clinics:create'), {**CLINIC_DATA, 'phone': 'abc', 'pan_number': '!!', 'website': 'nope', 'email': 'x'})
        self.assertEqual(bad.status_code, 200)
        self.assertFalse(Clinic.objects.exists())
        missing = self.client.post(reverse('clinics:create'), {'name': 'No Province', 'phone': '015550001'})
        self.assertEqual(missing.status_code, 200)
        self.assertFalse(Clinic.objects.exists())

    def test_full_profile_hours_amenities_and_pictures(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        import tempfile

        def png(size):
            buf = io.BytesIO()
            Image.new('RGB', size, 'teal').save(buf, 'PNG')
            return SimpleUploadedFile('x.png', buf.getvalue(), content_type='image/png')

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            data = {**CLINIC_DATA, 'short_bio': 'Rehab for everyone', 'pan_number': 'PAN-123456', 'facility_license': 'HF/2081/77', 'specializations': ['sports', 'neurological'],
                    'phone_secondary': '9800000000', 'email': 'info@himal.example', 'website': 'https://himal.example', 'map_link': 'https://maps.example/x',
                    'amenities': ['parking', 'gym'], 'open_sunday': 'on', 'start_sunday': '09:00', 'end_sunday': '17:30',
                    'open_monday': 'on', 'start_monday': '10:00', 'end_monday': '16:00', 'logo': png((900, 600)), 'banner': png((2000, 800))}
            self.client.post(reverse('clinics:create'), data)
            clinic = Clinic.objects.get()
            self.assertEqual(clinic.hours, {'sunday': ['09:00', '17:30'], 'monday': ['10:00', '16:00']})
            self.assertEqual((clinic.specializations, clinic.amenities), (['sports', 'neurological'], ['parking', 'gym']))
            self.assertEqual(Image.open(clinic.banner.path).size, (1280, 720))  # cropped to 16:9
            self.assertLessEqual(max(Image.open(clinic.logo.path).size), 512)
            self.assertEqual(clinic.completeness()[0], 100)
            page = self.client.get(reverse('clinics:detail', args=[clinic.pk]))
            self.assertContains(page, '09:00 - 17:30')
            self.assertContains(page, 'Sports rehab, Neurological')
            # replacing a picture removes the old file
            import os
            old = clinic.logo.path
            update = {**data, 'logo': png((100, 100))}
            del update['banner']
            self.client.post(reverse('clinics:update', args=[clinic.pk]), update)
            clinic.refresh_from_db()
            self.assertFalse(os.path.exists(old))

    def test_closing_must_be_after_opening(self):
        r = self.client.post(reverse('clinics:create'), {**CLINIC_DATA, 'open_sunday': 'on', 'start_sunday': '18:00', 'end_sunday': '09:00'})
        self.assertContains(r, 'closing time must be after opening time')
        self.assertFalse(Clinic.objects.exists())

    def test_clinic_limit_is_enforced_once_active(self):
        self.activate(clinic_limit=1)
        self.client.post(reverse('clinics:create'), CLINIC_DATA)
        self.client.post(reverse('clinics:create'), {**CLINIC_DATA, 'name': 'Two'})
        self.assertEqual(Clinic.objects.count(), 1)

    def test_expired_plan_pauses_clinic_features(self):
        clinic = self.make_clinic()
        ClinicSubscription.objects.update(expires_at=timezone.localdate() - datetime.timedelta(days=1))
        self.assertFalse(Clinic.objects.get(pk=clinic.pk).is_usable)
        self.assertContains(self.client.get(reverse('clinics:hub')), 'expired')

    def test_blank_registration_numbers_do_not_collide(self):
        self.activate(clinic_limit=3)
        self.make_clinic('One')
        self.make_clinic('Two')
        self.assertEqual(Clinic.objects.count(), 2)

    def test_update_is_owner_only_and_validates(self):
        clinic = self.make_clinic()
        bad = self.client.post(reverse('clinics:update', args=[clinic.pk]), {**CLINIC_DATA, 'phone': 'abc'})
        self.assertContains(bad, 'valid phone number')
        self.client.post(reverse('clinics:update', args=[clinic.pk]), {**CLINIC_DATA, 'name': 'Renamed', 'short_bio': 'Hello'})
        clinic.refresh_from_db()
        self.assertEqual((clinic.name, clinic.short_bio), ('Renamed', 'Hello'))
        make_professional('rival')
        self.as_user('rival')
        self.assertEqual(self.client.post(reverse('clinics:update', args=[clinic.pk]), {**CLINIC_DATA, 'name': 'Hijack'}).status_code, 404)


class TeamTests(Base):
    def setUp(self):
        super().setUp()
        self.clinic = self.make_clinic()
        self.physio_user, self.physio = make_professional('physio', first_name='Bina', last_name='Thapa', license_number='NPC-12345')
        self.pending_user, self.pending = make_professional('pending', status='submitted', first_name='Pema', last_name='Sherpa')

    def search(self, q):
        return self.client.get(reverse('clinics:physio-search'), {'clinic': self.clinic.pk, 'q': q}).json()['results']

    def test_only_verified_physios_are_searchable_and_inviteable(self):
        self.assertEqual([r['name'] for r in self.search('Bina')], ['Bina Thapa'])
        self.assertEqual(self.search('Bina')[0]['licence'], '...2345')  # never the full number
        self.assertEqual(self.search('Pema'), [])  # credentials not verified
        self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': self.pending.pk})
        self.assertFalse(ClinicMember.objects.exists())

    def test_invitation_accept_and_leave_flow(self):
        self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': self.physio.pk})
        member = ClinicMember.objects.get()
        self.assertEqual(member.status, 'invited')
        self.assertEqual(self.search('Bina'), [])  # already invited
        # the invited physio is not a member until they accept: no access yet
        self.as_user('physio')
        self.assertEqual(self.client.get(reverse('clinics:detail', args=[self.clinic.pk])).status_code, 404)
        self.assertContains(self.client.get(reverse('clinics:hub')), 'Himal Clinic')
        self.client.post(reverse('clinics:invitation-respond', args=[member.pk]), {'action': 'accept'})
        member.refresh_from_db()
        self.assertEqual(member.status, 'active')
        self.assertEqual(self.client.get(reverse('clinics:detail', args=[self.clinic.pk])).status_code, 200)
        # a member may not manage the team or edit the clinic
        self.client.post(reverse('clinics:staff-add', args=[self.clinic.pk]), {'name': 'X', 'role': 'receptionist'})
        self.assertEqual(self.client.post(reverse('clinics:update', args=[self.clinic.pk]), {**CLINIC_DATA, 'name': 'Hijack'}).status_code, 404)
        # a patient the physio registers inside the clinic passes to the clinic when they leave
        self.client.post(reverse('accounts:patient-add') + f'?clinic={self.clinic.pk}', {**PATIENT, 'clinic': self.clinic.pk})
        patient = Patient.objects.get(name='Clinic Patient')
        self.assertEqual((patient.professional, patient.clinic), (self.physio, self.clinic))
        self.client.post(reverse('clinics:leave', args=[self.clinic.pk]))
        patient.refresh_from_db()
        self.assertEqual((patient.professional, patient.clinic), (self.owner, self.clinic))
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('clinics:detail', args=[self.clinic.pk])).status_code, 404)

    def test_decline_and_reinvite(self):
        self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': self.physio.pk})
        member = ClinicMember.objects.get()
        self.as_user('physio')
        self.client.post(reverse('clinics:invitation-respond', args=[member.pk]), {'action': 'decline'})
        member.refresh_from_db()
        self.assertEqual(member.status, 'declined')
        self.as_user('owner')
        self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': self.physio.pk})
        member.refresh_from_db()
        self.assertEqual((member.status, ClinicMember.objects.count()), ('invited', 1))

    def test_nobody_else_can_answer_my_invitation(self):
        self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': self.physio.pk})
        member = ClinicMember.objects.get()
        make_professional('other')
        self.as_user('other')
        self.assertEqual(self.client.post(reverse('clinics:invitation-respond', args=[member.pk]), {'action': 'accept'}).status_code, 404)

    def test_staff_records_and_removal(self):
        self.client.post(reverse('clinics:staff-add', args=[self.clinic.pk]), {'name': 'Ram Karki', 'role': 'receptionist', 'phone': '9800000009'})
        staff = ClinicMember.objects.get()
        self.assertEqual((staff.display_name, staff.role, staff.status), ('Ram Karki', 'receptionist', 'active'))
        self.client.post(reverse('clinics:staff-add', args=[self.clinic.pk]), {'name': 'Bad', 'role': 'physio'})  # physio is not a staff role
        self.assertEqual(ClinicMember.objects.count(), 1)
        self.assertContains(self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'team'}), 'Ram Karki')
        self.client.post(reverse('clinics:member-remove', args=[self.clinic.pk, staff.pk]))
        staff.refresh_from_db()
        self.assertEqual(staff.status, 'left')


PATIENT = {'name': 'Clinic Patient', 'date_of_birth': '1990-01-01', 'gender': 'F', 'phone': '9841234567', 'email': 'cp@example.com', 'address': 'Secret Street 9'}


class JoinedClinic(Base):
    """An owner with an active clinic and an accepted physio."""
    def setUp(self):
        super().setUp()
        self.clinic = self.make_clinic()
        self.physio_user, self.physio = make_professional('physio', first_name='Bina', last_name='Thapa')
        ClinicMember.objects.create(clinic=self.clinic, physio=self.physio, status='active', joined_at=timezone.now())

    def add_patient(self, **extra):
        self.client.post(reverse('accounts:patient-add') + f'?clinic={self.clinic.pk}', {**PATIENT, 'clinic': self.clinic.pk, **extra})
        return Patient.objects.get(name=extra.get('name', PATIENT['name']))


class ClinicPatientTests(JoinedClinic):
    def test_the_clinic_is_fixed_text_not_a_dropdown(self):
        page = self.client.get(reverse('accounts:patient-add'), {'clinic': self.clinic.pk})
        self.assertContains(page, 'Himal Clinic')
        self.assertContains(page, '<input type="hidden" name="clinic"')
        self.assertNotContains(page, '<select name="clinic"')
        self.assertNotContains(self.client.get(reverse('accounts:patient-add')), 'name="clinic"')  # a normal patient has no clinic at all
        self.assertNotContains(self.client.get(reverse('accounts:patients')), '<select name="clinic"')
        patient = self.add_patient()
        self.assertEqual(patient.clinic, self.clinic)
        # the edit page shows no way to move a patient to another clinic
        self.assertNotContains(self.client.get(reverse('accounts:patient-edit', args=[patient.pk])), '<select name="clinic"')

    def test_only_a_clinic_you_belong_to_is_accepted(self):
        _, other = make_professional('rival')
        foreign = Clinic.objects.create(owner=other, name='Rival Clinic', phone='015550002')
        ClinicSubscription.objects.create(professional=other, status='active')
        r = self.client.post(reverse('accounts:patient-add'), {**PATIENT, 'name': 'Sneaky', 'clinic': foreign.pk})
        self.assertRedirects(r, reverse('accounts:patients'), fetch_redirect_response=False)
        self.assertFalse(Patient.objects.filter(name='Sneaky').exists())
        self.assertRedirects(self.client.get(reverse('accounts:patient-add'), {'clinic': foreign.pk}), reverse('accounts:patients'), fetch_redirect_response=False)

    def test_team_members_can_view_and_treat_clinic_patients(self):
        patient = self.add_patient()  # registered by the owner
        self.as_user('physio')
        page = self.client.get(reverse('accounts:patient-detail', args=[patient.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Clinic patient')
        self.assertTrue(self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'patients'}).context['patients'])
        # treatment: record a visit, an assessment and a prescription
        r = self.client.post(reverse('accounts:patient-visit-add', args=[patient.pk]), {'date': timezone.localdate().isoformat(), 'session_type': 'treatment', 'progress': 'improving', 'notes': 'ok'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Visit.objects.get().patient, patient)
        self.assertEqual(self.client.get(reverse('assessments:choose', args=[patient.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:plan-new', args=[patient.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk]), {'tab': 'profile', 'section': 'medicine'}).status_code, 200)

    def test_outsiders_and_former_members_cannot_open_clinic_patients(self):
        patient = self.add_patient()
        make_professional('outsider')
        self.as_user('outsider')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])).status_code, 404)
        self.as_user('physio')
        ClinicMember.objects.filter(physio=self.physio).update(status='left')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])).status_code, 404)

    def test_expired_plan_closes_the_clinics_patients_to_the_team_but_not_the_owner(self):
        patient = self.add_patient()
        ClinicSubscription.objects.update(expires_at=timezone.localdate() - datetime.timedelta(days=1))
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])).status_code, 200)  # owner registered it
        self.as_user('physio')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])).status_code, 404)

    def test_physios_never_see_contact_details_of_clinic_patients_but_the_owner_does(self):
        patient = self.add_patient()
        owner_page = self.client.get(reverse('accounts:patient-detail', args=[patient.pk]))
        self.assertContains(owner_page, '9841234567')
        self.assertContains(owner_page, 'Secret Street 9')
        self.assertContains(self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'patients'}), '9841234567')
        self.as_user('physio')
        for url in (reverse('accounts:patient-detail', args=[patient.pk]), reverse('accounts:patient-edit', args=[patient.pk]),
                    reverse('clinics:detail', args=[self.clinic.pk]) + '?tab=patients', reverse('clinics:detail', args=[self.clinic.pk]) + '?tab=queue'):
            body = self.client.get(url).content.decode()
            for secret in ('9841234567', 'cp@example.com', 'Secret Street 9'):
                self.assertNotIn(secret, body, f'{secret} leaked on {url}')
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])), 'kept private')
        # editing cannot overwrite the hidden details either
        self.client.post(reverse('accounts:patient-edit', args=[patient.pk]), {'name': 'Clinic Patient', 'date_of_birth': '1990-01-01', 'gender': 'F', 'status': 'active', 'phone': '1', 'email': 'x@example.com', 'address': 'changed'})
        patient.refresh_from_db()
        self.assertEqual((patient.phone, patient.email, patient.address), ('9841234567', 'cp@example.com', 'Secret Street 9'))

    def test_a_physios_own_registrations_in_the_clinic_hide_the_number_from_them_too(self):
        self.as_user('physio')
        patient = self.add_patient(name='Registered By Physio')
        self.assertEqual((patient.professional, patient.clinic), (self.physio, self.clinic))
        for url in (reverse('accounts:patients'), reverse('accounts:patient-detail', args=[patient.pk])):
            self.assertNotContains(self.client.get(url), '9841234567')
        self.assertEqual(self.client.get(reverse('accounts:appointment-patient-search'), {'q': 'Registered'}).json()['results'][0]['phone'], '')
        self.assertEqual(self.client.get(reverse('accounts:patients'), {'q': '9841234567'}).context['page_obj'].paginator.count, 0)  # cannot search by the hidden number
        self.as_user('owner')
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])), '9841234567')  # the owner can see it

    def test_private_patients_stay_private_and_normal_numbers_are_visible(self):
        mine = make_patient(self.physio, 'Private One', phone='9811111111')
        self.as_user('physio')
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[mine.pk])), '9811111111')
        self.as_user('owner')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[mine.pk])).status_code, 404)


class InvitationChannelTests(JoinedClinic):
    def test_invited_physio_is_notified_everywhere_and_can_accept(self):
        _, newbie = make_professional('newbie', first_name='Nina', last_name='Rai')
        self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': newbie.pk})
        self.as_user('newbie')
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).context['clinic_invites'], 1)
        self.assertContains(self.client.get(reverse('accounts:dashboard')), 'You have 1 clinic invitation')
        self.assertContains(self.client.get(reverse('accounts:patients')), 'nav-badge')
        hub = self.client.get(reverse('clinics:hub'))
        self.assertContains(hub, 'Invitations to join a clinic (1)')
        self.assertContains(hub, 'contact details')  # tells them what they will and will not see
        member = ClinicMember.objects.get(physio=newbie)
        self.client.post(reverse('clinics:invitation-respond', args=[member.pk]), {'action': 'accept'})
        self.assertNotContains(self.client.get(reverse('accounts:dashboard')), 'clinic invitation')
        hub = self.client.get(reverse('clinics:hub'))
        self.assertContains(hub, 'Clinics I work at')
        self.assertContains(hub, 'View patients')

    def test_the_hub_tracks_current_and_previous_clinics(self):
        self.as_user('physio')
        self.assertContains(self.client.get(reverse('clinics:hub')), 'Himal Clinic')
        self.client.post(reverse('clinics:leave', args=[self.clinic.pk]))
        hub = self.client.get(reverse('clinics:hub'))
        self.assertContains(hub, 'Previous clinics')
        self.assertNotContains(hub, 'Clinics I work at')


class QueueTests(JoinedClinic):
    def test_queue_lifecycle_with_the_clinics_patients(self):
        patient = self.add_patient()
        add = reverse('clinics:queue-add', args=[self.clinic.pk])
        self.client.post(add, {'patient_id': patient.pk})
        self.client.post(add, {'patient_id': patient.pk})  # duplicate ignored
        entry = QueueEntry.objects.get()
        self.assertEqual((entry.status, entry.added_by), ('waiting', self.owner))
        act = reverse('clinics:queue-action', args=[self.clinic.pk, entry.pk])
        # a physio on the team can work the queue too
        self.as_user('physio')
        self.assertContains(self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'queue'}), 'Clinic Patient')
        self.client.post(act, {'action': 'call'})
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'called')
        self.client.post(act, {'action': 'complete'})
        entry.refresh_from_db()
        self.assertEqual((entry.status, bool(entry.finished_at)), ('completed', True))
        self.client.post(act, {'action': 'call'})  # cannot go backwards
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'completed')
        self.client.post(add, {'patient_id': patient.pk})
        self.assertEqual(QueueEntry.objects.count(), 2)

    def test_queue_search_gives_names_only_and_only_clinic_patients(self):
        patient = self.add_patient()
        make_patient(self.owner, 'Private Person')
        results = self.client.get(reverse('clinics:patient-search', args=[self.clinic.pk]), {'q': 'Person'}).json()['results']
        self.assertEqual(results, [])
        results = self.client.get(reverse('clinics:patient-search', args=[self.clinic.pk]), {'q': 'Clinic'}).json()['results']
        self.assertEqual([(r['name'], r['phone']) for r in results], [('Clinic Patient', '')])
        self.client.post(reverse('clinics:queue-add', args=[self.clinic.pk]), {'patient_id': Patient.objects.get(name='Private Person').pk})
        self.assertFalse(QueueEntry.objects.exists())

    def test_outsiders_cannot_touch_the_queue(self):
        patient = self.add_patient()
        self.client.post(reverse('clinics:queue-add', args=[self.clinic.pk]), {'patient_id': patient.pk})
        entry = QueueEntry.objects.get()
        make_professional('rival')
        self.as_user('rival')
        self.assertEqual(self.client.post(reverse('clinics:queue-action', args=[self.clinic.pk, entry.pk]), {'action': 'call'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('clinics:patient-search', args=[self.clinic.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('clinics:detail', args=[self.clinic.pk])).status_code, 404)

    def test_overview_counts_visits_by_therapist_without_patient_details(self):
        patient = self.add_patient()
        Visit.objects.create(patient=patient, date=timezone.localdate(), therapist='Bina Thapa')
        Visit.objects.create(patient=patient, date=timezone.localdate(), therapist='Bina Thapa')
        page = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'overview'})
        self.assertEqual(page.context['month_visits'], 2)
        self.assertEqual(page.context['activity'], [{'name': 'Bina Thapa', 'visits': 2, 'patients': 1}])  # counts per therapist, no patient names


class GateTests(Base):
    def test_unapproved_professional_is_locked_out(self):
        make_professional('waiting', status='submitted')
        self.as_user('waiting')
        self.assertRedirects(self.client.get(reverse('clinics:hub')), reverse('accounts:welcome'), fetch_redirect_response=False)


class MonthlyUsageTests(JoinedClinic):
    """New patients enrolled per month, and the charge once a clinic goes over its cap."""

    def enrol(self, count, when=None, clinic=None, owner=None):
        made = []
        for i in range(count):
            p = make_patient(owner or self.owner, f'Enrolled {Patient.objects.count()}', clinic=clinic or self.clinic)
            if when:
                Patient.objects.filter(pk=p.pk).update(created_at=when)
            made.append(p)
        return made

    def test_counts_only_this_clinic_and_this_month(self):
        from . import usage
        first = usage.first_of_month(timezone.localdate())
        self.enrol(3)
        self.enrol(2, when=timezone.now() - datetime.timedelta(days=45))  # an earlier month
        other = Clinic.objects.create(owner=self.owner, name='Other', phone='015550009')
        self.enrol(4, clinic=other)
        make_patient(self.owner, 'Private, no clinic')
        self.assertEqual(usage.enrolled_in_month(self.clinic, first), 3)
        row = usage.refresh(self.clinic, first)
        self.assertEqual((row.enrolled, row.cap, row.overage, row.amount_due, row.status), (3, 400, 0, 0, 'open'))

    def test_going_over_the_cap_becomes_a_due(self):
        from . import usage
        ClinicSubscription.objects.update(monthly_patient_cap=5, overage_rate=200)
        self.enrol(8)
        row = usage.refresh(self.clinic, usage.first_of_month(timezone.localdate()))
        self.assertEqual((row.enrolled, row.overage, row.amount_due, row.status), (8, 3, 600, 'due'))
        self.assertEqual(usage.summary(self.clinic)['total_due'], 600)
        self.enrol(1)
        row.refresh_from_db()
        self.assertEqual(usage.refresh(self.clinic, row.month).amount_due, 800)  # still accruing during the month

    def test_adding_patients_is_never_blocked_by_the_cap(self):
        ClinicSubscription.objects.update(monthly_patient_cap=1)
        self.add_patient(name='First')
        self.add_patient(name='Second')
        self.assertEqual(self.clinic.patients.count(), 2)

    def test_defaults_are_400_and_200_and_the_subscription_can_override(self):
        from . import usage
        sub = ClinicSubscription.objects.get()
        self.assertEqual((sub.monthly_patient_cap, sub.overage_rate), (400, 200))
        self.enrol(3)
        ClinicSubscription.objects.update(monthly_patient_cap=2, overage_rate=350)
        row = usage.refresh(self.clinic, usage.first_of_month(timezone.localdate()))
        self.assertEqual((row.cap, row.rate, row.amount_due), (2, 350, 350))

    def test_previous_months_stay_due_until_marked_paid_then_freeze(self):
        from . import usage
        ClinicSubscription.objects.update(monthly_patient_cap=2, overage_rate=200)
        last_month = usage.previous_month(usage.first_of_month(timezone.localdate()))
        Clinic.objects.filter(pk=self.clinic.pk).update(created_at=timezone.now() - datetime.timedelta(days=120))
        self.clinic.refresh_from_db()
        mid_last_month = timezone.make_aware(datetime.datetime.combine(last_month + datetime.timedelta(days=10), datetime.time(12)))
        self.enrol(5, when=mid_last_month)
        summary = usage.summary(self.clinic)
        old = next(r for r in summary['rows'] if r.month == last_month)
        self.assertEqual((old.enrolled, old.amount_due, old.status), (5, 600, 'due'))
        self.assertEqual(summary['total_due'], 600)
        # staff mark it paid in the admin: it freezes even if the underlying records change
        staff = make_professional('staffer', staff=True)[0]
        staff.is_superuser = True
        staff.save()
        self.client.force_login(staff)
        self.client.post(reverse('admin:clinics_clinicmonthlyusage_changelist'), {'action': 'mark_paid', '_selected_action': [old.pk]})
        old.refresh_from_db()
        self.assertEqual((old.status, bool(old.paid_at)), ('paid', True))
        Patient.objects.filter(clinic=self.clinic).update(clinic=None)
        again = usage.refresh(self.clinic, last_month)
        self.assertEqual((again.enrolled, again.amount_due, again.status), (5, 600, 'paid'))
        self.assertEqual(usage.summary(self.clinic)['total_due'], 0)

    def test_overview_shows_the_meter_and_dues_to_the_owner_only(self):
        ClinicSubscription.objects.update(monthly_patient_cap=3, overage_rate=200)
        self.enrol(5)
        page = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]))
        self.assertContains(page, 'New patients enrolled this month')
        self.assertContains(page, '2 over the cap')
        self.assertContains(page, 'Due before next billing: NPR 400')
        self.as_user('physio')
        page = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]))
        self.assertContains(page, 'New patients enrolled this month')  # the team sees the count
        self.assertNotContains(page, 'Due before next billing: NPR')  # money is the owner's business

    def test_the_monthly_command_prints_what_is_due(self):
        from io import StringIO
        from django.core.management import call_command
        ClinicSubscription.objects.update(monthly_patient_cap=1, overage_rate=200)
        self.enrol(3)
        out = StringIO()
        call_command('clinic_usage', stdout=out)
        self.assertIn('2 over the cap of 1 -> NPR 400 due', out.getvalue())
        self.assertIn('Total due across clinics: NPR 400', out.getvalue())


class ClinicWorkspaceTests(Base):
    def test_each_clinic_has_its_own_workspace_with_its_own_menu_and_a_switcher(self):
        first = self.make_clinic('Himal Clinic')
        self.client.post(reverse('clinics:create'), {**CLINIC_DATA, 'name': 'Lake Clinic'})
        second = Clinic.objects.filter(name='Lake Clinic').first()
        if second is None:  # the plan allows one clinic: raise the allowance by registering through the model
            second = Clinic.objects.create(owner=self.owner, name='Lake Clinic', phone='015550002')
        page = self.client.get(reverse('clinics:detail', args=[first.pk]))
        self.assertContains(page, 'Himal Clinic · clinic workspace')  # the header names this clinic, not "Professional workspace"
        for label in ('Overview', 'Team', 'Queue', 'Clinic details'):
            self.assertContains(page, f'<span class="nav-text">{label}</span>')
        self.assertNotContains(page, '<span class="nav-text">Exercise Library</span>')  # the professional menu is replaced
        self.assertContains(page, reverse('clinics:detail', args=[second.pk]))  # switch clinic
        self.assertContains(page, reverse('accounts:dashboard'))  # and a way back to the personal dashboard

    def test_a_visiting_physio_does_not_see_the_owners_settings_item(self):
        clinic = self.make_clinic()
        guest_user, guest = make_professional('guest')
        ClinicMember.objects.create(clinic=clinic, physio=guest, role=ClinicMember.PHYSIO, status=ClinicMember.ACTIVE)
        self.as_user('guest')
        page = self.client.get(reverse('clinics:detail', args=[clinic.pk]))
        self.assertContains(page, '<span class="nav-text">Team</span>')
        self.assertNotContains(page, '<span class="nav-text">Clinic details</span>')


class ClinicLoginTests(Base):
    LOGIN = {'username': 'himal-desk', 'password1': PASSWORD, 'password2': PASSWORD}

    def set_login(self, clinic, **extra):
        return self.client.post(reverse('clinics:login', args=[clinic.pk]), {**self.LOGIN, **extra})

    def test_owner_sets_the_clinic_login_and_the_clinic_gets_a_full_workspace_of_its_own(self):
        clinic = self.make_clinic()
        self.assertContains(self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'settings'}), 'Create clinic login')
        r = self.set_login(clinic)
        self.assertRedirects(r, reverse('clinics:detail', args=[clinic.pk]) + '?tab=settings', fetch_redirect_response=False)
        clinic.refresh_from_db()
        self.assertEqual((clinic.workspace.account.user.username, clinic.workspace.status, clinic.workspace.account.account_type), ('himal-desk', 'approved', 'clinic'))
        self.assertTrue(clinic.workspace.account.user.check_password(self.LOGIN['password1']))

        self.client.logout()
        self.assertTrue(self.client.login(username='himal-desk', password=self.LOGIN['password1']))
        for name in ('accounts:dashboard', 'accounts:patients', 'accounts:appointments', 'accounts:plans', 'billing:billing', 'accounts:reports', 'exercises:library'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        sidebar = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(sidebar, 'Clinic &amp; team')
        self.assertContains(self.client.get(reverse('clinics:detail', args=[clinic.pk])), 'Himal Clinic')

    def test_patients_added_by_the_clinic_login_belong_to_the_clinic_and_are_seen_by_its_team(self):
        clinic = self.make_clinic()
        self.set_login(clinic)
        guest_user, guest = make_professional('guest')
        ClinicMember.objects.create(clinic=clinic, physio=guest, role=ClinicMember.PHYSIO, status=ClinicMember.ACTIVE)
        self.as_user('himal-desk')
        r = self.client.post(reverse('accounts:patient-add'), {'name': 'Front Desk Patient', 'phone': '9841111111', 'gender': 'F', 'date_of_birth': '1990-01-02'})
        self.assertRedirects(r, reverse('accounts:patients'), fetch_redirect_response=False)  # stays in the clinic's workspace
        clinic.refresh_from_db()
        patient = Patient.objects.get(name='Front Desk Patient')
        self.assertEqual((patient.clinic, patient.professional), (clinic, clinic.workspace))
        self.as_user('guest')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])).status_code, 200)

    def test_only_the_owning_physio_can_change_the_login_and_usernames_are_unique(self):
        clinic = self.make_clinic()
        self.assertEqual(self.set_login(clinic, username='owner').context['login_form'].errors['username'][0], 'That username is already taken. Choose another.')
        self.assertEqual(self.set_login(clinic, password2='different').context['login_form'].errors['password2'][0], 'The two passwords do not match.')
        self.assertEqual(self.set_login(clinic, password1='short', password2='short').status_code, 200)
        clinic.refresh_from_db()
        self.assertIsNone(clinic.workspace_id)
        self.set_login(clinic)
        self.set_login(clinic, username='himal-new', password1='An0ther!Desk-Pass-88', password2='An0ther!Desk-Pass-88')  # changing it later keeps the same workspace
        clinic.refresh_from_db()
        self.assertEqual(clinic.workspace.account.user.username, 'himal-new')
        self.client.logout()
        self.assertTrue(self.client.login(username='himal-new', password='An0ther!Desk-Pass-88'))  # the clinic's own login cannot rename itself
        self.assertEqual(self.set_login(clinic, username='sneaky').status_code, 404)
        stranger, _ = make_professional('stranger')
        self.as_user('stranger')
        self.assertEqual(self.set_login(clinic).status_code, 404)

    def test_add_team_lives_in_an_actions_menu_with_both_forms(self):
        clinic = self.make_clinic()
        page = self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'team'})
        self.assertContains(page, 'data-open="addTeamModal"')
        self.assertContains(page, reverse('clinics:invite', args=[clinic.pk]))
        self.assertContains(page, reverse('clinics:staff-add', args=[clinic.pk]))


class StaffLoginTests(Base):
    """Staff (manager, receptionist, assistant, other) sign in to a limited front desk the owner gave them."""
    CREDS = {'username': 'ram-desk', 'password1': PASSWORD, 'password2': PASSWORD}

    def add_staff(self, clinic, name='Ram', role='receptionist', **creds):
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'name': name, 'role': role})
        member = ClinicMember.objects.get(clinic=clinic, name=name)
        self.client.post(reverse('clinics:staff-login', args=[clinic.pk, member.pk]), {**self.CREDS, **creds})
        member.refresh_from_db()
        return member

    def test_owner_gives_a_staff_member_a_login_that_opens_the_front_desk(self):
        clinic = self.make_clinic()
        member = self.add_staff(clinic)
        self.assertEqual((member.user.username, member.user.account.account_type), ('ram-desk', 'staff'))
        self.assertContains(self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'team'}), 'Login: ram-desk')
        self.client.logout()
        r = self.client.post(reverse('accounts:login'), {'username': 'ram-desk', 'password': PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertRedirects(self.client.get(reverse('accounts:welcome')), reverse('clinics:desk'), fetch_redirect_response=False)
        page = self.client.get(reverse('clinics:desk'))
        self.assertContains(page, 'Himal Clinic')
        self.assertContains(page, 'Register patient')
        self.assertNotContains(page, 'Clinic details')
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 404)  # no clinical workspace
        self.assertEqual(self.client.get(reverse('clinics:detail', args=[clinic.pk])).status_code, 404)

    def test_only_the_owner_can_set_staff_logins_and_usernames_are_unique(self):
        clinic = self.make_clinic()
        member = self.add_staff(clinic)
        other = self.add_staff(clinic, name='Sita', username='ram-desk')
        self.assertIsNone(other.user)  # taken
        self.add_staff(clinic, name='Gita', username='gita-desk')
        self.client.post(reverse('clinics:staff-login', args=[clinic.pk, member.pk]), {'username': 'ram2', 'password1': PASSWORD, 'password2': PASSWORD})
        member.refresh_from_db()
        self.assertEqual(member.user.username, 'ram2')  # changed, same user
        self.client.post(reverse('clinics:staff-login', args=[clinic.pk, member.pk]), {'username': 'ram3', 'password1': 'short', 'password2': 'short'})
        member.refresh_from_db()
        self.assertEqual(member.user.username, 'ram2')  # weak password refused
        self.as_user('gita-desk')
        r = self.client.post(reverse('clinics:staff-login', args=[clinic.pk, member.pk]), {'username': 'hacked', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertEqual(r.status_code, 404)

    def test_receptionist_registers_patients_and_runs_the_queue_but_sees_no_clinical_data(self):
        clinic = self.make_clinic()
        self.add_staff(clinic)
        self.as_user('ram-desk')
        r = self.client.post(reverse('clinics:desk-register'), {'name': 'Walk In', 'phone': '9841000111', 'gender': 'F', 'date_of_birth': '1991-03-04', 'diagnosis': 'Injected'})
        patient = Patient.objects.get(name='Walk In')
        self.assertEqual((patient.clinic, patient.professional, patient.diagnosis), (clinic, self.owner, ''))
        self.assertRedirects(r, reverse('clinics:desk') + '?tab=queue', fetch_redirect_response=False)
        self.client.post(reverse('clinics:desk-queue-add'), {'patient_id': patient.pk})
        entry = QueueEntry.objects.get()
        self.client.post(reverse('clinics:desk-queue-action', args=[entry.pk]), {'action': 'call'})
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'called')
        page = self.client.get(reverse('clinics:desk'), {'tab': 'patients'})
        self.assertContains(page, '9841000111')
        self.assertNotContains(page, 'Injected')
        self.assertNotContains(self.client.get(reverse('clinics:desk'), {'tab': 'team'}), 'Owner / physiotherapist')  # a receptionist has no team tab

    def test_roles_limit_what_staff_can_do(self):
        clinic = self.make_clinic()
        patient = make_patient(self.owner, name='Someone', phone='9841999999')
        patient.clinic = clinic
        patient.save()
        self.add_staff(clinic, 'Asha', 'assistant', username='asha')
        self.add_staff(clinic, 'Omi', 'other', username='omi')
        self.add_staff(clinic, 'Mani', 'manager', username='mani')
        self.as_user('asha')
        page = self.client.get(reverse('clinics:desk'), {'tab': 'patients'})
        self.assertContains(page, 'Someone')
        self.assertNotContains(page, '9841999999')  # no contact details for an assistant
        self.assertEqual(self.client.post(reverse('clinics:desk-register'), {'name': 'No'}).status_code, 404)
        self.client.post(reverse('clinics:desk-queue-add'), {'patient_id': patient.pk})
        entry = QueueEntry.objects.get()
        self.client.post(reverse('clinics:desk-queue-action', args=[entry.pk]), {'action': 'cancel'})
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'waiting')  # an assistant cannot cancel
        self.as_user('omi')
        self.assertNotContains(self.client.get(reverse('clinics:desk'), {'tab': 'patients'}), 'tab=patients')  # only the queue tab exists
        self.assertEqual(self.client.post(reverse('clinics:desk-queue-add'), {'patient_id': patient.pk}).status_code, 404)
        self.as_user('mani')
        self.assertContains(self.client.get(reverse('clinics:desk')), 'Waiting today')

    def test_removed_staff_cannot_sign_in(self):
        clinic = self.make_clinic()
        member = self.add_staff(clinic)
        self.client.post(reverse('clinics:member-remove', args=[clinic.pk, member.pk]))
        self.client.logout()
        self.assertFalse(self.client.login(username='ram-desk', password=PASSWORD))

    def test_the_desk_is_for_staff_only(self):
        clinic = self.make_clinic()
        self.add_staff(clinic)
        make_professional('stranger')
        self.as_user('stranger')
        self.assertEqual(self.client.get(reverse('clinics:desk')).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('clinics:desk')).status_code, 302)
