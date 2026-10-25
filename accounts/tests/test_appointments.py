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
