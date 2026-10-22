"""The physiotherapy part of a patient's rehab profile, assembled from what the professional already records.

Nothing here is typed in twice: assessments come from initial-assessment visits and treatment-plan measures,
exercises from exercise prescriptions, interventions from the plan's clinic interventions and treatment visits.
"""
from accounts.models import TreatmentPlan, Visit


def physio_summary(patient):
    visits = list(patient.visits.all()[:40])
    plans = list(patient.plans.exclude(status=TreatmentPlan.DISCONTINUED).prefetch_related('measures__readings', 'phases__items'))
    plans.sort(key=lambda p: (p.status != TreatmentPlan.ACTIVE, -p.pk))  # the active plan first
    plan = plans[0] if plans else None

    measures = []
    for m in (plan.measures.all() if plan else []):
        readings = sorted(m.readings.all(), key=lambda r: (r.date, r.id))
        measures.append({'name': m.name, 'unit': m.unit, 'baseline': m.baseline, 'latest': m.latest, 'target': m.target,
                         'progress': m.progress_pct, 'last_date': readings[-1].date if readings else None, 'readings': len(readings)})

    current_phase = None
    clinic_by_phase = []
    for phase in (plan.phases.all() if plan else []):
        items = [i for i in phase.items.all() if i.kind == 'clinic']
        if phase.status == 'current':
            current_phase = phase
        if items:
            clinic_by_phase.append({'phase': phase, 'items': items})

    prescriptions = list(patient.prescriptions.prefetch_related('exercises__exercise__step_images').order_by('status', '-created_at')[:6])
    prescriptions.sort(key=lambda p: (p.status != 'active', -p.pk))

    return {
        'plan': plan,
        'initial_assessments': [v for v in visits if v.session_type == Visit.INITIAL],
        'measures': measures,
        'prescriptions': prescriptions,
        'current_phase': current_phase,
        'clinic_by_phase': clinic_by_phase,
        'recent_treatments': [v for v in visits if v.session_type != Visit.INITIAL][:10],
        'visit_count': patient.visits.count(),
        'has_data': bool(visits or plan or prescriptions),
    }
