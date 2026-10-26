from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import own_patient, workspace_context
from accounts.models import Visit
from accounts.services import record_visit

from . import presets
from .clean import TEXT_FIELDS, _json_list, clean_note
from .models import SoapAddendum, SoapNote

VISIT_TYPE = {SoapNote.INITIAL: Visit.INITIAL, SoapNote.FOLLOW_UP: Visit.TREATMENT, SoapNote.REASSESSMENT: Visit.FOLLOW_UP, SoapNote.DISCHARGE: Visit.FOLLOW_UP}


def tab_url(patient):
    return reverse('accounts:patient-detail', args=[patient.pk]) + '?tab=soap'


def _note_for(request, note_id):
    note = get_object_or_404(SoapNote.objects.select_related('patient'), pk=note_id)
    profile, patient = own_patient(request, note.patient_id)  # same access rule as the patient (clinic colleagues included)
    return profile, patient, note


VALUE_FIELDS = list(TEXT_FIELDS) + ['pain_now', 'pain_best', 'pain_worst', 'frequency_per_week', 'duration_weeks', 'icd10_code', 'note_date', 'next_review',
                                    'note_type', 'stage', 'irritability', 'prognosis']


def _values(note, posted):
    """{field: what the form should show}: the posted text when re-showing after an error, else the saved note."""
    if posted is not None:
        return {name: posted.get(name, '') for name in VALUE_FIELDS}
    out = {}
    for name in VALUE_FIELDS:
        value = getattr(note, name)
        out[name] = '' if value is None else (value.isoformat() if hasattr(value, 'isoformat') else value)
    return out


def _form_context(request, profile, patient, note, posted=None, errors=None):
    """Values the form shows: the saved note, or what was just posted, or (new note) hints carried over from the last note."""
    previous = patient.soap_notes.exclude(pk=note.pk).first() if note.pk else patient.soap_notes.first()
    state = {
        'rom': note.rom, 'strength': note.strength, 'tests': note.special_tests, 'measures': note.measures, 'goals': note.goals,
    }
    if not note.pk and previous:  # a follow-up starts from the last note's measures (baseline left empty to enter today's value) and goals
        state['measures'] = [{'name': m['name'], 'unit': m['unit'], 'baseline': '', 'target': m['target']} for m in previous.measures]
        state['goals'] = previous.goals
    if posted is not None:
        state = {'rom': _json_list(posted, 'rom_json'), 'strength': _json_list(posted, 'strength_json'), 'tests': _json_list(posted, 'tests_json'),
                 'measures': _json_list(posted, 'measures_json'), 'goals': _json_list(posted, 'goals_json')}
    from accounts.plans import MEASURE_PRESETS
    context = workspace_context(request.user, profile)
    context.update({
        'active': 'patients', 'patient': patient, 'note': note, 'state': state, 'previous': previous, 'errors': errors or [], 'posted': posted,
        'presets': presets, 'measure_presets': MEASURE_PRESETS, 'today': timezone.localdate().isoformat(),
        'v': _values(note, posted),
        'flags': posted.getlist('red_flags') if posted is not None else note.red_flags,
        'types': SoapNote.TYPE_CHOICES, 'stages': SoapNote.STAGE_CHOICES, 'irritabilities': SoapNote.IRRITABILITY_CHOICES, 'prognoses': SoapNote.PROGNOSIS_CHOICES,
    })
    return context


def _save(request, profile, patient, note):
    """Validate and store the posted form. Returns (saved?, errors)."""
    data, errors = clean_note(request.POST)
    if errors:
        return False, errors
    final = request.POST.get('action') == 'final'
    if final and not any(data[f] for f in ('chief_complaint', 'impression', 'history', 'observation', 'treatment_today')):
        return False, ['A note needs at least a complaint, findings, an impression or the treatment given before it can be finalised.']
    with transaction.atomic():
        for key, value in data.items():
            setattr(note, key, value)
        note.patient = patient
        if not note.pk:
            note.author, note.author_name = profile, profile.full_name
        if final:
            note.status, note.finalized_at = SoapNote.FINAL, timezone.now()
        if request.POST.get('record_visit') and note.visit_id is None:
            summary = (note.treatment_today or note.impression or note.chief_complaint or 'SOAP note recorded')[:300]
            visit, _ = record_visit(patient, profile.full_name, note.note_date, session_type=VISIT_TYPE[note.note_type], notes=f'SOAP note: {summary}', professional=profile)
            note.visit = visit
        note.save()
    patient.touch()
    return True, []


@login_required
def new(request, pk):
    profile, patient = own_patient(request, pk)
    note = SoapNote(patient=patient, note_date=timezone.localdate(),
                    note_type=SoapNote.FOLLOW_UP if patient.soap_notes.exists() else SoapNote.INITIAL,
                    chief_complaint='', icd10_code=patient.icd10_code, impression=patient.diagnosis)
    errors = []
    if request.method == 'POST':
        saved, errors = _save(request, profile, patient, note)
        if saved:
            messages.success(request, 'SOAP note finalised.' if note.is_final else 'Draft saved.')
            return redirect('soapnotes:detail', note_id=note.pk) if note.is_final else redirect('soapnotes:edit', note_id=note.pk)
    return render(request, 'soapnotes/form.html', _form_context(request, profile, patient, note, request.POST if request.method == 'POST' else None, errors))


@login_required
def edit(request, note_id):
    profile, patient, note = _note_for(request, note_id)
    if note.is_final:
        messages.info(request, 'A finalised note is locked. Add an addendum instead.')
        return redirect('soapnotes:detail', note_id=note.pk)
    if note.author_id != profile.pk:
        raise Http404  # only the author edits a draft
    errors = []
    if request.method == 'POST':
        saved, errors = _save(request, profile, patient, note)
        if saved:
            messages.success(request, 'SOAP note finalised.' if note.is_final else 'Draft saved.')
            return redirect('soapnotes:detail', note_id=note.pk) if note.is_final else redirect('soapnotes:edit', note_id=note.pk)
    return render(request, 'soapnotes/form.html', _form_context(request, profile, patient, note, request.POST if request.method == 'POST' else None, errors))


@login_required
def detail(request, note_id):
    profile, patient, note = _note_for(request, note_id)
    context = workspace_context(request.user, profile)
    flag_names = dict(presets.RED_FLAGS)
    context.update({'active': 'patients', 'patient': patient, 'note': note, 'addenda': note.addenda.all(), 'is_author': note.author_id == profile.pk,
                    'flag_labels': [flag_names[k] for k in note.red_flags if k in flag_names], 'tab_url': tab_url(patient)})
    return render(request, 'soapnotes/detail.html', context)


@login_required
@require_POST
def addendum(request, note_id):
    profile, patient, note = _note_for(request, note_id)
    text = request.POST.get('text', '').strip()
    if not note.is_final:
        messages.error(request, 'Addenda can be added to finalised notes; edit the draft instead.')
    elif not text:
        messages.error(request, 'Write the addendum text.')
    else:
        SoapAddendum.objects.create(note=note, text=text[:5000], author_name=profile.full_name)
        messages.success(request, 'Addendum added.')
    return redirect('soapnotes:detail', note_id=note.pk)


@login_required
@require_POST
def delete(request, note_id):
    profile, patient, note = _note_for(request, note_id)
    if note.is_final or note.author_id != profile.pk:
        messages.error(request, 'Only your own drafts can be deleted. A finalised note is part of the record.')
        return redirect('soapnotes:detail', note_id=note.pk)
    note.delete()
    messages.success(request, 'Draft deleted.')
    return redirect(tab_url(patient))
