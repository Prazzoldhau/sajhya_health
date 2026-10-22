"""Turns the posted SOAP form into clean model values (or a list of problems). No database access."""
import datetime
import json
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .models import SoapNote
from .presets import MANUAL_GRADES, RED_FLAGS, SIDES, TEST_RESULTS

TEXT_FIELDS = {  # field -> max length (None = unlimited text)
    'chief_complaint': 250, 'history': None, 'mechanism': 250, 'pain_location': 200, 'pain_character': 150, 'aggravating': 300, 'easing': 300,
    'pattern_24h': 300, 'medical_history': None, 'functional_limits': None, 'patient_goals': None, 'observation': None, 'palpation': None,
    'vitals': 150, 'neuro': None, 'gait_function': None, 'impression': None, 'problem_list': None, 'contributing': None, 'treatment_today': None,
    'hep': None, 'education': None, 'precautions': None, 'referral': 300,
}


def _json_list(post, key):
    try:
        value = json.loads(post.get(key) or '[]')
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _s(value, limit=200):
    return str(value or '').strip()[:limit]


def _num(value):
    text = str(value if value is not None else '').strip()
    if not text:
        return ''
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return format(number.normalize(), 'f') if abs(number) < 100000 else None


def _int(value, low, high):
    text = str(value or '').strip()
    if not text:
        return None, None
    if not text.isdigit() or not low <= int(text) <= high:
        return None, f'must be a whole number from {low} to {high}'
    return int(text), None


def clean_note(post):
    """(values dict for SoapNote, errors list)."""
    errors, data = [], {}
    for field, limit in TEXT_FIELDS.items():
        text = (post.get(field) or '').strip()
        data[field] = text[:limit] if limit else text[:20000]
    data['icd10_code'] = _s(post.get('icd10_code'), 20).upper()

    for field, label in (('pain_now', 'Pain now'), ('pain_best', 'Best pain'), ('pain_worst', 'Worst pain')):
        value, problem = _int(post.get(field), 0, 10)
        data[field] = value
        if problem:
            errors.append(f'{label} {problem}.')
    for field, label, high in (('frequency_per_week', 'Treatment frequency', 14), ('duration_weeks', 'Treatment duration (weeks)', 104)):
        value, problem = _int(post.get(field), 0, high)
        data[field] = value or None
        if problem:
            errors.append(f'{label} {problem}.')

    for field, choices, label in (('stage', SoapNote.STAGE_CHOICES, 'stage'), ('irritability', SoapNote.IRRITABILITY_CHOICES, 'irritability'),
                                  ('prognosis', SoapNote.PROGNOSIS_CHOICES, 'prognosis')):
        value = post.get(field, '')
        data[field] = value if value in dict(choices) else ''
    data['note_type'] = post.get('note_type') if post.get('note_type') in dict(SoapNote.TYPE_CHOICES) else SoapNote.FOLLOW_UP

    try:
        data['note_date'] = datetime.date.fromisoformat(post.get('note_date', ''))
    except ValueError:
        data['note_date'] = None
        errors.append('Enter the date of the note.')
    if data['note_date'] and data['note_date'] > timezone.localdate():
        errors.append('The date of the note cannot be in the future.')
    review = post.get('next_review', '')
    try:
        data['next_review'] = datetime.date.fromisoformat(review) if review else None
    except ValueError:
        data['next_review'] = None
        errors.append('The next review date is not valid.')

    known = {key for key, _ in RED_FLAGS}
    data['red_flags'] = [k for k in post.getlist('red_flags') if k in known]

    data['rom'] = [{'movement': _s(r.get('movement'), 80), 'side': _s(r.get('side'), 10) if _s(r.get('side'), 10) in SIDES else '',
                    'active': _s(r.get('active'), 20), 'passive': _s(r.get('passive'), 20), 'pain': bool(r.get('pain')), 'note': _s(r.get('note'), 150)}
                   for r in _json_list(post, 'rom_json') if isinstance(r, dict) and _s(r.get('movement'), 80)][:40]
    data['strength'] = [{'muscle': _s(r.get('muscle'), 80), 'side': _s(r.get('side'), 10) if _s(r.get('side'), 10) in SIDES else '',
                         'grade': _s(r.get('grade'), 3) if _s(r.get('grade'), 3) in MANUAL_GRADES else ''}
                        for r in _json_list(post, 'strength_json') if isinstance(r, dict) and _s(r.get('muscle'), 80)][:40]
    data['special_tests'] = [{'name': _s(r.get('name'), 80), 'result': _s(r.get('result'), 15) if _s(r.get('result'), 15) in TEST_RESULTS else '', 'note': _s(r.get('note'), 150)}
                             for r in _json_list(post, 'tests_json') if isinstance(r, dict) and _s(r.get('name'), 80)][:40]

    measures = []
    for row in _json_list(post, 'measures_json'):
        if not isinstance(row, dict) or not _s(row.get('name'), 150):
            continue
        baseline, target = _num(row.get('baseline')), _num(row.get('target'))
        if baseline is None or target is None:
            errors.append(f'"{_s(row.get("name"), 60)}": baseline and target must be numbers.')
            continue
        measures.append({'name': _s(row.get('name'), 150), 'unit': _s(row.get('unit'), 20), 'baseline': baseline, 'target': target})
    data['measures'] = measures[:30]

    goals = []
    for row in _json_list(post, 'goals_json'):
        if not isinstance(row, dict) or not _s(row.get('text'), 300):
            continue
        when = _s(row.get('target_date'), 10)
        try:
            when = datetime.date.fromisoformat(when).isoformat() if when else ''
        except ValueError:
            errors.append(f'Goal "{_s(row.get("text"), 40)}": the target date is not valid.')
            when = ''
        goals.append({'text': _s(row.get('text'), 300), 'term': 'long' if row.get('term') == 'long' else 'short', 'target_date': when})
    data['goals'] = goals[:30]
    return data, errors
