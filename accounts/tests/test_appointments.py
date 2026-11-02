import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.appointments import _layout_lanes, aware, sync_next_appointment
from accounts.models import Appointment, Task, Visit

from .helpers import PASSWORD, make_patient, make_professional


class AppointmentTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.today = timezone.localdate()
        self.tomorrow = self.today + datetime.timedelta(days=1)

    def book(self, date=None, time='10:00', duration=30, **extra):
        return self.client.post(reverse('accounts:appointment-create'), {
            'patient': self.patient.pk, 'date': (date or self.tomorrow).isoformat(), 'start_time': time,
            'duration': duration, 'session_type': 'treatment', 'notes': '', **extra})

    def test_calendar_renders_for_all_ranges_and_bad_input(self):
        self.book()
        for params in ({}, {'days': 1}, {'days': 7}, {'days': 5}, {'date': 'junk'}, {'date': self.tomorrow.isoformat(), 'days': 3}, {'panel': 'todo'}, {'new': 1}):
            self.assertEqual(self.client.get(reverse('accounts:appointments'), params).status_code, 200, params)

    def test_booking_creates_appointment_and_syncs_patient_next_appointment(self):
        r = self.book(duration=45)
        self.assertEqual(r.status_code, 302)
        appt = Appointment.objects.get()
        self.assertEqual(appt.end - appt.start, datetime.timedelta(minutes=45))
        self.assertEqual(timezone.localtime(appt.start).hour, 10)  # stored in Nepal time
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.next_appointment, self.tomorrow)
        calendar = self.client.get(reverse('accounts:appointments'), {'date': self.tomorrow.isoformat()})
        events = [e for col in calendar.context['columns'] for e in col['events']]
        self.assertEqual([e['title'] for e in events], [self.patient.name])

    def test_booking_validation(self):
        bad = self.client.post(reverse('accounts:appointment-create'), {'patient': 9999, 'date': 'x', 'start_time': 'y', 'duration': 30, 'session_type': 'treatment'})
        self.assertEqual(bad.status_code, 302)
        self.assertEqual(Appointment.objects.count(), 0)
        other_user, other_profile = make_professional('other')
        theirs = make_patient(other_profile, 'Theirs')
        self.client.post(reverse('accounts:appointment-create'), {'patient': theirs.pk, 'date': self.tomorrow.isoformat(), 'start_time': '09:00', 'duration': 30, 'session_type': 'treatment'})
        self.assertEqual(Appointment.objects.count(), 0)  # cannot book someone else's patient

    def test_patient_search_for_the_booking_form(self):
        make_patient(self.profile, 'Discharged Dan', status='discharged')
        url = reverse('accounts:appointment-patient-search')
        self.assertEqual([p['name'] for p in self.client.get(url, {'q': 'sita'}).json()['results']], ['Sita Gurung'])
        names = [p['name'] for p in self.client.get(url).json()['results']]
        self.assertNotIn('Discharged Dan', names)
        self.assertEqual(self.client.get(url, {'q': 'zzzz'}).json()['results'], [])

    def test_blocks_validate_and_show(self):
        ok = self.client.post(reverse('accounts:block-create'), {'kind': 'unavailable', 'title': 'Lunch', 'date': self.tomorrow.isoformat(), 'start_time': '12:00', 'end_time': '13:00'})
        self.assertEqual(ok.status_code, 302)
        bad = self.client.post(reverse('accounts:block-create'), {'kind': 'unavailable', 'date': self.tomorrow.isoformat(), 'start_time': '13:00', 'end_time': '12:00'})
        self.assertEqual(bad.status_code, 302)
        self.assertEqual(Appointment.objects.filter(kind='unavailable').count(), 1)

    def test_attending_records_a_visit_and_cancelling_clears_next_appointment(self):
        self.book(date=self.today, time='08:00')
        appt = Appointment.objects.get()
        action = reverse('accounts:appointment-action', args=[appt.pk])
        self.client.post(action, {'action': 'attend'})
        appt.refresh_from_db()
        self.patient.refresh_from_db()
        self.assertEqual(appt.status, 'attended')
        self.assertEqual(self.patient.last_visit, self.today)
        self.assertEqual(Visit.objects.count(), 1)
        self.client.post(action, {'action': 'attend'})  # a second click must not duplicate the visit
        self.assertEqual(Visit.objects.count(), 1)

        self.book()
        future = Appointment.objects.exclude(pk=appt.pk).get()
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.next_appointment, self.tomorrow)
        self.client.post(reverse('accounts:appointment-action', args=[future.pk]), {'action': 'cancel'})
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.next_appointment)
        events = [e for col in self.client.get(reverse('accounts:appointments'), {'date': self.tomorrow.isoformat(), 'days': 1}).context['columns'] for e in col['events']]
        self.assertEqual(events, [])  # cancelled appointments leave the calendar

    def test_reschedule_moves_the_appointment_and_updates_the_next_visit(self):
        self.book()
        appt = Appointment.objects.get()
        later = self.today + datetime.timedelta(days=4)
        r = self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {
            'date': later.isoformat(), 'start_time': '14:30', 'end_time': '15:15', 'session_type': 'follow_up', 'notes': 'Moved'})
        self.assertEqual(r.status_code, 302)
        appt.refresh_from_db()
        local = timezone.localtime(appt.start)
        self.assertEqual((local.date(), local.strftime('%H:%M'), appt.session_type, appt.notes), (later, '14:30', 'follow_up', 'Moved'))
        self.assertEqual(int((appt.end - appt.start).total_seconds() // 60), 45)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.next_appointment, later)

    def test_reschedule_rejects_bad_times_attended_and_strangers(self):
        self.book()
        appt = Appointment.objects.get()
        url = reverse('accounts:appointment-edit', args=[appt.pk])
        before = appt.start
        self.client.post(url, {'date': self.tomorrow.isoformat(), 'start_time': '12:00', 'end_time': '11:00'})
        appt.refresh_from_db()
        self.assertEqual(appt.start, before)
        stranger, _ = make_professional('stranger2')
        other = self.client_class()
        other.force_login(stranger)
        self.assertEqual(other.post(url, {'date': self.tomorrow.isoformat(), 'start_time': '09:00', 'end_time': '10:00'}).status_code, 404)
        appt.status = Appointment.ATTENDED
        appt.save()
        self.client.post(url, {'date': self.tomorrow.isoformat(), 'start_time': '09:00', 'end_time': '10:00'})
        appt.refresh_from_db()
        self.assertEqual(appt.start, before)

    def test_delete_and_ownership(self):
        self.book()
        appt = Appointment.objects.get()
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertEqual(other.post(reverse('accounts:appointment-action', args=[appt.pk]), {'action': 'delete'}).status_code, 404)
        self.assertTrue(Appointment.objects.filter(pk=appt.pk).exists())
        self.client.post(reverse('accounts:appointment-action', args=[appt.pk]), {'action': 'delete'})
        self.assertFalse(Appointment.objects.exists())

    def test_book_next_visit_from_the_patient_page_lands_on_the_calendar(self):
        r = self.client.post(reverse('accounts:patient-next-visit', args=[self.patient.pk]), {'date': self.tomorrow.isoformat(), 'start_time': '09:00'})
        self.assertEqual(r.status_code, 302)
        appt = Appointment.objects.get()
        self.assertEqual((appt.patient, appt.session_type), (self.patient, 'follow_up'))

    def test_sync_next_appointment_picks_the_earliest_upcoming_scheduled(self):
        for days in (5, 2, 9):
            start = aware(self.today + datetime.timedelta(days=days), datetime.time(9, 0))
            Appointment.objects.create(professional=self.profile, patient=self.patient, start=start, end=start + datetime.timedelta(minutes=30))
        sync_next_appointment(self.patient)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.next_appointment, self.today + datetime.timedelta(days=2))

    def test_overlapping_appointments_are_laid_out_side_by_side(self):
        items = [{'start_min': 540, 'end_min': 600}, {'start_min': 560, 'end_min': 620}, {'start_min': 700, 'end_min': 730}]
        _layout_lanes(items)
        self.assertEqual([i['width'] for i in items], [50.0, 50.0, 100.0])
        self.assertEqual([i['left'] for i in items], [0.0, 50.0, 0.0])


class TaskTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)

    def test_task_lifecycle(self):
        self.client.post(reverse('accounts:task-add'), {'text': 'Order supplies', 'due': '2026-10-21T09:30'})
        task = Task.objects.get()
        self.assertEqual(timezone.localtime(task.due).hour, 9)
        self.client.post(reverse('accounts:task-toggle', args=[task.pk]))
        task.refresh_from_db()
        self.assertTrue(task.done)
        page = self.client.get(reverse('accounts:appointments'), {'panel': 'todo'})
        self.assertEqual((page.context['open_count'], page.context['done_count']), (0, 1))
        self.client.post(reverse('accounts:task-delete', args=[task.pk]))
        self.assertFalse(Task.objects.exists())

    def test_blank_task_is_ignored_and_tasks_are_private(self):
        self.client.post(reverse('accounts:task-add'), {'text': ''})
        self.assertEqual(Task.objects.count(), 0)
        task = Task.objects.create(professional=self.profile, text='Mine')
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertEqual(other.post(reverse('accounts:task-delete', args=[task.pk])).status_code, 404)
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())


class SessionTreatmentTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)

    def post(self, treatments, **extra):
        import json
        return self.client.post(reverse('accounts:patient-visit-add', args=[self.patient.pk]), {
            'date': timezone.localdate().isoformat(), 'session_type': 'treatment', 'progress': 'improving', 'notes': 'Good', 'treatments': json.dumps(treatments), **extra})

    def test_a_session_records_the_treatments_given(self):
        r = self.post([{'kind': 'clinical', 'name': 'TENS (pain relief)', 'dosage': '15 min'}, {'kind': 'exercise', 'name': 'Bridging', 'dosage': '3 x 10'}, {'kind': 'bogus', 'name': '  Custom  ', 'dosage': ''}, {'name': ''}])
        self.assertEqual(r.status_code, 302)
        visit = Visit.objects.get()
        self.assertEqual([(t.kind, t.name, t.dosage) for t in visit.treatments.all()], [('clinical', 'TENS (pain relief)', '15 min'), ('exercise', 'Bridging', '3 x 10'), ('clinical', 'Custom', '')])
        tab = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'visits'})
        self.assertContains(tab, 'TENS (pain relief)')
        self.assertContains(tab, 'Record Session')
        self.assertNotContains(tab, 'Record Visit')
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk])), 'Recent Sessions')

    def test_bad_treatment_data_never_blocks_the_session(self):
        self.post('not json')
        self.post({'name': 'x'})
        self.post([{'name': 'N' * 500, 'dosage': 'D' * 500}] * 40)
        self.assertEqual(Visit.objects.count(), 3)
        self.assertEqual(Visit.objects.order_by('id').last().treatments.count(), 30)  # capped
        self.assertEqual(max(len(t.name) for t in Visit.objects.order_by('id').last().treatments.all()), 200)

    def test_search_finds_electrotherapy_and_the_exercise_library(self):
        r = self.client.get(reverse('accounts:treatment-search'), {'q': 'tens'})
        self.assertIn('TENS (pain relief)', [x['name'] for x in r.json()['results']])
        self.assertEqual(self.client.get(reverse('accounts:treatment-search'), {'q': ''}).json()['results'], [])
        self.assertEqual(self.client.get(reverse('accounts:treatment-search'), {'q': 'electro'}).json()['results'][0]['group'], 'Electrotherapy')
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:treatment-search'), {'q': 'tens'}).status_code, 302)


