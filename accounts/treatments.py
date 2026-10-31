"""Treatments given in a session: what the therapist can pick from, and how the posted list is checked."""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from assessments.disciplines import LABELS, SPECIFIC

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
# What each department gives in a session, searched as the therapist types. Doses are usual starting points to change per patient.
OT_OPTIONS = [
    ('Sensory integration', 'Sensory integration therapy', '30 min'), ('Sensory integration', 'Deep pressure / proprioceptive input', '10 min'),
    ('Sensory integration', 'Vestibular activities (swing, spinning board)', '10 min'), ('Sensory integration', 'Tactile exploration / desensitisation', '10 min'),
    ('Sensory integration', 'Sensory diet planning', ''), ('Sensory integration', 'Oral sensory-motor and feeding therapy', '15 min'),
    ('Fine motor and hand', 'Fine motor training', '20 min'), ('Fine motor and hand', 'Handwriting training', '20 min'), ('Fine motor and hand', 'Hand strengthening', '15 min'),
    ('Fine motor and hand', 'In-hand manipulation practice', '15 min'), ('Fine motor and hand', 'Visual-perceptual training', '20 min'), ('Fine motor and hand', 'Hand-eye coordination activities', '15 min'),
    ('Fine motor and hand', 'Splinting / orthosis fitting', ''), ('Fine motor and hand', 'Scar and oedema management', '10 min'), ('Fine motor and hand', 'Paraffin wax bath', '15 min'),
    ('Daily living', 'ADL training (dressing, feeding, toileting)', '30 min'), ('Daily living', 'Self-care training', '30 min'), ('Daily living', 'Home and school adaptation advice', ''),
    ('Daily living', 'Parent and caregiver training', '15 min'),
    ('Cognition and play', 'Cognitive retraining', '20 min'), ('Cognition and play', 'Play-based therapy', '30 min'), ('Cognition and play', 'Attention and executive function activities', '20 min'),
    ('Cognition and play', 'Neurodevelopmental treatment (NDT)', '30 min'), ('Cognition and play', 'Postural control and seating', '15 min'),
]
SPEECH_OPTIONS = [
    ('Speech sounds', 'Articulation therapy', '30 min'), ('Speech sounds', 'Phonological therapy', '30 min'), ('Speech sounds', 'Oral-motor exercises', '10 min'),
    ('Speech sounds', 'Speech sound discrimination (minimal pairs)', '15 min'),
    ('Language', 'Language stimulation', '30 min'), ('Language', 'Receptive language therapy', '30 min'), ('Language', 'Expressive language therapy', '30 min'),
    ('Language', 'Vocabulary building', '20 min'), ('Language', 'Sentence and grammar practice', '20 min'), ('Language', 'Story telling and narrative practice', '20 min'),
    ('Communication', 'Augmentative and alternative communication (AAC)', '30 min'), ('Communication', 'Picture exchange (PECS) training', '30 min'),
    ('Communication', 'Social communication and pragmatics', '30 min'), ('Communication', 'Parent coaching on communication', '15 min'),
    ('Voice and fluency', 'Voice therapy', '30 min'), ('Voice and fluency', 'Fluency shaping', '30 min'), ('Voice and fluency', 'Stuttering modification', '30 min'),
    ('Voice and fluency', 'Breathing and phonation exercises', '10 min'),
    ('Swallowing and feeding', 'Swallowing (dysphagia) therapy', '30 min'), ('Swallowing and feeding', 'Feeding and oral skills therapy', '30 min'),
    ('Hearing', 'Auditory training', '20 min'), ('Hearing', 'Listening skills practice', '20 min'), ('Hearing', 'Hearing aid orientation and care', ''),
    ('Hearing', 'Speech reading (lip reading) training', '20 min'),
]
BEHAVIOUR_OPTIONS = [
    ('Assessment', 'Functional behaviour assessment (FBA)', '60 min'), ('Assessment', 'Behaviour observation', '30 min'), ('Assessment', 'Behaviour management plan review', '20 min'),
    ('Behaviour intervention', 'Applied behaviour analysis (ABA) session', '60 min'), ('Behaviour intervention', 'Discrete trial training', '30 min'), ('Behaviour intervention', 'Natural environment teaching', '30 min'),
    ('Behaviour intervention', 'Positive reinforcement / token system', '20 min'), ('Behaviour intervention', 'Prompting and fading', '20 min'), ('Behaviour intervention', 'Extinction and redirection plan', ''),
    ('Skills training', 'Social skills training', '30 min'), ('Skills training', 'Communication training (functional)', '30 min'), ('Skills training', 'Self-help and daily living skills', '30 min'),
    ('Skills training', 'Visual schedule teaching', '15 min'), ('Skills training', 'Toilet training programme', '15 min'),
    ('Emotional regulation', 'Relaxation and self-regulation training', '20 min'), ('Emotional regulation', 'Cognitive behavioural therapy (CBT)', '45 min'),
    ('Emotional regulation', 'Anger and anxiety management', '30 min'), ('Emotional regulation', 'Play therapy', '45 min'),
    ('Family', 'Parent training', '45 min'), ('Family', 'Family counselling', '45 min'), ('Family', 'School consultation', '30 min'),
]
LISTS = {'physio': OPTIONS, 'ot': OT_OPTIONS, 'speech': SPEECH_OPTIONS, 'behaviour': BEHAVIOUR_OPTIONS}
# the quick buttons above the search box: (name, usual dose, short label)
CHIPS = {
    'physio': [('TENS (pain relief)', '15-20 min', 'TENS'), ('IFC / Interferential current', '15-20 min', 'IFC'), ('Therapeutic ultrasound', '5-8 min', 'Ultrasound'),
               ('Hot pack', '15 min', 'Hot pack'), ('Cold pack / cryotherapy', '10-15 min', 'Cold pack'), ('Cervical traction', '10-15 min', 'Traction')],
    'ot': [('Sensory integration therapy', '30 min', 'Sensory integration'), ('Fine motor training', '20 min', 'Fine motor'), ('Handwriting training', '20 min', 'Handwriting'),
           ('ADL training (dressing, feeding, toileting)', '30 min', 'ADL training'), ('Play-based therapy', '30 min', 'Play-based')],
    'speech': [('Articulation therapy', '30 min', 'Articulation'), ('Language stimulation', '30 min', 'Language'), ('Oral-motor exercises', '10 min', 'Oral-motor'),
               ('Voice therapy', '30 min', 'Voice'), ('Fluency shaping', '30 min', 'Fluency')],
    'behaviour': [('Applied behaviour analysis (ABA) session', '60 min', 'ABA session'), ('Social skills training', '30 min', 'Social skills'), ('Positive reinforcement / token system', '20 min', 'Token system'),
                  ('Parent training', '45 min', 'Parent training'), ('Relaxation and self-regulation training', '20 min', 'Self-regulation')],
}
HINTS = {
    'physio': ('electrotherapy, heat / cold, traction, manual therapy...', 'Search treatments (TENS, ultrasound, SWD...) or type your own and press Enter'),
    'ot': ('sensory integration, fine motor, handwriting, daily living...', 'Search treatments (sensory integration, handwriting, ADL...) or type your own and press Enter'),
    'speech': ('articulation, language, voice, fluency, swallowing...', 'Search treatments (articulation, language, voice...) or type your own and press Enter'),
    'behaviour': ('ABA, social skills, reinforcement, parent training...', 'Search treatments (ABA, social skills, token system...) or type your own and press Enter'),
}
MAX_TREATMENTS = 30


