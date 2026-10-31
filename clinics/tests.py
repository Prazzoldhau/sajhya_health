import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Patient, Visit
from accounts.tests.helpers import PASSWORD, make_patient, make_professional

from billing.models import BillingEntry
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
        # a team member cannot add patients to the clinic
        refused = self.client.post(reverse('accounts:patient-add') + f'?clinic={self.clinic.pk}', {**PATIENT, 'clinic': self.clinic.pk})
        self.assertRedirects(refused, reverse('accounts:patients'), fetch_redirect_response=False)
        self.assertFalse(Patient.objects.filter(name='Clinic Patient').exists())
        # a patient they registered in the clinic earlier passes to the clinic when they leave
        patient = make_patient(self.physio, 'Clinic Patient', clinic=self.clinic)
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

    def assign(self, patient, physio=None):
        """Assign a clinic patient to a physio on the team (a team member only sees the patients assigned to them)."""
        patient.assigned.add(ClinicMember.objects.get(clinic=self.clinic, physio=physio or self.physio))


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
        self.assign(patient)
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
        self.assign(patient)
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
        patient = make_patient(self.physio, 'Registered By Physio', phone='9841234567', email='cp@example.com', address='Secret Street 9', clinic=self.clinic)  # from before members could not add
        self.as_user('physio')
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
        self.assign(patient)
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
        guest_member = ClinicMember.objects.create(clinic=clinic, physio=guest, role=ClinicMember.PHYSIO, status=ClinicMember.ACTIVE)
        self.as_user('himal-desk')
        r = self.client.post(reverse('accounts:patient-add'), {'name': 'Front Desk Patient', 'phone': '9841111111', 'gender': 'F', 'date_of_birth': '1990-01-02'})
        self.assertRedirects(r, reverse('accounts:patients'), fetch_redirect_response=False)  # stays in the clinic's workspace
        clinic.refresh_from_db()
        patient = Patient.objects.get(name='Front Desk Patient')
        self.assertEqual((patient.clinic, patient.professional), (clinic, clinic.workspace))
        self.as_user('guest')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])).status_code, 404)  # not assigned to them
        patient.assigned.add(guest_member)
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
        self.assertContains(self.client.get(reverse('clinics:desk')), 'Waiting in queue')

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


class PasswordToggleTests(Base):
    def test_every_page_with_a_password_box_loads_the_show_hide_control(self):
        clinic = self.make_clinic()
        for page in (self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'settings'}),
                     self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'team'}),
                     self.client.get(reverse('accounts:password-change'))):
            self.assertContains(page, 'js/pw-toggle.js')
        self.client.logout()
        self.assertContains(self.client.get(reverse('accounts:signup-client')), 'js/pw-toggle.js')
        self.assertContains(self.client.get(reverse('accounts:login')), 'js/pw-toggle.js')


class FrontDeskRegisteredByAndBillingTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff

    """Reception's registrations show who made them and reach the clinic's own workspace; reception can bill."""
    def setup_desk(self):
        clinic = self.make_clinic()
        self.client.post(reverse('clinics:login', args=[clinic.pk]), {'username': 'himal-clinic', 'password1': PASSWORD, 'password2': PASSWORD})
        self.add_staff(clinic, 'Ram', 'receptionist', username='ram-desk')
        self.add_staff(clinic, 'Asha', 'assistant', username='asha')
        self.add_staff(clinic, 'Mani', 'manager', username='mani')
        clinic.refresh_from_db()
        return clinic

    def register(self, **extra):
        return self.client.post(reverse('clinics:desk-register'), {'name': 'Walk In', 'phone': '9841000111', 'gender': 'F', 'date_of_birth': '1991-03-04', **extra})

    def test_a_patient_registered_by_reception_shows_who_registered_them_everywhere(self):
        clinic = self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        patient = Patient.objects.get(name='Walk In')
        self.assertEqual((patient.registered_by_name, patient.registered_by_role, patient.clinic), ('Ram', 'Receptionist', clinic))
        self.assertContains(self.client.get(reverse('clinics:desk'), {'tab': 'patients'}), 'Ram (Receptionist)')
        self.as_user('owner')
        page = self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'patients'})
        self.assertContains(page, 'Walk In')
        self.assertContains(page, 'Ram')  # not the owner's name
        self.as_user('himal-clinic')  # the clinic's own login sees it in its workspace patient list, dashboard and calendar search
        self.assertContains(self.client.get(reverse('accounts:patients')), 'Walk In')
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).context['stats']['total'], 1)
        self.assertEqual([p['name'] for p in self.client.get(reverse('accounts:appointment-patient-search'), {'q': 'Walk'}).json()['results']], ['Walk In'])
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[patient.pk])), 'Walk In')
        # patients added by the clinic login are stamped too
        self.client.post(reverse('accounts:patient-add'), {'name': 'Own Add', 'phone': '9800000001', 'gender': 'M', 'date_of_birth': '1980-01-01'})
        stamp = Patient.objects.get(name='Own Add')
        self.assertEqual((stamp.registered_by_name, stamp.registered_by_role), ('Himal Clinic', 'Clinic login'))

    def test_age_can_replace_the_date_of_birth(self):
        self.setup_desk()
        self.as_user('ram-desk')
        self.register(name='By Age', date_of_birth='', age='35')
        patient = Patient.objects.get(name='By Age')
        self.assertEqual((patient.age, patient.dob_is_estimate), (35, True))
        self.assertIn('approx', patient.age_label)
        self.register(name='Nothing', date_of_birth='')  # neither is fine: both are optional
        nothing = Patient.objects.get(name='Nothing')
        self.assertEqual((nothing.date_of_birth, nothing.age, nothing.dob_is_estimate), (None, None, False))
        self.register(name='Both', date_of_birth='1990-05-05', age='10')  # a real date wins
        both = Patient.objects.get(name='Both')
        self.assertEqual((both.date_of_birth.isoformat(), both.dob_is_estimate), ('1990-05-05', False))
        self.as_user('himal-clinic')
        self.client.post(reverse('accounts:patient-add'), {'name': 'Pro Add', 'phone': '9800000002', 'gender': 'F', 'age': '60'})
        self.assertEqual(Patient.objects.get(name='Pro Add').age, 60)
        self.assertContains(self.client.get(reverse('accounts:patient-edit', args=[patient.pk])), 'name="age"')

    def test_reception_handles_billing_and_it_records_who_billed(self):
        clinic = self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        patient = Patient.objects.get(name='Walk In')
        self.assertContains(self.client.get(reverse('clinics:desk')), f'href="{reverse("billing:billing")}"')  # the full billing pages, now that the clinic has its own login
        bill = {'patient_id': patient.pk, 'entry_date': timezone.localdate().isoformat(), 'service': 'Therapy', 'rate': '700', 'payment_mode': 'cash'}
        self.client.post(reverse('clinics:desk-bill-create'), {**bill, 'payment_status': 'paid', 'amount_given': '1000'})  # no change: 300 carried over
        first = BillingEntry.objects.get()
        self.assertEqual((first.created_by_name, first.created_by_role, first.professional, first.status_key), ('Ram', 'Receptionist', clinic.workspace, 'paid'))
        from billing.models import advance_balance
        self.assertEqual(advance_balance(patient.pk), 300)
        self.client.post(reverse('clinics:desk-bill-create'), {**bill, 'payment_status': 'due'})
        due = BillingEntry.objects.exclude(pk=first.pk).get()
        page = self.client.get(reverse('clinics:desk'), {'tab': 'billing'})
        self.assertContains(page, 'BILLED BY')
        self.assertContains(page, 'wa.me')
        self.client.post(reverse('clinics:desk-bill-payment', args=[due.pk]), {'amount': '300', 'payment_mode': 'advance'})
        self.client.post(reverse('clinics:desk-bill-payment', args=[due.pk]), {'amount': '500', 'payment_mode': 'cash'})  # 400 owed: 100 extra kept
        due.refresh_from_db()
        self.assertEqual((due.status_key, advance_balance(patient.pk)), ('paid', 100))
        pdf = self.client.get(reverse('clinics:desk-bill-pdf', args=[due.pk]))
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.as_user('himal-clinic')  # the clinic's own login sees the same bills in its Billing page, with who billed
        self.assertContains(self.client.get(reverse('billing:billing')), 'Billed by Ram')

    def test_other_roles_and_clinics_are_kept_out_of_desk_billing(self):
        self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        patient = Patient.objects.get(name='Walk In')
        bill = {'patient_id': patient.pk, 'entry_date': timezone.localdate().isoformat(), 'service': 'T', 'rate': '100', 'payment_mode': 'cash', 'payment_status': 'due'}
        self.client.post(reverse('clinics:desk-bill-create'), bill)
        entry = BillingEntry.objects.get()
        self.as_user('asha')  # an assistant has no billing
        self.assertEqual(self.client.post(reverse('clinics:desk-bill-create'), bill).status_code, 404)
        self.assertEqual(self.client.get(reverse('clinics:desk-bill-pdf', args=[entry.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('clinics:desk')), 'tab=billing')
        self.as_user('mani')  # a manager does
        self.assertEqual(self.client.get(reverse('clinics:desk'), {'tab': 'billing'}).status_code, 200)
        self.client.post(reverse('clinics:desk-bill-create'), {**bill, 'patient_id': 999999})
        self.assertEqual(BillingEntry.objects.count(), 1)  # a patient that is not the clinic's cannot be billed


class ClinicLoginBillsFrontDeskPatientTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    register = FrontDeskRegisteredByAndBillingTests.register

    """The clinic's own login bills (and packages) a patient reception registered: it was refused with 'Select a valid choice'."""
    def test_clinic_login_can_bill_and_start_a_package_for_a_patient_the_front_desk_registered(self):
        from billing.models import PatientPackage
        self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        patient = Patient.objects.get(name='Walk In')
        self.as_user('himal-clinic')
        today = timezone.localdate().isoformat()
        r = self.client.post(reverse('billing:entry-create'), {'entry_date': today, 'patient': patient.pk, 'patient_name': 'Walk In', 'age': '32', 'sex': 'F', 'contact_number': '9841000111',
                                                              'service': 'Physiotherapy', 'rate': '500', 'payment_mode': 'cash', 'payment_status': 'paid', 'amount_given': '1000'})
        self.assertEqual(r.status_code, 302)
        entry = BillingEntry.objects.get()
        self.assertEqual((entry.patient, entry.status_key, entry.carried_over), (patient, 'paid', 500))
        self.client.post(reverse('billing:package-create'), {'patient': patient.pk, 'duration': '10_day', 'total_sessions': 10, 'total_amount': '5000', 'amount_paid_now': '0', 'start_date': today})
        self.assertEqual(PatientPackage.objects.get().patient, patient)
        self.assertEqual(self.client.get(reverse('accounts:reports'), {'from': today, 'to': today}).status_code, 200)


class DeskBillingExportTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    register = FrontDeskRegisteredByAndBillingTests.register

    def test_reception_and_managers_download_the_clinics_bills_and_others_cannot(self):
        import io

        from openpyxl import load_workbook
        clinic = self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        patient = Patient.objects.get(name='Walk In')
        today = timezone.localdate().isoformat()
        self.client.post(reverse('clinics:desk-bill-create'), {'patient_id': patient.pk, 'entry_date': today, 'service': 'Therapy', 'rate': '700', 'payment_mode': 'cash', 'payment_status': 'paid'})
        # a bill of another clinic's patient must never be in this clinic's file
        outsider_user, outsider = make_professional('other-physio')
        stranger = make_patient(outsider, 'Elsewhere')
        BillingEntry.objects.create(professional=outsider, patient=stranger, patient_name='Elsewhere', rate=999, entry_date=timezone.localdate())
        r = self.client.get(reverse('clinics:desk-bill-export'), {'from': today, 'to': today})
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))
        wb = load_workbook(io.BytesIO(r.content))
        bills = wb['Bills']
        self.assertEqual([bills.cell(row=2, column=c).value for c in (3, 5, 7, 13)], ['Walk In', '9841000111', 700, 'Ram / Receptionist'])  # patient, phone, amount, who billed
        self.assertEqual(bills.max_row, 3)  # header, the one bill and the total row
        self.assertEqual(wb['Summary']['A1'].value, clinic.name)
        self.as_user('mani')
        self.assertEqual(self.client.get(reverse('clinics:desk-bill-export')).status_code, 200)
        self.assertContains(self.client.get(reverse('clinics:desk'), {'tab': 'billing'}), 'Excel (this day)')
        self.as_user('asha')  # an assistant has no billing
        self.assertEqual(self.client.get(reverse('clinics:desk-bill-export')).status_code, 404)
        self.as_user('other-physio')
        self.assertEqual(self.client.get(reverse('clinics:desk-bill-export')).status_code, 404)


class AssistantRecordsTreatmentTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    register = FrontDeskRegisteredByAndBillingTests.register

    def prepare(self):
        clinic = self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        self.patient = Patient.objects.get(name='Walk In')
        self.client.post(reverse('clinics:desk-queue-add'), {'patient_id': self.patient.pk})
        self.as_user('asha')
        return clinic

    def save(self, **extra):
        import json
        data = {'patient_id': self.patient.pk, 'date': timezone.localdate().isoformat(), 'session_type': 'treatment', 'finish_queue': '1', 'notes': 'Tolerated well',
                'treatments': json.dumps([{'kind': 'exercise', 'name': 'TENS (pain relief)', 'dosage': '15 min'}, {'name': 'Hot pack', 'dosage': '10 min'}]),
                'exercises': json.dumps([{'kind': 'clinical', 'name': 'Bridging', 'dosage': '3 x 10'}]), **extra}
        return self.client.post(reverse('clinics:desk-session-create'), data)

    def test_the_assistant_records_the_treatment_given_and_the_exercises_supervised(self):
        from accounts.models import Visit
        self.prepare()
        page = self.client.get(reverse('clinics:desk'), {'tab': 'session', 'patient': self.patient.pk})
        self.assertContains(page, 'Treatment given')
        self.assertContains(page, 'Exercises supervised')
        self.assertContains(page, 'Record treatment')  # the tab name, and the shortcut on the queue row
        self.assertContains(self.client.get(reverse('clinics:desk'), {'tab': 'queue'}), f'tab=session&amp;patient={self.patient.pk}' if False else 'Record treatment')
        r = self.save()
        self.assertRedirects(r, reverse('clinics:desk') + '?tab=session', fetch_redirect_response=False)
        visit = Visit.objects.get()
        self.assertEqual((visit.patient, visit.therapist, visit.recorded_by_role, visit.session_type, visit.notes), (self.patient, 'Asha', 'Therapy assistant', 'treatment', 'Tolerated well'))
        # the page decides the kind from the list it was typed in, whatever was posted
        self.assertEqual([(t.kind, t.name, t.dosage) for t in visit.treatments.all()], [('clinical', 'TENS (pain relief)', '15 min'), ('clinical', 'Hot pack', '10 min'), ('exercise', 'Bridging', '3 x 10')])
        self.assertEqual(QueueEntry.objects.get().status, 'completed')  # finished in today's queue
        mine = self.client.get(reverse('clinics:desk'), {'tab': 'session'})
        self.assertContains(mine, 'Bridging')
        self.assertEqual(len(mine.context['my_sessions']), 1)
        # the physiotherapist sees it on the patient's record with the assistant's name and role
        self.as_user('owner')
        tab = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'visits'})
        self.assertContains(tab, 'Asha')
        self.assertContains(tab, 'Therapy assistant')
        self.assertContains(tab, 'Bridging')

    def test_something_must_be_entered_the_patient_must_be_the_clinics_and_the_date_sensible(self):
        from accounts.models import Visit
        self.prepare()
        self.save(treatments='[]', exercises='[]')
        self.assertEqual(Visit.objects.count(), 0)  # neither a treatment nor an exercise
        self.save(patient_id=999999)
        stranger_user, stranger = make_professional('far-physio')
        elsewhere = make_patient(stranger, 'Elsewhere')
        self.save(patient_id=elsewhere.pk)
        self.save(date=(timezone.localdate() + datetime.timedelta(days=2)).isoformat())
        self.save(date=(timezone.localdate() - datetime.timedelta(days=90)).isoformat())
        self.assertEqual(Visit.objects.count(), 0)
        self.save(treatments='[]')  # exercises alone are enough
        self.assertEqual(Visit.objects.get().treatments.count(), 1)
        self.save(finish_queue='', treatments='[]', exercises='not json')
        self.assertEqual(Visit.objects.count(), 1)

    def test_only_the_assistant_has_the_page_and_the_search_works(self):
        self.prepare()
        search = self.client.get(reverse('clinics:desk-treatment-search'), {'q': 'tens', 'kind': 'clinical'})
        self.assertIn('TENS (pain relief)', [r['name'] for r in search.json()['results']])
        self.assertTrue(all(r['kind'] == 'clinical' for r in self.client.get(reverse('clinics:desk-treatment-search'), {'q': 'e', 'kind': 'clinical'}).json()['results']))
        for who in ('ram-desk', 'mani'):  # receptionist and manager do not record treatment
            self.as_user(who)
            self.assertNotContains(self.client.get(reverse('clinics:desk')), 'tab=session')
            self.assertEqual(self.client.post(reverse('clinics:desk-session-create'), {'patient_id': self.patient.pk, 'exercises': '[{"name": "x"}]'}).status_code, 404)
            self.assertEqual(self.client.get(reverse('clinics:desk-treatment-search'), {'q': 'tens'}).status_code, 404)
        self.as_user('owner')
        self.assertEqual(self.client.post(reverse('clinics:desk-session-create'), {}).status_code, 404)

    def test_a_session_by_the_assistant_uses_a_package_session(self):
        from billing.models import PatientPackage
        self.prepare()
        package = PatientPackage.objects.create(patient=self.patient, professional=self.patient.professional, duration='10_day', total_sessions=5, total_amount=1000, start_date=timezone.localdate())
        self.save()
        package.refresh_from_db()
        self.assertEqual(package.sessions_used, 1)


class ClinicLoginSeesAssistantsTreatmentsTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    register = FrontDeskRegisteredByAndBillingTests.register

    def test_the_clinic_login_and_the_owner_see_who_the_assistant_treated(self):
        import json
        self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        patient = Patient.objects.get(name='Walk In')
        self.as_user('asha')
        self.client.post(reverse('clinics:desk-session-create'), {'patient_id': patient.pk, 'date': timezone.localdate().isoformat(), 'session_type': 'treatment',
                                                                  'treatments': json.dumps([{'name': 'Hot pack', 'dosage': '10 min'}]), 'exercises': json.dumps([{'name': 'Bridging'}])})
        for who in ('himal-clinic', 'owner'):
            self.as_user(who)
            page = self.client.get(reverse('accounts:treated'))
            self.assertEqual(page.context['summary'], {'sessions': 1, 'patients': 1, 'by_therapist': 0, 'by_assistant': 1}, who)
            self.assertContains(page, 'Asha')
            self.assertContains(page, 'Therapy assistant')
            self.assertContains(page, 'Bridging')
            self.assertEqual(self.client.get(reverse('accounts:dashboard')).context['stats']['treated_today'], 1, who)


