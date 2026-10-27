import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.appointments import _layout_lanes, aware, sync_next_appointment
from accounts.models import Appointment, Task, Visit

from .helpers import make_patient, make_professional


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
