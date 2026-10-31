"""Treatments given in a session: what the therapist can pick from, and how the posted list is checked."""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .access import workspace_profile
from .models import VisitTreatment

# (group, name, usual dose) - searched as the therapist types; anything else can still be typed in and added.
OPTIONS = [
    ('Electrotherapy', 'TENS (pain relief)', '15-20 min'), ('Electrotherapy', 'IFC / Interferential current', '15-20 min'),
    ('Electrotherapy', 'Therapeutic ultrasound', '5-8 min'), ('Electrotherapy', 'Shortwave diathermy (SWD)', '15-20 min'),
    ('Electrotherapy', 'Microwave diathermy', '10-15 min'), ('Electrotherapy', 'Muscle stimulation (NMES / EMS)', '15 min'),
    ('Electrotherapy', 'Low-level laser therapy', '5 min'), ('Electrotherapy', 'Magnetic therapy', '20 min'),
    ('Electrotherapy', 'Shockwave therapy (ESWT)', '1 session'), ('Electrotherapy', 'Galvanic / iontophoresis', '15 min'),
    ('Electrotherapy', 'Russian current', '15 min'), ('Electrotherapy', 'Biofeedback', '15 min'),
    ('Thermal', 'Hot pack', '15 min'), ('Thermal', 'Cold pack / cryotherapy', '10-15 min'), ('Thermal', 'Infrared (IRR)', '15 min'),
    ('Thermal', 'Paraffin wax bath', '15 min'), ('Thermal', 'Contrast bath', '15 min'), ('Thermal', 'Steam / moist heat', '15 min'),
    ('Traction', 'Cervical traction', '10-15 min'), ('Traction', 'Lumbar traction', '10-15 min'),
    ('Manual', 'Manual therapy', ''), ('Manual', 'Joint mobilization (Grade I-II)', ''), ('Manual', 'Joint mobilization (Grade III-IV)', ''),
    ('Manual', 'Soft tissue release / massage', '10 min'), ('Manual', 'Myofascial release', '10 min'), ('Manual', 'Muscle energy technique', ''),
    ('Manual', 'Dry needling', ''), ('Manual', 'Cupping', '10 min'), ('Manual', 'Kinesio taping', ''), ('Manual', 'Bracing / splinting', ''),
    ('Therapeutic', 'Passive ROM', '10 reps'), ('Therapeutic', 'Active-assisted ROM (AAROM)', '10 reps'), ('Therapeutic', 'Stretching', '3 x 30 s'),
    ('Therapeutic', 'Strengthening exercises', '3 x 10'), ('Therapeutic', 'Balance and proprioception training', '10 min'),
    ('Therapeutic', 'Gait training', '10 min'), ('Therapeutic', 'Postural re-education', ''), ('Therapeutic', 'Core stabilization', '3 x 10'),
    ('Therapeutic', 'Breathing exercises', '5 min'), ('Therapeutic', 'Home exercise program taught', ''),
]
MAX_TREATMENTS = 30


def parse_treatments(raw):
    """The treatments posted by the session form (a JSON list), cleaned: known kinds only, trimmed, length-limited, no blanks."""
    try:
        rows = json.loads(raw or '[]')
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []
    kinds = {k for k, _ in VisitTreatment.KIND_CHOICES}
    out = []
    for row in rows[:MAX_TREATMENTS]:
        if not isinstance(row, dict):
            continue
        name = str(row.get('name', '')).strip()[:200]
        if not name:
            continue
        kind = row.get('kind') if row.get('kind') in kinds else VisitTreatment.CLINICAL
        out.append({'kind': kind, 'name': name, 'dosage': str(row.get('dosage', '')).strip()[:100]})
    return out


@login_required
def treatment_search(request):
    """Type-ahead for the session form: clinical / electrotherapy options first, then the exercise library."""
    if workspace_profile(request) is None:
        return JsonResponse({'results': []})
    from assessments import disciplines
    return JsonResponse({'results': search_options(request.GET.get('q', ''), request.GET.get('kind', ''), disciplines.visible_filter(disciplines.allowed(workspace_profile(request))))})


def search_options(query, kind='', visible=None):
    """Clinical / electrotherapy options and exercise-library matches for a search text. kind 'clinical' or 'exercise' limits it to one list."""
    q = (query or '').strip().lower()
    if not q:
        return []
    results = []
    if kind != 'exercise':
        results += [{'kind': 'clinical', 'name': name, 'dose': dose, 'group': group} for group, name, dose in OPTIONS if q in name.lower() or q in group.lower()][:10]
    if kind != 'clinical' and len(q) >= 2:
        from exercises.models import ExerciseMain
        library = ExerciseMain.objects.filter(exercise_name__icontains=q)
        if visible is not None:  # only the department's own library
            library = library.filter(discipline__in=visible)
        for e in library.order_by('exercise_name')[:10]:
            results.append({'kind': 'exercise', 'name': e.exercise_name, 'dose': e.dose_label, 'group': 'Exercise'})
    return results
