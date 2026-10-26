"""Business actions that more than one screen performs. Put side effects here so they cannot drift apart."""
from .models import Visit, VisitTreatment


def record_visit(patient, therapist, date, session_type=Visit.TREATMENT, progress='', notes='', treatments=(), professional=None):
    """Record that a session happened. Every way of recording a visit (the visit form, marking an appointment
    attended) goes through here, so each one also:
      - moves the patient's last-visit date forward (never backwards), and
      - uses up one session of the patient's active package, if they have one, and
      - when `professional` is given, puts the session on that professional's calendar if the patient was not booked for that day
        (see calendar_entry_for_session).
    Returns (visit, package_session_used)."""
    from billing.models import use_package_session  # billing depends on accounts, so import lazily

    visit = Visit.objects.create(patient=patient, date=date, therapist=therapist, session_type=session_type, progress=progress, notes=notes)
    for order, t in enumerate(treatments):
        VisitTreatment.objects.create(visit=visit, kind=t['kind'], name=t['name'], dosage=t['dosage'], order=order)
    patient.last_visit = max(d for d in (patient.last_visit, date) if d)
    patient.save(update_fields=['last_visit'])
    patient.touch()
    if professional is not None:
        calendar_entry_for_session(patient, professional, date, session_type, notes)
    return visit, use_package_session(patient)


def calendar_entry_for_session(patient, professional, date, session_type, notes=''):
    """A session happened for a patient who was never booked: add it to the calendar. It starts when the session was entered and
    runs one hour. A booked-but-unmarked appointment that day is marked attended instead, so nothing is duplicated."""
    import datetime

    from django.utils import timezone

    from .appointments import aware, sync_next_appointment
    from .models import Appointment

    day_start = aware(date, datetime.time.min)
    that_day = Appointment.objects.filter(professional=professional, patient=patient, kind=Appointment.APPOINTMENT,
                                          start__gte=day_start, start__lt=day_start + datetime.timedelta(days=1)).exclude(status=Appointment.CANCELLED)
    booked = that_day.filter(status=Appointment.SCHEDULED).first()
    if booked is not None:
        booked.status = Appointment.ATTENDED
        booked.save(update_fields=['status'])
    elif not that_day.exists():
        start = aware(date, timezone.localtime().time().replace(second=0, microsecond=0))
        Appointment.objects.create(professional=professional, patient=patient, start=start, end=start + datetime.timedelta(hours=1),
                                   session_type=session_type, status=Appointment.ATTENDED, notes=notes)
    sync_next_appointment(patient)