class ClinicModulesTests(Base):
    """Staff switch parts of the workspace on or off for each clinic; the clinic's own login and front desk respect it."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk

    def test_a_new_clinic_has_every_module_and_everything_works_as_before(self):
        from .modules import KEYS
        clinic = self.setup_desk()
        self.assertEqual(clinic.modules, KEYS)
        self.as_user('himal-clinic')
        for url in ('accounts:appointments', 'billing:billing', 'accounts:plans', 'accounts:messages', 'accounts:reports'):
            self.assertEqual(self.client.get(reverse(url)).status_code, 200, url)

    def test_a_module_that_is_off_disappears_from_the_menu_and_its_pages_are_closed(self):
        clinic = self.setup_desk()
        clinic.modules = ['appointments', 'reports']
        clinic.save()
        self.as_user('himal-clinic')
        page = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(page, f'href="{reverse("accounts:appointments")}"')
        self.assertContains(page, f'href="{reverse("accounts:reports")}"')
        for gone in ('billing:billing', 'accounts:plans', 'exercises:library', 'accounts:messages'):
            self.assertNotContains(page, f'class="nav " href="{reverse(gone)}"', msg_prefix=gone)
        for url in ('billing:billing', 'accounts:plans', 'accounts:messages'):
            r = self.client.get(reverse(url))
            self.assertRedirects(r, reverse('clinics:detail', args=[clinic.pk]), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('accounts:appointments')).status_code, 200)
        self.assertEqual(self.client.post(reverse('billing:billing')).status_code, 403)  # forms and scripts get a plain refusal
        # the owner sees which parts the clinic has
        self.as_user('owner')
        overview = self.client.get(reverse('clinics:detail', args=[clinic.pk]))
        self.assertContains(overview, 'Not in your plan')
        self.assertEqual([(n, on) for n, _, on in overview.context['module_rows']][:3], [('Appointments', True), ('Billing & accounts', False), ('Assessments & SOAP notes', False)])

    def test_the_front_desk_loses_the_billing_tab_when_billing_is_off(self):
        clinic = self.setup_desk()
        self.as_user('ram-desk')
        self.assertContains(self.client.get(reverse('clinics:desk')), f'href="{reverse("billing:billing")}"')
        clinic.modules = ['appointments']
        clinic.save()
        self.assertNotContains(self.client.get(reverse('clinics:desk')), f'href="{reverse("billing:billing")}"')
        self.assertNotContains(self.client.get(reverse('clinics:desk')), 'tab=billing')
        self.assertEqual(self.client.post(reverse('clinics:desk-bill-create'), {}).status_code, 404)
        self.assertNotEqual(self.client.get(reverse('clinics:desk'), {'tab': 'billing'}).context['tab'], 'billing')

    def test_a_physiotherapists_own_workspace_is_never_restricted_and_staff_can_set_modules_in_the_admin(self):
        clinic = self.setup_desk()
        clinic.modules = []
        clinic.save()
        self.as_user('owner')
        self.assertEqual(self.client.get(reverse('billing:billing')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:appointments')).status_code, 200)
        from .admin import ClinicAdminForm
        form = ClinicAdminForm(instance=clinic)
        self.assertIn('billing', [key for key, _ in form.fields['modules'].choices])


class SchedulesTests(Base):
    """Each department and each therapist has their own page onto the clinic's appointments."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk

    def prepare(self):
        from accounts.models import Appointment, Department
        clinic = self.setup_desk()
        self.workspace = clinic.workspace
        self.pt = Department.objects.create(professional=self.workspace, name='Physical Therapy')
        self.ot = Department.objects.create(professional=self.workspace, name='Occupational Therapy')
        self.physio_user, self.physio = make_professional('therapist', first_name='Tara', last_name='Gurung')
        self.member = ClinicMember.objects.create(clinic=clinic, physio=self.physio, role='physio', status='active')
        self.asha = ClinicMember.objects.get(name='Asha')
        self.a = make_patient(self.owner, 'Patient A')
        self.c = make_patient(self.owner, 'Patient C')
        self.when = timezone.make_aware(datetime.datetime.combine(timezone.localdate(), datetime.time(13, 30)))
        end = self.when + datetime.timedelta(minutes=30)
        self.appt_a = Appointment.objects.create(professional=self.workspace, patient=self.a, start=self.when, end=end, department=self.pt, practitioner=self.member)
        self.appt_c = Appointment.objects.create(professional=self.workspace, patient=self.c, start=self.when, end=end, department=self.ot, practitioner=self.asha)
        return clinic

    def test_a_department_login_sees_only_its_own_departments_appointments_and_may_use_a_simple_password(self):
        clinic = self.prepare()
        self.as_user('owner')
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'role': 'department', 'department': self.ot.pk, 'name': ''})
        member = ClinicMember.objects.get(role='department')
        self.assertEqual((member.name, member.department), ('Occupational Therapy', self.ot))
        url = reverse('clinics:staff-login', args=[clinic.pk, member.pk])
        self.client.post(url, {'username': 'ot-room', 'password1': 'abc', 'password2': 'abc'})  # too short
        member.refresh_from_db()
        self.assertIsNone(member.user)
        self.client.post(url, {'username': 'ot-room', 'password1': 'ot-room', 'password2': 'ot-room'})  # same as the username
        member.refresh_from_db()
        self.assertIsNone(member.user)
        self.client.post(url, {'username': 'ot-room', 'password1': '1234', 'password2': '1234'})  # simple is allowed
        member.refresh_from_db()
        self.assertIsNotNone(member.user)
        self.client.post(url, {'username': 'ot-room', 'password1': '5678', 'password2': '5678'})  # changing only the password keeps the username
        self.assertTrue(self.client.login(username='ot-room', password='5678'))
        page = self.client.get(reverse('clinics:desk'))
        self.assertEqual(page.context['tab'], 'schedule')
        self.assertEqual([t[0] for t in page.context['tabs']], ['schedule'])
        self.assertEqual([a.patient.name for a in page.context['appointments']], ['Patient C'])
        self.assertNotContains(page, 'Patient A')
        self.assertNotContains(page, '9841')  # no phone numbers
        self.assertEqual(self.client.get(reverse('clinics:desk'), {'tab': 'patients'}).context['tab'], 'schedule')  # nothing else is open to it
        for url in ('billing:billing', 'accounts:patients', 'accounts:appointments'):  # not a workspace login: the other pages stay closed
            self.assertIn(self.client.get(reverse(url)).status_code, (302, 403, 404), url)

    def test_other_staff_see_the_whole_clinic_and_can_narrow_to_a_department(self):
        self.prepare()
        self.as_user('ram-desk')
        page = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertEqual(sorted(a.patient.name for a in page.context['appointments']), ['Patient A', 'Patient C'])
        self.assertContains(page, 'Occupational Therapy')
        narrowed = self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'dept': self.pt.pk})
        self.assertEqual([a.patient.name for a in narrowed.context['appointments']], ['Patient A'])
        tomorrow = self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'date': (timezone.localdate() + datetime.timedelta(days=1)).isoformat()})
        self.assertEqual(tomorrow.context['appointments'], [])

    def test_a_therapy_assistant_starts_with_the_appointments_booked_with_them(self):
        self.prepare()
        self.as_user('asha')
        mine = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertEqual([a.patient.name for a in mine.context['appointments']], ['Patient C'])
        everyone = self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'all': 1})
        self.assertEqual(len(everyone.context['appointments']), 2)

    def test_a_therapist_has_their_own_page_across_clinics(self):
        self.prepare()
        self.client.force_login(self.physio_user)
        page = self.client.get(reverse('clinics:my-schedule'))
        self.assertEqual([a.patient.name for a in page.context['appointments']], ['Patient A'])
        self.assertContains(page, 'My schedule')
        self.assertContains(page, 'Physical Therapy')
        self.assertNotContains(page, 'Patient C')
        stranger_user, _ = make_professional('nobody')
        self.client.force_login(stranger_user)
        empty = self.client.get(reverse('clinics:my-schedule'))
        self.assertContains(empty, 'not on a clinic team yet')
        self.assertNotContains(self.client.get(reverse('accounts:patients')), 'My schedule')

    def test_booking_with_a_therapist_on_the_clinics_calendar(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        self.as_user('himal-clinic')
        patient = make_patient(self.workspace, 'Walk In')
        day = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()
        base = {'patient': patient.pk, 'date': day, 'start_time': '10:00', 'duration': 30, 'session_type': 'treatment', 'notes': '', 'department': self.pt.pk}
        self.client.post(reverse('accounts:appointment-create'), {**base, 'practitioner': self.member.pk})
        appt = Appointment.objects.get(patient=patient)
        self.assertEqual((appt.department, appt.practitioner), (self.pt, self.member))
        page = self.client.get(reverse('accounts:appointments'), {'date': day, 'days': 1})
        self.assertContains(page, 'Tara Gurung')
        outsider = ClinicMember.objects.create(clinic=Clinic.objects.create(owner=self.owner, name='Other', phone='01555'), physio=self.physio, role='physio')
        self.client.post(reverse('accounts:appointment-create'), {**base, 'start_time': '11:00', 'practitioner': outsider.pk})  # not this clinic's team
        self.assertEqual(Appointment.objects.filter(patient=patient).count(), 1)
        edit = {'date': day, 'start_time': '10:30', 'end_time': '11:00', 'session_type': 'treatment', 'notes': '', 'department': self.pt.pk}
        self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {**edit, 'practitioner': self.asha.pk})
        appt.refresh_from_db()
        self.assertEqual(appt.practitioner, self.asha)
        self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {**edit, 'practitioner': outsider.pk})
        appt.refresh_from_db()
        self.assertIsNone(appt.practitioner)  # never attached to someone outside the clinic