class SessionOnCalendarTests(TestCase):
    """A session recorded for a patient who was never booked still lands on the calendar: it starts when it was entered and runs an hour."""
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.today = timezone.localdate()

    def session(self, date=None, **extra):
        return self.client.post(reverse('accounts:patient-visit-add', args=[self.patient.pk]), {
            'date': (date or self.today).isoformat(), 'session_type': 'treatment', 'progress': '', 'notes': 'Walk-in session', **extra})

    def test_unbooked_session_gets_an_attended_hour_long_appointment(self):
        before = timezone.now()
        self.session()
        appt = Appointment.objects.get()
        self.assertEqual((appt.patient, appt.professional, appt.status, appt.kind), (self.patient, self.profile, Appointment.ATTENDED, Appointment.APPOINTMENT))
        self.assertEqual(appt.end - appt.start, datetime.timedelta(hours=1))
        self.assertLessEqual(abs(timezone.localtime(appt.start) - timezone.localtime(before)), datetime.timedelta(minutes=2))  # started when the session was entered
        self.assertEqual((appt.session_type, appt.notes), ('treatment', 'Walk-in session'))
        events = [e for col in self.client.get(reverse('accounts:appointments'), {'date': self.today.isoformat(), 'days': 1}).context['columns'] for e in col['events']]
        self.assertEqual(len(events), 1)

    def test_a_booked_appointment_is_marked_attended_not_duplicated(self):
        start = aware(self.today, datetime.time(15, 0))
        booked = Appointment.objects.create(professional=self.profile, patient=self.patient, start=start, end=start + datetime.timedelta(minutes=30))
        self.session()
        self.assertEqual(Appointment.objects.count(), 1)
        booked.refresh_from_db()
        self.assertEqual(booked.status, Appointment.ATTENDED)
        self.session()  # a second session the same day does not add a second entry either
        self.assertEqual(Appointment.objects.count(), 1)

    def test_other_days_cancelled_bookings_and_attending_do_not_double_up(self):
        yesterday = self.today - datetime.timedelta(days=1)
        self.session(yesterday)
        self.assertEqual(timezone.localtime(Appointment.objects.get().start).date(), yesterday)
        self.session()  # a different day gets its own entry
        self.assertEqual(Appointment.objects.count(), 2)
        start = aware(self.today + datetime.timedelta(days=3), datetime.time(9, 0))
        appt = Appointment.objects.create(professional=self.profile, patient=self.patient, start=start, end=start + datetime.timedelta(minutes=30))
        self.client.post(reverse('accounts:appointment-action', args=[appt.pk]), {'action': 'attend'})
        self.assertEqual(Appointment.objects.count(), 3)  # marking attended records the session without adding another entry


