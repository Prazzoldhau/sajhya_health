"""Who is seen when: one day of a clinic's appointments, for the front desk, a department's sign-in and a therapist's own page."""
import datetime

from django.utils import timezone

from accounts.models import Appointment


def parse_day(raw):
    try:
        return datetime.date.fromisoformat(raw or '')
    except ValueError:
        return timezone.localdate()


def appointments_between(first, last, **filters):
    """Live (not cancelled) appointments starting from the first day to the last day inclusive, earliest first."""
    start = timezone.make_aware(datetime.datetime.combine(first, datetime.time.min))
    end = timezone.make_aware(datetime.datetime.combine(last + datetime.timedelta(days=1), datetime.time.min))
    return list(Appointment.objects.filter(kind=Appointment.APPOINTMENT, start__gte=start, start__lt=end, **filters)
                .exclude(status=Appointment.CANCELLED).select_related('patient', 'department', 'practitioner__physio', 'professional').order_by('start', 'id'))


def appointments_on(day, **filters):
    """Live (not cancelled) appointments starting on a day, earliest first."""
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    return list(Appointment.objects.filter(kind=Appointment.APPOINTMENT, start__gte=start, start__lt=start + datetime.timedelta(days=1), **filters)
                .exclude(status=Appointment.CANCELLED).select_related('patient', 'department', 'practitioner__physio', 'professional').order_by('start', 'id'))


def day_context(day):
    today = timezone.localdate()
    return {'day': day, 'today': today, 'prev_day': day - datetime.timedelta(days=1), 'next_day': day + datetime.timedelta(days=1)}