class VisitingClinicianTests(Base):
    """A doctor or therapist who is not on Sajhya: added by name, bookable, with a login of their own."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def add_doctor(self, clinic):
        self.as_user('owner')
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'name': 'Dr Sailendra Maharjan', 'role': 'clinician', 'specialty': 'Ortho'})
        doctor = ClinicMember.objects.get(role='clinician')
        self.client.post(reverse('clinics:staff-login', args=[clinic.pk, doctor.pk]), {'username': 'dr-sailendra', 'password1': PASSWORD, 'password2': PASSWORD})
        doctor.refresh_from_db()
        return doctor

    def test_the_owner_adds_a_visiting_doctor_with_a_login_and_books_patients_with_them(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        doctor = self.add_doctor(clinic)
        self.assertEqual((doctor.specialty, doctor.label, doctor.physio), ('Ortho', 'Dr Sailendra Maharjan (Ortho)', None))
        self.assertIsNotNone(doctor.user)
        self.as_user('himal-clinic')
        patient = make_patient(self.workspace, 'Walk In')
        page = self.client.get(reverse('accounts:appointments'))
        self.assertContains(page, 'Dr Sailendra Maharjan (Ortho)')  # in "Book with"
        day = timezone.localdate()
        self.client.post(reverse('accounts:appointment-create'), {'patient': patient.pk, 'date': day.isoformat(), 'start_time': '15:00', 'duration': 30, 'session_type': 'treatment',
                                                                  'department': self.pt.pk, 'practitioner': doctor.pk, 'notes': ''})
        self.assertEqual(Appointment.objects.get(patient=patient).practitioner, doctor)

    def test_the_doctor_signs_in_sees_their_own_appointments_and_records_treatment_under_their_name(self):
        import json
        from accounts.models import Appointment, Visit
        clinic = self.prepare()
        doctor = self.add_doctor(clinic)
        patient = make_patient(self.workspace, 'Walk In')
        patient.clinic = clinic
        patient.save()
        start = self.when + datetime.timedelta(hours=2)
        Appointment.objects.create(professional=self.workspace, patient=patient, start=start, end=start + datetime.timedelta(minutes=30), department=self.pt, practitioner=doctor)
        self.client.logout()
        self.assertTrue(self.client.login(username='dr-sailendra', password=PASSWORD))
        mine = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertEqual([a.patient.name for a in mine.context['appointments']], ['Walk In'])
        self.assertEqual(len(self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'all': 1}).context['appointments']), 3)
        tabs = [t[0] for t in mine.context['tabs']]
        self.assertIn('session', tabs)
        self.assertNotIn('billing', tabs)
        self.assertNotContains(mine, '9841')
        self.client.post(reverse('clinics:desk-session-create'), {'patient_id': patient.pk, 'date': timezone.localdate().isoformat(), 'session_type': 'treatment',
                                                                  'treatments': json.dumps([{'name': 'Joint mobilization (Grade I-II)'}]), 'exercises': '[]'})
        visit = Visit.objects.get()
        self.assertEqual((visit.therapist, visit.recorded_by_role), ('Dr Sailendra Maharjan', 'Doctor / therapist'))
        self.as_user('himal-clinic')
        treated = self.client.get(reverse('accounts:treated'))
        self.assertContains(treated, 'Doctor / therapist')
        self.assertContains(treated, 'Dr Sailendra Maharjan')

    def test_a_specialty_is_only_kept_for_a_visiting_doctor(self):
        clinic = self.prepare()
        self.as_user('owner')
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'name': 'Sita', 'role': 'receptionist', 'specialty': 'Ortho'})
        self.assertEqual(ClinicMember.objects.get(name='Sita').specialty, '')


class SeedQaClinicTests(TestCase):
    """python manage.py seed_qa_clinic: a mock clinic for QA, and a clean way to remove it."""
    def run_command(self, *args):
        import io
        from django.core.management import call_command
        out = io.StringIO()
        call_command('seed_qa_clinic', *args, stdout=out)
        text = out.getvalue()
        passwords = {}
        for line in text.splitlines():
            parts = line.split()
            if parts and parts[0].startswith('qa-bshc-') and len(parts) > 1 and not parts[1].startswith('('):
                passwords[parts[0]] = parts[1]
        return text, passwords

    def test_it_builds_the_clinic_with_four_therapists_who_each_see_their_own_bookings(self):
        from accounts.models import Appointment, Department
        text, passwords = self.run_command()
        clinic = Clinic.objects.get(name='Bhaktapur Speech and Hearing Center')
        self.assertTrue(clinic.is_usable)
        therapists = {f'qa-bshc-{prefix}{suffix}' for prefix in ('ot', 'speech', 'physio') for suffix in ('', '2', '3', '4')} | {'qa-bshc-behaviour'}
        self.assertEqual(set(passwords), {'qa-bshc-owner', 'qa-bshc-clinic', 'qa-bshc-reception'} | therapists)
        self.assertEqual(clinic.members.filter(role='physio').count(), 13)
        self.assertEqual(sorted(clinic.calendar_owner.departments.values_list('name', flat=True)),
                         ['Behaviour Therapy', 'Occupational Therapy', 'Physiotherapy', 'Speech Therapy'])
        professions = {m.physio.account.profession.name for m in clinic.members.filter(role='physio')}
        self.assertEqual(professions, {'occupational therapist', 'speech therapist', 'physiotherapist', 'behaviour therapist'})
        # one time slot shared by the four departments
        shared = Appointment.objects.filter(professional=clinic.workspace, start__hour=13, start__minute=30, start__date=timezone.localdate())
        self.assertEqual(sorted(a.department.name for a in shared), ['Behaviour Therapy'] + ['Occupational Therapy'] * 2 + ['Physiotherapy'] * 2 + ['Speech Therapy'] * 2)
        logins = [(f'{p}{n}', d) for p, d in (('ot', 'Occupational Therapy'), ('speech', 'Speech Therapy'), ('physio', 'Physiotherapy')) for n in ('', '2', '3', '4')] + [('behaviour', 'Behaviour Therapy')]
        for suffix, department in logins:
            self.assertTrue(self.client.login(username=f'qa-bshc-{suffix}', password=passwords[f'qa-bshc-{suffix}']), suffix)
            page = self.client.get(reverse('clinics:my-schedule'))
            rows = page.context['appointments']
            self.assertTrue(rows, suffix)
            self.assertEqual({a.department.name for a in rows}, {department})  # only their own bookings
            self.assertContains(page, 'Bhaktapur Speech and Hearing Center')
            self.client.logout()
        from billing.models import ServiceItem
        self.assertEqual({i.department.name for i in ServiceItem.objects.filter(professional=clinic.workspace).select_related('department')},
                         {'Occupational Therapy', 'Speech Therapy', 'Physiotherapy', 'Behaviour Therapy'})  # each department bills its own services
        for member in clinic.members.filter(role='physio'):
            self.assertEqual(member.departments.count(), 1)
        self.assertTrue(self.client.login(username='qa-bshc-clinic', password=passwords['qa-bshc-clinic']))
        calendar = self.client.get(reverse('accounts:appointments'))
        self.assertEqual(calendar.status_code, 200)
        self.assertEqual(len(calendar.context['departments']), 4)
        self.client.logout()
        self.assertTrue(self.client.login(username='qa-bshc-reception', password=passwords['qa-bshc-reception']))
        desk = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertGreaterEqual(len(desk.context['appointments']), 4)

    def test_running_it_again_changes_nothing_but_the_dates_and_keeps_passwords(self):
        from accounts.models import Appointment
        _, first = self.run_command()
        counts = (User.objects.filter(username__startswith='qa-bshc-').count(), Patient.objects.count(), Clinic.objects.count(), Appointment.objects.count())
        text, second = self.run_command()
        self.assertEqual(second, {})  # no password is printed again
        self.assertIn('unchanged', text)
        self.assertEqual((User.objects.filter(username__startswith='qa-bshc-').count(), Patient.objects.count(), Clinic.objects.count(), Appointment.objects.count()), counts)
        self.assertTrue(self.client.login(username='qa-bshc-ot', password=first['qa-bshc-ot']))
        self.client.logout()
        _, third = self.run_command('--reset-passwords')
        self.assertNotEqual(third['qa-bshc-ot'], first['qa-bshc-ot'])
        self.assertFalse(self.client.login(username='qa-bshc-ot', password=first['qa-bshc-ot']))
        self.assertTrue(self.client.login(username='qa-bshc-ot', password=third['qa-bshc-ot']))

    def test_remove_deletes_only_the_qa_clinic(self):
        from accounts.models import Appointment
        real_user, real = make_professional('real-physio')
        make_patient(real, 'Real Patient')
        self.run_command()
        self.assertGreater(Appointment.objects.count(), 0)
        text, _ = self.run_command('--remove')
        self.assertIn('Removed', text)
        self.assertFalse(User.objects.filter(username__startswith='qa-bshc-').exists())
        self.assertFalse(Clinic.objects.filter(name='Bhaktapur Speech and Hearing Center').exists())
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(list(Patient.objects.values_list('name', flat=True)), ['Real Patient'])
        self.assertTrue(User.objects.filter(username='real-physio').exists())
        self.run_command()  # and it can be built again
        self.assertTrue(Clinic.objects.filter(name='Bhaktapur Speech and Hearing Center').exists())


class ReceptionRunsTheAppointmentBookTests(Base):
    """Reception (and the manager) book, change and cancel the clinic's appointments from the front desk."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def booking(self, **extra):
        return {'patient': self.c.pk, 'date': timezone.localdate().isoformat(), 'start_time': '09:30', 'duration': 30, 'session_type': 'treatment',
                'department': self.ot.pk, 'practitioner': self.member.pk, 'notes': 'First visit', **extra}

    def test_reception_books_a_clinic_patient_with_a_department_and_a_therapist(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        for patient in (self.a, self.c):  # the QA patients belong to the clinic
            patient.clinic = clinic
            patient.professional = self.workspace
            patient.save()
        self.as_user('ram-desk')
        page = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertContains(page, 'Book an appointment')
        r = self.client.post(reverse('clinics:desk-appt-create'), self.booking())
        appt = Appointment.objects.get(patient=self.c, notes='First visit')
        self.assertEqual((appt.professional, appt.department, appt.practitioner), (self.workspace, self.ot, self.member))
        self.assertRedirects(r, f"{reverse('clinics:desk')}?tab=schedule&date={timezone.localdate().isoformat()}&booked={appt.pk}&kind=booked", fetch_redirect_response=False)
        after = self.client.get(r['Location'])
        self.assertContains(after, 'Booked: Patient C')  # the message to the patient is offered straight away
        self.assertContains(after, 'WhatsApp')
        # it appears on the therapist's page and on the clinic's calendar
        self.client.force_login(self.physio_user)
        self.assertIn(appt, self.client.get(reverse('clinics:my-schedule')).context['appointments'])
        self.as_user('himal-clinic')
        self.assertContains(self.client.get(reverse('accounts:appointments')), 'Patient C')

    def test_reception_can_change_and_cancel_it(self):
        clinic = self.prepare()
        self.as_user('mani')  # the manager can too
        self.a.clinic = clinic
        self.a.save()
        edit = reverse('clinics:desk-appt-edit', args=[self.appt_a.pk])
        day = timezone.localdate().isoformat()
        self.client.post(edit, {'date': day, 'start_time': '16:00', 'end_time': '16:30', 'department': self.ot.pk, 'practitioner': self.asha.pk, 'session_type': 'treatment', 'notes': ''})
        self.appt_a.refresh_from_db()
        self.assertEqual((timezone.localtime(self.appt_a.start).strftime('%H:%M'), self.appt_a.department, self.appt_a.practitioner), ('16:00', self.ot, self.asha))
        self.client.post(edit, {'date': day, 'start_time': '17:00', 'end_time': '16:30'})  # ends before it starts: refused
        self.appt_a.refresh_from_db()
        self.assertEqual(timezone.localtime(self.appt_a.start).strftime('%H:%M'), '16:00')
        r = self.client.post(reverse('clinics:desk-appt-cancel', args=[self.appt_a.pk]))
        self.appt_a.refresh_from_db()
        self.assertEqual(self.appt_a.status, 'cancelled')
        self.assertIn('kind=cancelled', r['Location'])
        self.assertEqual(self.client.post(reverse('clinics:desk-appt-cancel', args=[self.appt_a.pk])).status_code, 404)  # no longer scheduled

    def test_only_the_patients_of_this_clinic_and_only_the_right_roles(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        stranger_user, stranger = make_professional('far-physio')
        elsewhere = make_patient(stranger, 'Elsewhere')
        self.as_user('ram-desk')
        before = Appointment.objects.count()
        self.client.post(reverse('clinics:desk-appt-create'), self.booking(patient=elsewhere.pk))
        self.client.post(reverse('clinics:desk-appt-create'), self.booking(patient=self.c.pk))  # not registered under the clinic
        self.assertEqual(Appointment.objects.count(), before)
        for who in ('asha', 'owner'):  # an assistant and the owner's personal sign-in cannot use the desk's booking
            self.as_user(who)
            self.assertEqual(self.client.post(reverse('clinics:desk-appt-create'), self.booking()).status_code, 404, who)
            self.assertEqual(self.client.post(reverse('clinics:desk-appt-cancel', args=[self.appt_a.pk])).status_code, 404, who)
        clinic.modules = ['billing']
        clinic.save()
        self.as_user('ram-desk')
        self.assertEqual(self.client.post(reverse('clinics:desk-appt-create'), self.booking()).status_code, 404)  # Appointments is off in the plan


class FrontDeskWorkspaceTests(Base):
    """The front desk is a workspace: a sidebar, a dashboard as the home page and a calendar for the appointment book."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def test_reception_lands_on_a_dashboard_with_todays_numbers(self):
        clinic = self.prepare()
        self.a.clinic = clinic
        self.a.save()
        self.as_user('ram-desk')
        page = self.client.get(reverse('clinics:desk'))
        self.assertEqual(page.context['tab'], 'overview')
        self.assertEqual([label for _, label in page.context['tabs']][:2], ['Dashboard', 'Schedule'])
        self.assertEqual(page.context['appt_total'], 2)  # the two seeded appointments are today
        self.assertEqual(page.context['appt_waiting'], page.context['appt_total'] - page.context['appt_attended'])
        self.assertIsNotNone(page.context['billed_today'])  # reception bills, so the money cards show
        self.assertContains(page, 'Appointments today')
        self.assertContains(page, 'Book an appointment')
        self.assertContains(page, 'Coming up today')
        self.as_user('asha')  # an assistant has no dashboard and no money
        assistant = self.client.get(reverse('clinics:desk'))
        self.assertNotEqual(assistant.context['tab'], 'overview')
        self.assertNotContains(assistant, 'Billed today')

    def test_the_calendar_shows_the_clinics_appointments_in_columns_and_departments_side_by_side(self):
        self.prepare()
        self.as_user('ram-desk')
        page = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertEqual(page.context['view'], 'calendar')  # reception opens on the calendar
        self.assertEqual(len(page.context['columns']), 3)
        events = page.context['columns'][0]['events']
        self.assertEqual(sorted((e['title'], e['department']) for e in events), [('Patient A', 'Physical Therapy'), ('Patient C', 'Occupational Therapy')])
        self.assertEqual({e['lane'] for e in events}, {0, 1})
        self.assertContains(page, 'Click an empty time to book')
        self.assertContains(page, 'data-open="bookModal"')
        self.assertEqual(len(self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'days': 7}).context['columns']), 7)
        filtered = self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'dept': self.pt.pk})
        self.assertEqual([e['title'] for e in filtered.context['columns'][0]['events']], ['Patient A'])
        listing = self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'view': 'list'})
        self.assertEqual(listing.context['view'], 'list')
        self.assertEqual(len(listing.context['appointments']), 2)

    def test_a_department_login_gets_a_read_only_view_without_phone_numbers_or_message_links(self):
        clinic = self.prepare()
        self.as_user('owner')
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'role': 'department', 'department': self.ot.pk, 'name': ''})
        member = ClinicMember.objects.get(role='department')
        self.client.post(reverse('clinics:staff-login', args=[clinic.pk, member.pk]), {'username': 'ot-room', 'password1': '1234', 'password2': '1234'})
        self.assertTrue(self.client.login(username='ot-room', password='1234'))
        page = self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'view': 'calendar'})
        self.assertEqual([e['title'] for e in page.context['columns'][0]['events']], ['Patient C'])
        self.assertNotContains(page, 'wa.me')
        self.assertNotContains(page, 'data-open="bookModal"')
        self.assertNotContains(page, 'Patient A')
        self.assertEqual(page.context['columns'][0]['events'][0]['links'], {})


class StaffByDepartmentTests(Base):
    """Team members belong to departments, so booking into OT only offers the people who work in OT."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def test_the_owner_sets_which_departments_a_person_works_in(self):
        clinic = self.prepare()
        self.as_user('owner')
        url = reverse('clinics:member-departments', args=[clinic.pk, self.member.pk])
        self.client.post(url, {'departments': [self.pt.pk]})
        self.assertEqual(list(self.member.departments.all()), [self.pt])
        team = self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'team'})
        self.assertContains(team, 'Physical Therapy')
        self.assertContains(team, 'data-member-depts')
        self.client.post(url, {'departments': []})  # none = can be booked anywhere
        self.assertEqual(self.member.departments.count(), 0)
        other, _ = make_professional('someone-else')
        self.client.post(url, {'departments': [999999]})  # not a department of this clinic: ignored
        self.assertEqual(self.member.departments.count(), 0)
        self.as_user('ram-desk')  # only the owner
        self.assertEqual(self.client.post(url, {'departments': [self.pt.pk]}).status_code, 404)
        # adding staff can set them straight away
        self.as_user('owner')
        self.client.post(reverse('clinics:staff-add', args=[clinic.pk]), {'name': 'Dr Sailendra', 'role': 'clinician', 'specialty': 'Ortho', 'departments': [self.pt.pk, self.ot.pk]})
        self.assertEqual(set(ClinicMember.objects.get(name='Dr Sailendra').departments.all()), {self.pt, self.ot})

    def test_booking_only_accepts_people_from_the_chosen_department(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        self.member.departments.set([self.pt])
        self.asha.departments.set([self.ot])
        self.as_user('himal-clinic')
        patient = make_patient(self.workspace, 'Walk In')
        patient.clinic = clinic
        patient.save()
        day = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()
        base = {'patient': patient.pk, 'date': day, 'start_time': '10:00', 'duration': 30, 'session_type': 'treatment', 'notes': ''}
        page = self.client.get(reverse('accounts:appointments'))
        self.assertContains(page, f'data-depts="{self.pt.pk}"')  # the booking form can narrow the list
        self.client.post(reverse('accounts:appointment-create'), {**base, 'department': self.ot.pk, 'practitioner': self.member.pk})  # PT person into OT
        self.assertFalse(Appointment.objects.filter(patient=patient).exists())
        self.client.post(reverse('accounts:appointment-create'), {**base, 'department': self.ot.pk, 'practitioner': self.asha.pk})
        appt = Appointment.objects.get(patient=patient)
        self.assertEqual((appt.department, appt.practitioner), (self.ot, self.asha))
        # moving it to PT with the OT person drops the person and says so
        edit = {'date': day, 'start_time': '10:30', 'end_time': '11:00', 'session_type': 'treatment', 'notes': '', 'department': self.pt.pk, 'practitioner': self.asha.pk}
        r = self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), edit, follow=True)
        appt.refresh_from_db()
        self.assertEqual((appt.department, appt.practitioner), (self.pt, None))
        self.assertContains(r, 'does not work in that department')
        # a person with no department set can go anywhere
        self.member.departments.clear()
        self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {**edit, 'department': self.ot.pk, 'practitioner': self.member.pk})
        appt.refresh_from_db()
        self.assertEqual(appt.practitioner, self.member)

    def test_the_front_desk_books_the_same_way(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        self.c.clinic = clinic
        self.c.professional = self.workspace
        self.c.save()
        self.member.departments.set([self.pt])
        self.as_user('ram-desk')
        page = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertContains(page, f'data-depts="{self.pt.pk}"')
        booking = {'patient': self.c.pk, 'date': timezone.localdate().isoformat(), 'start_time': '09:30', 'duration': 30, 'session_type': 'treatment', 'notes': 'desk'}
        self.client.post(reverse('clinics:desk-appt-create'), {**booking, 'department': self.ot.pk, 'practitioner': self.member.pk})
        self.assertFalse(Appointment.objects.filter(notes='desk').exists())
        self.client.post(reverse('clinics:desk-appt-create'), {**booking, 'department': self.pt.pk, 'practitioner': self.member.pk})
        self.assertTrue(Appointment.objects.filter(notes='desk', practitioner=self.member).exists())


class ReceptionFullBillingTests(Base):
    """Reception and the manager use the same billing pages as the clinic itself: bills, payments, advances, packages, the sheet, the invoice picture."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    register = FrontDeskRegisteredByAndBillingTests.register

    def prepare(self):
        clinic = self.setup_desk()
        self.as_user('ram-desk')
        self.register()
        self.patient = Patient.objects.get(name='Walk In')
        return clinic

    def bill(self, **extra):
        data = {'entry_date': timezone.localdate().isoformat(), 'patient': self.patient.pk, 'patient_name': 'Walk In', 'service': 'Speech Therapy Session', 'rate': '600',
                'payment_mode': 'cash', 'payment_status': 'paid', **extra}
        return self.client.post(reverse('billing:entry-create'), data)

    def test_reception_opens_the_full_billing_book_in_the_front_desk_layout(self):
        self.prepare()
        page = self.client.get(reverse('billing:billing'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Front desk')
        self.assertContains(page, f'href="{reverse("clinics:desk")}?tab=queue"')  # the front-desk menu
        self.assertNotContains(page, reverse('accounts:patients'))  # not the clinical one
        self.assertNotContains(page, reverse('accounts:reports'))
        self.assertEqual(page.context['display_name'], 'Ram')
        for url in ('billing:packages', 'billing:advances', 'billing:sheet'):
            self.assertEqual(self.client.get(reverse(url)).status_code, 200, url)
        self.assertEqual(self.client.get(reverse('billing:export-xlsx')).status_code, 200)
        # the desk's own menu goes there too
        self.assertContains(self.client.get(reverse('clinics:desk')), f'href="{reverse("billing:billing")}"')

    def test_a_bill_is_stamped_with_who_made_it_and_can_be_paid_corrected_cancelled_and_restored(self):
        clinic = self.prepare()
        self.bill(payment_status='due')
        entry = BillingEntry.objects.get()
        self.assertEqual((entry.created_by_name, entry.created_by_role, entry.professional), ('Ram', 'Receptionist', clinic.workspace))
        self.assertEqual((entry.rate, entry.amount_paid), (600, 0))
        self.client.post(reverse('billing:entry-payment', args=[entry.pk]), {'amount': '250', 'payment_mode': 'cash', 'paid_on': timezone.localdate().isoformat()})
        entry.refresh_from_db()
        self.assertEqual(entry.amount_paid, 250)
        self.client.post(reverse('billing:entry-correct', args=[entry.pk]), {'entry_date': timezone.localdate().isoformat(), 'service': 'Speech Assessment', 'rate': '650',
                                                                            'payment_mode': 'cash', 'payment_status': 'partial', 'amount_received': '250', 'notes': ''})
        entry.refresh_from_db()
        self.assertEqual((entry.service, entry.rate), ('Speech Assessment', 650))
        self.client.post(reverse('billing:entry-cancel', args=[entry.pk]))
        entry.refresh_from_db()
        self.assertTrue(entry.is_cancelled)
        self.client.post(reverse('billing:entry-restore', args=[entry.pk]))
        entry.refresh_from_db()
        self.assertFalse(entry.is_cancelled)
        # the clinic itself sees the same bill and who made it
        self.as_user('himal-clinic')
        self.assertContains(self.client.get(reverse('billing:billing')), 'Walk In')

    def test_the_invoice_can_be_shown_sent_as_a_picture_and_as_a_pdf(self):
        self.prepare()
        self.bill()
        entry = BillingEntry.objects.get()
        page = self.client.get(reverse('billing:invoice', args=[entry.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, entry.invoice_number)
        png = self.client.get(reverse('billing:invoice-png', args=[entry.pk]))
        self.assertEqual((png.status_code, png['Content-Type']), (200, 'image/png'))
        pdf = self.client.get(reverse('billing:invoice-pdf', args=[entry.pk]))
        self.assertEqual((pdf.status_code, pdf['Content-Type']), (200, 'application/pdf'))

    def test_a_patients_bill_advances_and_packages_work_from_the_billing_pages(self):
        self.prepare()
        r = self.client.post(reverse('billing:patient-bill', args=[self.patient.pk]), {'entry_date': timezone.localdate().isoformat(), 'service': 'Hearing Test (Audiometry)',
                                                                                       'rate': '500', 'payment_mode': 'cash', 'payment_status': 'paid'})
        self.assertRedirects(r, f"{reverse('billing:billing')}?patient={self.patient.pk}", fetch_redirect_response=False)  # staff cannot open the patient record
        self.assertEqual(BillingEntry.objects.get().service, 'Hearing Test (Audiometry)')
        r = self.client.post(reverse('billing:advance-add', args=[self.patient.pk]), {'amount': '1000', 'payment_mode': 'cash'})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('/accounts/patients/', r['Location'])
        search = self.client.get(reverse('billing:billing'), {'patient': self.patient.pk})
        self.assertContains(search, 'Walk In')
        self.assertNotContains(search, '/accounts/patients/')

    def test_who_may_delete_and_who_may_edit_prices(self):
        clinic = self.prepare()
        self.bill()
        entry = BillingEntry.objects.get()
        self.assertEqual(self.client.post(reverse('billing:entry-delete', args=[entry.pk])).status_code, 404)  # reception cannot delete for good
        self.assertTrue(BillingEntry.objects.filter(pk=entry.pk).exists())
        self.assertEqual(self.client.get(reverse('billing:services')).status_code, 404)
        self.assertNotContains(self.client.get(reverse('billing:billing')), reverse('billing:services'))
        self.as_user('mani')
        manager = self.client.get(reverse('billing:services'))
        self.assertEqual(manager.status_code, 200)
        self.client.post(reverse('billing:service-save', args=[0]), {'name': 'Hearing screening', 'price': '350', 'kind': 'main'})
        from billing.models import ServiceItem
        self.assertTrue(ServiceItem.objects.filter(professional=clinic.workspace, name='Hearing screening').exists())
        self.client.post(reverse('billing:entry-delete', args=[entry.pk]))
        self.assertFalse(BillingEntry.objects.filter(pk=entry.pk).exists())

    def test_only_billing_roles_only_the_clinics_own_patients_and_only_while_the_plan_is_active(self):
        clinic = self.prepare()
        self.bill()
        entry = BillingEntry.objects.get()
        stranger_user, stranger = make_professional('far-physio')
        elsewhere = make_patient(stranger, 'Elsewhere')
        self.assertEqual(self.client.post(reverse('billing:patient-bill', args=[elsewhere.pk]), {'entry_date': timezone.localdate().isoformat(), 'service': 'x', 'rate': '1', 'payment_mode': 'cash',
                                                                                                  'payment_status': 'paid'}).status_code, 404)
        self.bill(patient=elsewhere.pk, patient_name='Elsewhere')
        self.assertEqual(BillingEntry.objects.count(), 1)  # a patient of another practice is refused
        self.as_user('asha')
        for url in (reverse('billing:billing'), reverse('billing:invoice', args=[entry.pk]), reverse('billing:invoice-png', args=[entry.pk])):
            self.assertEqual(self.client.get(url).status_code, 404, url)  # an assistant does not bill
        self.as_user('ram-desk')
        ClinicSubscription.objects.filter(professional=self.owner).update(status='cancelled')
        self.assertEqual(self.client.get(reverse('billing:billing')).status_code, 200)  # can still look
        self.assertEqual(self.bill().status_code, 403)  # but nothing changes while the plan is off
        ClinicSubscription.objects.filter(professional=self.owner).update(status='active')
        clinic.modules = ['appointments']
        clinic.save()
        self.assertEqual(self.client.get(reverse('billing:billing')).status_code, 404)  # Billing is off in the plan


class TeamMembersSeeOnlyTheirAssignedPatientsTests(JoinedClinic):
    """A therapist on a clinic's team sees only the clinic patients assigned to them, and cannot add patients to the clinic."""
    def setUp(self):
        super().setUp()
        self.mine = self.add_patient(name='Assigned Patient')
        self.other = self.add_patient(name='Not Assigned Patient')
        self.assign(self.mine)
        self.member = ClinicMember.objects.get(clinic=self.clinic, physio=self.physio)

    def test_only_assigned_patients_can_be_listed_searched_or_opened(self):
        self.as_user('physio')
        tab = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'patients'})
        self.assertEqual([p.name for p in tab.context['patients']], ['Assigned Patient'])
        self.assertEqual(tab.context['patient_total'], 1)
        self.assertContains(tab, 'assigned to you')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.other.pk])).status_code, 404)
        found = self.client.get(reverse('clinics:patient-search', args=[self.clinic.pk]), {'q': 'Patient'}).json()['results']
        self.assertEqual([r['name'] for r in found], ['Assigned Patient'])
        self.assertEqual(self.client.get(reverse('assessments:choose', args=[self.other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('billing:billing'), {'patient': self.other.pk}).status_code, 200)  # no bill of theirs appears, and nothing leaks
        self.assertNotContains(self.client.get(reverse('accounts:patients')), 'Not Assigned Patient')

    def test_the_owner_still_sees_every_patient(self):
        self.as_user('owner')
        tab = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'patients'})
        self.assertEqual(len(tab.context['patients']), 2)
        self.assertContains(tab, 'Assign')
        self.assertContains(tab, 'Add patient to')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.other.pk])).status_code, 200)

    def test_the_queue_shows_and_accepts_only_assigned_patients(self):
        add = reverse('clinics:queue-add', args=[self.clinic.pk])
        self.client.post(add, {'patient_id': self.mine.pk})
        self.client.post(add, {'patient_id': self.other.pk})
        self.assertEqual(QueueEntry.objects.count(), 2)  # the owner queued both
        self.as_user('physio')
        queue = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'queue'})
        self.assertEqual([e.patient.name for e in queue.context['entries']], ['Assigned Patient'])
        hidden = QueueEntry.objects.get(patient=self.other)
        self.assertEqual(self.client.post(reverse('clinics:queue-action', args=[self.clinic.pk, hidden.pk]), {'action': 'call'}).status_code, 404)
        self.client.post(add, {'patient_id': self.other.pk})  # cannot queue a patient that is not theirs
        self.assertEqual(QueueEntry.objects.filter(added_by=self.physio).count(), 0)

    def test_a_team_member_cannot_add_patients_to_the_clinic(self):
        self.as_user('physio')
        tab = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'patients'})
        self.assertNotContains(tab, 'Add patient to')
        r = self.client.get(reverse('accounts:patient-add'), {'clinic': self.clinic.pk})
        self.assertRedirects(r, reverse('accounts:patients'), fetch_redirect_response=False)
        before = Patient.objects.count()
        self.client.post(reverse('accounts:patient-add') + f'?clinic={self.clinic.pk}', {**PATIENT, 'name': 'Sneaky', 'clinic': self.clinic.pk})
        self.assertEqual(Patient.objects.count(), before)
        # their own private patients are unaffected
        r = self.client.post(reverse('accounts:patient-add'), {**PATIENT, 'name': 'My Own Private'})
        self.assertTrue(Patient.objects.filter(name='My Own Private', clinic__isnull=True, professional=self.physio).exists())

    def test_the_owner_assigns_and_unassigns(self):
        url = reverse('clinics:patient-assign', args=[self.clinic.pk, self.other.pk])
        self.client.post(url, {'members': [self.member.pk, 9999]})
        self.assertEqual(list(self.other.assigned.all()), [self.member])
        self.as_user('physio')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.other.pk])).status_code, 200)
        self.assertEqual(self.client.post(url, {'members': []}).status_code, 404)  # a team member cannot assign
        self.as_user('owner')
        self.client.post(url, {'members': []})
        self.assertEqual(self.other.assigned.count(), 0)
        self.as_user('physio')
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.other.pk])).status_code, 404)

    def test_leaving_the_team_ends_the_access(self):
        self.as_user('physio')
        self.client.post(reverse('clinics:leave', args=[self.clinic.pk]))
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.mine.pk])).status_code, 404)


class DeskAndBookingAssignPatientsTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def test_reception_assigns_a_patient_to_a_therapist(self):
        clinic = self.prepare()
        self.a.clinic, self.a.professional = clinic, self.workspace
        self.a.save()
        self.as_user('ram-desk')
        page = self.client.get(reverse('clinics:desk'), {'tab': 'patients'})
        self.assertContains(page, 'data-assign')
        url = reverse('clinics:desk-patient-assign', args=[self.a.pk])
        self.client.post(url, {'members': [self.member.pk]})
        self.assertEqual(list(self.a.assigned.all()), [self.member])
        self.client.force_login(self.physio_user)
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.a.pk])).status_code, 200)
        self.as_user('asha')  # an assistant cannot assign
        self.assertEqual(self.client.post(url, {'members': []}).status_code, 404)
        self.assertEqual(self.a.assigned.count(), 1)

    def test_booking_with_a_therapist_assigns_the_patient_to_them(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        self.c.clinic, self.c.professional = clinic, self.workspace
        self.c.save()
        self.assertEqual(self.c.assigned.count(), 0)
        self.as_user('ram-desk')
        booking = {'patient': self.c.pk, 'date': timezone.localdate().isoformat(), 'start_time': '09:30', 'duration': 30, 'session_type': 'treatment', 'department': self.pt.pk, 'practitioner': self.member.pk, 'notes': 'x'}
        self.client.post(reverse('clinics:desk-appt-create'), booking)
        self.assertEqual(set(self.c.assigned.all()), {self.member})
        self.client.force_login(self.physio_user)
        self.assertEqual(self.client.get(reverse('accounts:patient-detail', args=[self.c.pk])).status_code, 200)
        # moving an appointment to another person assigns the patient to them too
        appt = Appointment.objects.get(notes='x')
        self.as_user('himal-clinic')
        self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {'date': timezone.localdate().isoformat(), 'start_time': '10:00', 'end_time': '10:30', 'department': '', 'practitioner': self.asha.pk, 'session_type': 'treatment', 'notes': ''})
        appt.refresh_from_db()
        self.assertEqual(appt.practitioner, self.asha)
        self.assertEqual(set(self.c.assigned.all()), {self.member, self.asha})


class TherapistLabelsAndWeekCalendarTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def make_therapist(self, clinic, username, profession, **names):
        from accounts.models import Account, Profession
        user, profile = make_professional(username, **names)
        Account.objects.filter(pk=profile.account_id).update(profession=Profession.objects.get_or_create(name=profession)[0])
        member = ClinicMember.objects.create(clinic=clinic, physio=profile, role='physio', status='active')
        return ClinicMember.objects.get(pk=member.pk)  # read back, so it sees the profession set above

    def test_each_person_is_labelled_with_their_own_profession_not_physiotherapist(self):
        clinic = self.prepare()
        ot = self.make_therapist(clinic, 'ot-one', 'occupational therapist', first_name='Oma', last_name='Rai')
        slp = self.make_therapist(clinic, 'slp-one', 'speech therapist', first_name='Sita', last_name='Rai')
        self.assertEqual((self.member.role_label, ot.role_label, slp.role_label), ('Physiotherapist', 'Occupational therapist', 'Speech therapist'))
        self.assertEqual(ot.choice_label, 'Oma Rai (Occupational therapist)')
        self.assertEqual(self.asha.choice_label, 'Asha (Therapy assistant)')
        self.as_user('himal-clinic')
        page = self.client.get(reverse('accounts:appointments'))
        self.assertContains(page, 'Oma Rai (Occupational therapist)')
        self.assertContains(page, 'Sita Rai (Speech therapist)')
        self.assertNotContains(page, 'Oma Rai (Physiotherapist)')
        self.as_user('ram-desk')
        desk = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertContains(desk, 'Oma Rai (Occupational therapist)')
        self.as_user('owner')
        self.assertContains(self.client.get(reverse('clinics:detail', args=[clinic.pk]), {'tab': 'team'}), 'Occupational therapist')
        from accounts.access import actor_of
        _, role = actor_of(ot.physio.account.user, ot.physio)
        self.assertEqual(role, 'Occupational therapist')  # what a bill or a registration records

    def test_the_week_calendar_opens_alone_without_the_workspace(self):
        self.prepare()
        self.as_user('ram-desk')
        normal = self.client.get(reverse('clinics:desk'), {'tab': 'schedule'})
        self.assertContains(normal, 'Open in a new tab')
        self.assertContains(normal, 'Front desk')  # the sidebar and header
        bare = self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'view': 'calendar', 'bare': 1})
        self.assertEqual(bare.status_code, 200)
        self.assertEqual(bare.context['days'], 7)  # the whole week
        self.assertEqual(len(bare.context['columns']), 7)
        self.assertTrue(bare.context['bare'])
        self.assertNotContains(bare, '<header>')
        self.assertNotContains(bare, '<nav>')
        self.assertContains(bare, 'class="bare"')
        self.assertContains(bare, 'Close this tab')
        self.assertContains(bare, 'name="bare" value="1"')  # booking and changing stay in this tab
        self.assertContains(bare, 'bare=1')
        self.assertNotContains(bare, 'class="seg"')

    def test_booking_from_the_week_calendar_returns_to_it(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        self.c.clinic, self.c.professional = clinic, self.workspace
        self.c.save()
        self.as_user('ram-desk')
        booking = {'patient': self.c.pk, 'date': timezone.localdate().isoformat(), 'start_time': '16:00', 'duration': 30, 'session_type': 'treatment', 'department': self.ot.pk,
                   'practitioner': self.asha.pk, 'notes': 'bare', 'bare': '1'}
        r = self.client.post(reverse('clinics:desk-appt-create'), booking)
        appt = Appointment.objects.get(notes='bare')
        self.assertIn('bare=1', r['Location'])
        self.assertIn('days=7', r['Location'])
        r = self.client.post(reverse('clinics:desk-appt-cancel', args=[appt.pk]), {'bare': '1'})
        self.assertIn('bare=1', r['Location'])
        plain = self.client.post(reverse('clinics:desk-appt-create'), {**booking, 'bare': '', 'notes': 'plain'})
        self.assertNotIn('bare=1', plain['Location'])

    def test_every_role_that_has_the_schedule_can_open_it_alone(self):
        self.prepare()
        for who in ('ram-desk', 'mani', 'asha'):
            self.as_user(who)
            self.assertEqual(self.client.get(reverse('clinics:desk'), {'tab': 'schedule', 'bare': 1}).status_code, 200, who)


class ReceptionAppointmentBookLayoutTests(Base):
    """The clinic login's appointment book (used by reception): no side calendar by default, and a stand-alone week view for its own browser tab."""
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def test_the_side_calendar_is_closed_for_the_clinic_login_and_open_for_a_professional(self):
        self.prepare()
        self.as_user('himal-clinic')
        page = self.client.get(reverse('accounts:appointments'))
        self.assertFalse(page.context['side_open'])
        self.assertContains(page, 'class="appt-layout no-side"')  # the grid takes the whole width
        self.assertContains(page, 'id="sideToggle"')  # one click brings the month calendar and to-do list back
        self.assertContains(page, 'Week in a new tab')
        self.as_user('owner')  # a physiotherapist's own calendar is unchanged
        own = self.client.get(reverse('accounts:appointments'))
        self.assertTrue(own.context['side_open'])
        self.assertNotContains(own, 'class="appt-layout no-side"')

    def test_the_book_opens_alone_for_the_whole_week(self):
        self.prepare()
        self.as_user('himal-clinic')
        bare = self.client.get(reverse('accounts:appointments'), {'bare': 1})
        self.assertEqual(bare.status_code, 200)
        self.assertEqual((bare.context['days'], len(bare.context['columns'])), (7, 7))
        self.assertTrue(bare.context['bare'])
        self.assertEqual(bare.templates[0].name, 'accounts/appointments.html')
        self.assertNotContains(bare, 'class="topbar"')  # no header
        self.assertNotContains(bare, 'class="sidebar"')  # no workspace menu
        self.assertContains(bare, 'class="appt-layout no-side"')
        self.assertContains(bare, 'Close this tab')
        self.assertNotContains(bare, 'Week in a new tab')
        self.assertContains(bare, 'name="bare" value="1"')
        self.assertContains(bare, 'amp;bare=1')  # moving between weeks stays in this view (an escaped &)
        normal = self.client.get(reverse('accounts:appointments'))
        self.assertContains(normal, 'class="topbar"')
        self.assertContains(normal, 'class="sidebar"')

    def test_booking_and_changing_from_the_alone_view_return_to_it(self):
        from accounts.models import Appointment
        clinic = self.prepare()
        self.c.clinic, self.c.professional = clinic, self.workspace
        self.c.save()
        self.as_user('himal-clinic')
        day = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        r = self.client.post(reverse('accounts:appointment-create'), {'patient': self.c.pk, 'date': day, 'start_time': '10:00', 'duration': 30, 'session_type': 'treatment',
                                                                       'department': self.ot.pk, 'practitioner': self.asha.pk, 'notes': 'b', 'days': 7, 'bare': '1'})
        self.assertIn('bare=1', r['Location'])
        appt = Appointment.objects.get(notes='b')
        edit = {'date': day, 'start_time': '10:30', 'end_time': '11:00', 'session_type': 'treatment', 'notes': 'b', 'department': self.ot.pk, 'practitioner': self.asha.pk, 'days': 7}
        self.assertIn('bare=1', self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {**edit, 'bare': '1'})['Location'])
        self.assertNotIn('bare=1', self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), edit)['Location'])
        self.assertIn('bare=1', self.client.post(reverse('accounts:appointment-action', args=[appt.pk]), {'action': 'cancel', 'days': 7, 'bare': '1'})['Location'])


class WideDaysScrollSidewaysTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def test_a_busy_day_gets_wider_so_simultaneous_appointments_stay_readable(self):
        from accounts.models import Appointment
        self.prepare()
        for i in range(3):  # two are already booked at 1:30 pm; five at once in all
            patient = make_patient(self.workspace, f'Extra {i}')
            Appointment.objects.create(professional=self.workspace, patient=patient, start=self.when, end=self.when + datetime.timedelta(minutes=30), department=self.pt, practitioner=self.member)
        self.as_user('himal-clinic')
        for params in ({}, {'bare': 1}):
            page = self.client.get(reverse('accounts:appointments'), params)
            today, tomorrow = page.context['columns'][0], page.context['columns'][1]
            self.assertEqual(today['min_width'], 5 * 140)  # five side by side
            self.assertEqual(tomorrow['min_width'], 170)  # an empty day keeps the normal width
            self.assertContains(page, 'minmax(700px,1fr)')  # the grid is wider than the window, so it scrolls sideways
        self.as_user('ram-desk')
        for params in ({'tab': 'schedule'}, {'tab': 'schedule', 'bare': 1}):
            desk = self.client.get(reverse('clinics:desk'), params)
            self.assertEqual(desk.context['columns'][0]['min_width'], 700)
            self.assertContains(desk, 'minmax(700px,1fr)')
            self.assertContains(desk, 'position: sticky; left: 0')  # the hours stay in view while scrolling


