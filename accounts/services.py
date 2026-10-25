"""Business actions that more than one screen performs. Put side effects here so they cannot drift apart."""
from .models import Visit, VisitTreatment


def record_visit(patient, therapist, date, session_type=Visit.TREATMENT, progress='', notes='', treatments=()):
    """Record that a session happened. Every way of recording a visit (the visit form, marking an appointment
    attended) goes through here, so each one also:
      - moves the patient's last-visit date forward (never backwards), and
      - uses up one session of the patient's active package, if they have one.
    Returns (visit, package_session_used)."""
    from billing.models import use_package_session  # billing depends on accounts, so import lazily

    visit = Visit.objects.create(patient=patient, date=date, therapist=therapist, session_type=session_type, progress=progress, notes=notes)
    for order, t in enumerate(treatments):
        VisitTreatment.objects.create(visit=visit, kind=t['kind'], name=t['name'], dosage=t['dosage'], order=order)
    patient.last_visit = max(d for d in (patient.last_visit, date) if d)
    patient.save(update_fields=['last_visit'])
    patient.touch()
    return visit, use_package_session(patient)