def kinds_in(visible):
    """The departments whose treatments to offer, from the visible disciplines (everything when not restricted)."""
    return [d for d in (SPECIFIC if visible is None else visible) if d in LISTS]


def ui_for(visible):
    """The quick buttons and hints of the session form: those of the person's own department; generic when they work across several."""
    kinds = kinds_in(visible)
    if len(kinds) == 1:
        hint, placeholder = HINTS[kinds[0]]
        return {'chips': CHIPS[kinds[0]], 'hint': hint, 'placeholder': placeholder, 'label': LABELS[kinds[0]]}
    return {'chips': [], 'hint': 'treatments of any department', 'placeholder': 'Search treatments or type your own and press Enter', 'label': ''}


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
    """The department's treatments and exercise-library matches for a search text. kind 'clinical' or 'exercise' limits it to one list; `visible` are the
    disciplines the person works in (everything when None), so an occupational therapist is offered occupational therapy treatments, not TENS."""
    q = (query or '').strip().lower()
    if not q:
        return []
    results = []
    if kind != 'exercise':
        kinds = kinds_in(visible)
        for key in kinds:
            results += [{'kind': 'clinical', 'name': name, 'dose': dose, 'group': group if len(kinds) == 1 else f'{LABELS[key]}: {group}'}
                        for group, name, dose in LISTS[key] if q in name.lower() or q in group.lower()][:10]
    if kind != 'clinical' and len(q) >= 2:
        from exercises.models import ExerciseMain
        library = ExerciseMain.objects.filter(exercise_name__icontains=q)
        if visible is not None:  # only the department's own library
            library = library.filter(discipline__in=visible)
        for e in library.order_by('exercise_name')[:10]:
            results.append({'kind': 'exercise', 'name': e.exercise_name, 'dose': e.dose_label, 'group': 'Exercise'})
    return results