class DashboardCardTests(TestCase):
    def test_the_cards_open_the_matching_screens(self):
        user, profile = make_professional()
        self.client.force_login(user)
        old = make_patient(profile, 'Stale Patient')
        fresh = make_patient(profile, 'Fresh Patient')
        old.last_visit = timezone.localdate() - datetime.timedelta(days=30)
        old.save()
        fresh.last_visit = timezone.localdate()
        fresh.save()
        page = self.client.get(reverse('accounts:dashboard'))
        for target in (reverse('accounts:appointments') + f'?date={timezone.localdate().isoformat()}&days=1', reverse('accounts:patients') + '?status=active',
                       reverse('accounts:patients') + '?followup=due', reverse('billing:billing')):
            self.assertContains(page, f'href="{target}"')
        listing = self.client.get(reverse('accounts:patients'), {'followup': 'due'})
        self.assertEqual([p.name for p in listing.context['page_obj']], ['Stale Patient'])
        self.assertContains(listing, 'due for a follow-up')
        self.assertEqual(len(self.client.get(reverse('accounts:patients'), {'status': 'active'}).context['page_obj']), 2)


class AppointmentWhatsAppTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    def book(self):
        return self.client.post(reverse('accounts:appointment-create'), {
            'patient': self.patient.pk, 'date': self.tomorrow.isoformat(), 'start_time': '15:00', 'duration': 30, 'session_type': 'treatment', 'notes': ''})

    def test_booking_offers_a_whatsapp_message_to_the_patients_own_chat(self):
        r = self.book()
        appt = Appointment.objects.get()
        self.assertIn(f'booked={appt.pk}', r['Location'])
        page = self.client.get(r['Location'])
        prompt = page.context['prompt']
        self.assertEqual(prompt['kind'], 'booked')
        self.assertTrue(prompt['url'].startswith('https://wa.me/9779841000000?text='), prompt['url'])  # the patient's number, with the country code
        from urllib.parse import unquote
        text = unquote(prompt['url'].split('text=', 1)[1])
        self.assertIn('Sita Gurung', text)
        self.assertIn('is booked for', text)
        self.assertIn('3:00 PM', text)
        self.assertContains(page, 'Send by WhatsApp')
        self.assertContains(page, 'wa.me/9779841000000')  # also on the calendar entry, for the details window

    def test_rescheduling_offers_a_rescheduled_message_and_other_cases_stay_quiet(self):
        self.book()
        appt = Appointment.objects.get()
        r = self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {'date': self.tomorrow.isoformat(), 'start_time': '16:30', 'end_time': '17:00', 'session_type': 'treatment', 'notes': ''})
        page = self.client.get(r['Location'])
        self.assertEqual(page.context['prompt']['kind'], 'rescheduled')
        from urllib.parse import unquote
        self.assertIn('has been rescheduled to', unquote(page.context['prompt']['url']))
        self.assertIsNone(self.client.get(reverse('accounts:appointments')).context['prompt'])  # no banner on a normal visit
        self.assertIsNone(self.client.get(reverse('accounts:appointments'), {'booked': 'x'}).context['prompt'])
        appt.status = Appointment.CANCELLED
        appt.save()
        self.assertIsNone(self.client.get(reverse('accounts:appointments'), {'booked': appt.pk}).context['prompt'])  # cancelled: nothing to confirm

    def test_next_visit_from_the_patient_page_offers_it_too_and_without_a_number_the_contact_is_chosen(self):
        r = self.client.post(reverse('accounts:patient-next-visit', args=[self.patient.pk]), {'date': self.tomorrow.isoformat(), 'start_time': '09:00'})
        self.assertIn('booked=', r['Location'])
        page = self.client.get(r['Location'])
        self.assertContains(page, 'Send by WhatsApp')
        self.patient.phone = ''
        self.patient.save()
        page = self.client.get(r['Location'])
        self.assertTrue(page.context['prompt']['url'].startswith('https://wa.me/?text='))
        self.assertFalse(page.context['prompt']['has_phone'])
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertIsNone(other.get(reverse('accounts:appointments'), {'booked': Appointment.objects.get().pk}).context['prompt'])  # someone else's booking


class TreatedTodayTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def session(self, patient, **extra):
        return self.client.post(reverse('accounts:patient-visit-add', args=[patient.pk]), {'date': self.today.isoformat(), 'session_type': 'treatment', 'progress': '', 'notes': '', **extra})

    def test_the_dashboard_counts_patients_treated_today_and_lists_who_treated_and_when(self):
        import json
        a, b, c = make_patient(self.profile, 'Anita Rai'), make_patient(self.profile, 'Bina Lama'), make_patient(self.profile, 'Chandra Shah')
        self.session(a, treatments=json.dumps([{'kind': 'clinical', 'name': 'TENS (pain relief)', 'dosage': '15 min'}]))
        self.session(a)  # a second session for the same patient: one patient, two sessions
        self.session(b)
        old = Visit.objects.create(patient=c, date=self.today - datetime.timedelta(days=1), therapist='Someone')  # yesterday: not counted today
        # a session recorded by a therapy assistant (as the front desk does)
        Visit.objects.create(patient=c, date=self.today, therapist='Asha', recorded_by_role='Therapy assistant')
        page = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(page.context['stats']['treated_today'], 3)
        self.assertEqual(page.context['treated_summary'], {'sessions': 4, 'patients': 3, 'by_therapist': 3, 'by_assistant': 1})
        self.assertContains(page, 'Treated Today')
        self.assertContains(page, reverse('accounts:treated'))
        names = [v.patient.name for v in page.context['treated']]
        self.assertEqual(names[0], 'Chandra Shah')  # latest first on the dashboard
        row = page.context['treated'][0]
        self.assertEqual((row.therapist, row.treated_by_role), ('Asha', 'Therapy assistant'))
        self.assertContains(page, 'Therapy assistant')
        self.assertContains(page, 'Asha')

    def test_the_treated_page_shows_the_time_the_person_and_what_was_done_for_any_day(self):
        import json
        patient = make_patient(self.profile, 'Anita Rai')
        self.session(patient, treatments=json.dumps([{'kind': 'clinical', 'name': 'Hot pack', 'dosage': '10 min'}, {'kind': 'exercise', 'name': 'Bridging', 'dosage': '3 x 10'}]), notes='Went well')
        page = self.client.get(reverse('accounts:treated'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Anita Rai')
        self.assertContains(page, 'Treatment given')
        self.assertContains(page, 'Exercises supervised')
        self.assertContains(page, 'Hot pack')
        self.assertContains(page, 'Bridging')
        self.assertContains(page, 'Physiotherapist')
        self.assertContains(page, self.profile.full_name)
        visit = Visit.objects.get()
        self.assertContains(page, timezone.localtime(visit.created_at).strftime('%I:%M').lstrip('0'))  # the time it was recorded
        self.assertEqual(page.context['summary'], {'sessions': 1, 'patients': 1, 'by_therapist': 1, 'by_assistant': 0})
        yesterday = self.today - datetime.timedelta(days=1)
        past = self.client.get(reverse('accounts:treated'), {'date': yesterday.isoformat()})
        self.assertEqual(past.context['summary']['sessions'], 0)
        self.assertContains(past, 'Nobody was treated')
        self.assertEqual(self.client.get(reverse('accounts:treated'), {'date': 'junk'}).context['day'], self.today)

    def test_it_is_private_and_a_clinic_login_sees_its_assistants_work(self):
        mine = make_patient(self.profile, 'Anita Rai')
        self.session(mine)
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertEqual(other.get(reverse('accounts:treated')).context['summary']['sessions'], 0)
        self.assertEqual(other.get(reverse('accounts:dashboard')).context['stats']['treated_today'], 0)
        make_professional('waiting', status='submitted')
        waiting = self.client_class()
        waiting.login(username='waiting', password=PASSWORD)
        self.assertEqual(waiting.get(reverse('accounts:treated')).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:treated')).status_code, 302)


class DepartmentTests(TestCase):
    """Appointments are booked into departments, so one time slot can hold Physical Therapy and Occupational Therapy side by side."""
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.day = timezone.localdate() + datetime.timedelta(days=1)

    def book(self, patient, department=None, **extra):
        return self.client.post(reverse('accounts:appointment-create'), {'patient': patient.pk, 'date': self.day.isoformat(), 'start_time': '13:30', 'duration': 30,
                                                                         'session_type': 'treatment', 'department': department.pk if department else '', 'notes': '', **extra})

    def test_manage_departments(self):
        from accounts.models import Department
        page = self.client.get(reverse('accounts:departments'))
        self.assertContains(page, 'Add the suggested departments')
        self.client.post(reverse('accounts:departments'), {'action': 'suggest'})
        self.assertEqual(self.profile.departments.count(), len(Department.SUGGESTED))
        self.client.post(reverse('accounts:departments'), {'name': ' Cardio  Rehab '})
        self.assertTrue(self.profile.departments.filter(name='Cardio Rehab').exists())
        self.client.post(reverse('accounts:departments'), {'name': 'cardio rehab'})  # same name, any case
        self.assertEqual(self.profile.departments.filter(name__iexact='cardio rehab').count(), 1)
        self.client.post(reverse('accounts:departments'), {'name': '  '})
        stranger, other = make_professional('stranger')
        theirs = Department.objects.create(professional=other, name='Theirs')
        self.assertEqual(self.client.post(reverse('accounts:department-delete', args=[theirs.pk])).status_code, 404)
        mine = self.profile.departments.get(name='Cardio Rehab')
        self.client.post(reverse('accounts:department-delete', args=[mine.pk]))
        self.assertFalse(self.profile.departments.filter(name='Cardio Rehab').exists())

    def test_two_patients_at_the_same_time_in_different_departments(self):
        from accounts.models import Appointment, Department
        pt = Department.objects.create(professional=self.profile, name='Physical Therapy')
        ot = Department.objects.create(professional=self.profile, name='Occupational Therapy')
        a, c = make_patient(self.profile, 'Patient A'), make_patient(self.profile, 'Patient C')
        self.book(a, pt)
        self.book(c, ot)
        self.assertEqual({x.patient.name: x.department.name for x in Appointment.objects.all()}, {'Patient A': 'Physical Therapy', 'Patient C': 'Occupational Therapy'})
        page = self.client.get(reverse('accounts:appointments'), {'date': self.day.isoformat(), 'days': 1})
        events = page.context['columns'][0]['events']
        self.assertEqual(sorted((e['title'], e['department']) for e in events), [('Patient A', 'Physical Therapy'), ('Patient C', 'Occupational Therapy')])
        self.assertEqual({e['lane'] for e in events}, {0, 1})  # side by side
        self.assertContains(page, 'Physical Therapy')
        only_ot = self.client.get(reverse('accounts:appointments'), {'date': self.day.isoformat(), 'days': 1, 'dept': ot.pk})
        self.assertEqual([e['title'] for e in only_ot.context['columns'][0]['events']], ['Patient C'])
        none = self.client.get(reverse('accounts:appointments'), {'date': self.day.isoformat(), 'days': 1, 'dept': 'none'})
        self.assertEqual(none.context['columns'][0]['events'], [])

    def test_a_department_of_another_practice_cannot_be_used_and_it_can_be_changed_later(self):
        from accounts.models import Appointment, Department
        stranger, other = make_professional('stranger')
        foreign = Department.objects.create(professional=other, name='Foreign')
        mine = Department.objects.create(professional=self.profile, name='Speech Therapy')
        patient = make_patient(self.profile, 'Patient A')
        self.book(patient, foreign)
        self.assertEqual(Appointment.objects.count(), 0)  # refused
        self.book(patient)
        appt = Appointment.objects.get()
        self.assertIsNone(appt.department)
        edit = {'date': self.day.isoformat(), 'start_time': '14:00', 'end_time': '14:30', 'session_type': 'treatment', 'notes': ''}
        self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {**edit, 'department': mine.pk})
        appt.refresh_from_db()
        self.assertEqual(appt.department, mine)
        self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {**edit, 'department': foreign.pk})
        appt.refresh_from_db()
        self.assertIsNone(appt.department)  # not theirs: cleared, never attached
        self.client.post(reverse('accounts:appointment-edit', args=[appt.pk]), {**edit, 'department': mine.pk})
        mine.delete()
        appt.refresh_from_db()
        self.assertIsNone(appt.department)  # the appointment stays


class DepartmentTreatmentTests(TestCase):
    """The treatments offered in a session are the department's own: no TENS or ultrasound for occupational, speech or behaviour therapy."""
    def setUp(self):
        from accounts.models import Account, Profession
        self.users = {}
        for key, profession in (('physio', 'physiotherapist'), ('ot', 'occupational therapist'), ('speech', 'speech therapist'), ('behaviour', 'behaviour therapist')):
            user, profile = make_professional(f'u-{key}')
            Account.objects.filter(pk=profile.account_id).update(profession=Profession.objects.get_or_create(name=profession)[0])
            self.users[key] = (user, profile)

    def search(self, key, q):
        self.client.force_login(self.users[key][0])
        return [r['name'] for r in self.client.get(reverse('accounts:treatment-search'), {'q': q, 'kind': 'clinical'}).json()['results']]

    def test_each_department_is_offered_its_own_treatments(self):
        self.assertIn('TENS (pain relief)', self.search('physio', 'tens'))
        self.assertEqual(self.search('ot', 'tens'), [])
        self.assertEqual(self.search('speech', 'tens'), [])
        self.assertEqual(self.search('behaviour', 'ultrasound'), [])
        self.assertIn('Sensory integration therapy', self.search('ot', 'sensory'))
        self.assertIn('Handwriting training', self.search('ot', 'handwriting'))
        self.assertEqual(self.search('physio', 'sensory integration'), [])
        self.assertIn('Articulation therapy', self.search('speech', 'articulation'))
        self.assertIn('Swallowing (dysphagia) therapy', self.search('speech', 'swallow'))
        self.assertIn('Applied behaviour analysis (ABA) session', self.search('behaviour', 'aba'))
        self.assertEqual(self.search('physio', 'articulation'), [])

    def test_the_session_form_has_the_departments_own_quick_buttons(self):
        patients = {}
        for key, (user, profile) in self.users.items():
            patients[key] = make_patient(profile, f'Patient {key}')
        expect = {'physio': ('＋ TENS', '＋ Ultrasound'), 'ot': ('＋ Sensory integration', '＋ Handwriting'), 'speech': ('＋ Articulation', '＋ Voice'), 'behaviour': ('＋ ABA session', '＋ Token system')}
        for key, (user, profile) in self.users.items():
            self.client.force_login(user)
            page = self.client.get(reverse('accounts:patient-detail', args=[patients[key].pk]))
            for chip in expect[key]:
                self.assertContains(page, chip, msg_prefix=key)
            for other, chips in expect.items():
                if other != key:
                    for chip in chips:
                        self.assertNotContains(page, chip, msg_prefix=f'{key} must not see {other}')
        self.client.force_login(self.users['ot'][0])
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[patients['ot'].pk])), 'search sensory integration, fine motor')

    def test_a_clinic_login_searches_every_department_with_labels(self):
        from clinics.login import set_clinic_login
        from clinics.models import Clinic, ClinicSubscription
        clinic = Clinic.objects.create(owner=self.users['physio'][1], name='Mixed', phone='01555')
        ClinicSubscription.objects.create(professional=self.users['physio'][1], status='active')
        user = set_clinic_login(clinic, 'mixed-clinic', 'Gr33n!Health-99')
        self.client.force_login(user)
        results = self.client.get(reverse('accounts:treatment-search'), {'q': 'therapy', 'kind': 'clinical'}).json()['results']
        groups = {r['group'].split(':')[0] for r in results}
        self.assertGreater(len(groups), 1)
        self.assertTrue(all(':' in r['group'] for r in results))  # each result says which department it belongs to

    def test_a_visit_keeps_whatever_treatment_was_typed_or_picked(self):
        from accounts.models import Visit
        user, profile = self.users['ot']
        patient = make_patient(profile, 'Child')
        self.client.force_login(user)
        self.client.post(reverse('accounts:patient-visit-add', args=[patient.pk]), {'date': timezone.localdate().isoformat(), 'session_type': 'treatment',
                                                                                    'treatments': '[{"kind": "clinical", "name": "Sensory integration therapy", "dosage": "30 min"}]'})
        self.assertEqual([t.name for t in Visit.objects.get().treatments.all()], ['Sensory integration therapy'])