class DeskTreatmentsByDepartmentTests(Base):
    CREDS = StaffLoginTests.CREDS
    add_staff = StaffLoginTests.add_staff
    setup_desk = FrontDeskRegisteredByAndBillingTests.setup_desk
    prepare = SchedulesTests.prepare

    def test_an_assistant_is_offered_the_treatments_of_their_departments(self):
        self.prepare()
        self.as_user('asha')
        any_department = self.client.get(reverse('clinics:desk'), {'tab': 'session'})
        self.assertEqual(any_department.context['treat_ui']['chips'], [])  # no department set: generic
        self.asha.departments.set([self.ot])
        page = self.client.get(reverse('clinics:desk'), {'tab': 'session'})
        self.assertContains(page, '＋ Sensory integration')
        self.assertNotContains(page, '＋ TENS')
        names = [r['name'] for r in self.client.get(reverse('clinics:desk-treatment-search'), {'q': 'sensory', 'kind': 'clinical'}).json()['results']]
        self.assertIn('Sensory integration therapy', names)
        self.assertEqual(self.client.get(reverse('clinics:desk-treatment-search'), {'q': 'tens', 'kind': 'clinical'}).json()['results'], [])
        self.asha.departments.set([self.pt])
        physio = self.client.get(reverse('clinics:desk'), {'tab': 'session'})
        self.assertContains(physio, '＋ TENS')
        self.assertNotContains(physio, '＋ Sensory integration')


class AddAnyRegisteredProfessionalTests(Base):
    """The owner adds speech and occupational therapists, doctors, dentists... by searching, the way physiotherapists are added."""
    def setUp(self):
        super().setUp()
        from accounts.models import Account, Profession
        self.clinic = self.make_clinic()
        self.people = {}
        for username, first, profession in (('ot-one', 'Oma', 'occupational therapist'), ('slp-one', 'Sita', 'speech therapist'), ('doc-one', 'Dev', 'doctors'),
                                            ('dent-one', 'Dina', 'dentist'), ('bo-one', 'Bishnu', 'business owner')):
            user, profile = make_professional(username, first_name=first, last_name='Rai')
            Account.objects.filter(pk=profile.account_id).update(profession=Profession.objects.get_or_create(name=profession)[0])
            self.people[first] = profile

    def search(self, q, **extra):
        return self.client.get(reverse('clinics:physio-search'), {'q': q, 'clinic': self.clinic.pk, **extra}).json()['results']

    def test_they_are_found_by_name_or_by_profession_and_show_what_they_are(self):
        found = {r['name']: r['profession'] for r in self.search('Rai')}
        self.assertEqual(found, {'Oma Rai': 'Occupational therapist', 'Sita Rai': 'Speech therapist', 'Dev Rai': 'Doctors', 'Dina Rai': 'Dentist'})  # not the business owner
        self.assertEqual([r['name'] for r in self.search('speech')], ['Sita Rai'])  # by profession
        self.assertEqual([r['name'] for r in self.search('dentist')], ['Dina Rai'])
        from accounts.models import Profession
        only_ot = Profession.objects.get(name='occupational therapist')
        self.assertEqual([r['name'] for r in self.search('Rai', profession=only_ot.pk)], ['Oma Rai'])  # narrowed to one profession
        self.assertEqual(self.search('Bishnu'), [])  # a business owner is not a clinician
        page = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'team'})
        self.assertContains(page, 'Registered professional')
        self.assertContains(page, 'professionFilter')
        self.assertNotIn('business owner', [p.name for p in page.context['professions']])  # not offered as a profession to add
        self.assertIn('speech therapist', [p.name for p in page.context['professions']])

    def test_inviting_them_works_and_they_join_with_their_own_profession(self):
        for first in ('Oma', 'Sita', 'Dev'):
            r = self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': self.people[first].pk})
            self.assertEqual(r.status_code, 302)
        self.assertEqual(ClinicMember.objects.filter(clinic=self.clinic, status='invited').count(), 3)
        self.client.post(reverse('clinics:invite', args=[self.clinic.pk]), {'physio_id': self.people['Bishnu'].pk})
        self.assertFalse(ClinicMember.objects.filter(physio=self.people['Bishnu']).exists())  # refused
        member = ClinicMember.objects.get(physio=self.people['Oma'])
        self.as_user('ot-one')
        self.client.post(reverse('clinics:invitation-respond', args=[member.pk]), {'action': 'accept'})
        member.refresh_from_db()
        self.assertEqual((member.status, member.role_label), ('active', 'Occupational therapist'))
        self.as_user('owner')
        team = self.client.get(reverse('clinics:detail', args=[self.clinic.pk]), {'tab': 'team'})
        self.assertContains(team, 'Occupational therapist')
        self.assertContains(team, 'Speech therapist')  # invited, shown with what they are
        self.assertContains(team, 'Doctors')
        # and they are bookable like any therapist, labelled with their profession
        from clinics.login import set_clinic_login
        set_clinic_login(self.clinic, 'clinic-desk', PASSWORD)
        self.as_user('clinic-desk')
        self.assertContains(self.client.get(reverse('accounts:appointments')), 'Oma Rai (Occupational therapist)')
