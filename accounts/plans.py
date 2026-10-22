import datetime
import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import (PlanGoal, PlanItem, PlanMeasure, PlanPhase, PlanReading, TreatmentPlan, Visit)
from .access import accessible_patients, own_patient, workspace_context, workspace_profile

SUGGESTIONS = [
    'Passive ROM mobilization (Grade I/II)', 'Active-assisted ROM (AAROM)', 'Soft tissue release',
    'Joint mobilization (Grade III/IV)', 'Manual therapy', 'Cryotherapy', 'Heat therapy', 'IFC / TENS for pain gating',
    'Therapeutic ultrasound', 'Joint stabilization drills', 'Isometric strengthening', 'Progressive eccentric loading',
    'PNF patterns for neuromuscular control', 'Balance and proprioception training', 'Gait training', 'Core stabilization',
    'Taping / bracing', 'Dry needling', 'Postural re-education', 'Functional task training',
    'Pendulum exercises', 'Table slides for flexion', 'Scapular squeezes', 'Wand exercises (flexion/ER)', 'Wall crawls',
    'TheraBand rows', 'TheraBand abduction', 'Sleeper stretch', 'Dumbbell scaption', 'Quadriceps sets', 'Straight leg raises',
    'Heel slides', 'Bridging', 'Cat-camel', 'Pelvic tilts', 'Hamstring stretch', 'Calf raises', 'Sit-to-stand',
    'Single-leg balance', 'Walking program',
]

MEASURE_PRESETS = [
    ('Pain at rest (VAS 0-10)', '/10'), ('Pain on activity (VAS 0-10)', '/10'), ('Range of motion', '°'),
    ('Muscle strength (MMT 0-5)', '/5'), ('Functional score', '%'), ('Walking distance', 'm'),
]


# ---------- helpers ----------

def _plan_for(request, pk):
    profile = workspace_profile(request)
    if profile is None:
        raise Http404
    return profile, get_object_or_404(TreatmentPlan, pk=pk, patient__in=accessible_patients(profile))


def _dec(value):
    try:
        return Decimal(str(value)) if str(value).strip() != '' else None
    except (InvalidOperation, ValueError):
        return None


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _soap_source(patient, requested):
    """The SOAP note a new plan should start from: the one asked for (?from_soap=ID), none (?from_soap=none), or by default
    the latest note that carries baseline metrics or goals (else the latest note)."""
    notes = patient.soap_notes.all()
    if requested == 'none':
        return None
    if str(requested).isdigit():
        return notes.filter(pk=int(requested)).first()
    return next((n for n in notes[:20] if n.measures or n.goals), None) or notes.first()


def _apply_soap(state, note):
    """Pre-fill a new plan from a SOAP note: diagnosis, metrics, goals, frequency/duration, precautions and education."""
    state['diagnosis'] = (note.impression.splitlines()[0][:200] if note.impression else '') or state['diagnosis']
    state['icd10_code'] = note.icd10_code or state['icd10_code']
    state['precautions'], state['education'] = note.precautions, note.education
    if note.measures:
        state['measures'] = [{'id': None, 'name': m['name'], 'unit': m.get('unit', ''), 'baseline': m.get('baseline', ''), 'target': m.get('target', '')} for m in note.measures]
    if note.goals:
        state['goals'] = [{'id': None, 'text': g['text'], 'term': g.get('term', 'short'), 'target_date': g.get('target_date', '')} for g in note.goals]
    phase = state['phases'][0]
    if note.frequency_per_week:
        phase['frequency_per_week'] = note.frequency_per_week
    if note.duration_weeks:
        phase['week_end'] = min(note.duration_weeks, 12)
    if note.stage == 'post_op':
        state['title'] = 'Post-op rehabilitation'
    return state


def _state(plan, patient, soap=None):
    """Everything the builder page needs, as plain JSON."""
    if plan is None:
        state = {
            'id': None, 'title': 'Treatment Plan', 'diagnosis': patient.diagnosis, 'icd10_code': patient.icd10_code,
            'onset_date': '', 'start_date': timezone.localdate().isoformat(), 'precautions': '', 'education': '',
            'goals': [{'id': None, 'text': '', 'term': 'short', 'target_date': ''}],
            'measures': [], 'phases': [{'id': None, 'name': 'Phase 1', 'week_start': 1, 'week_end': 2,
                                        'frequency_per_week': 3, 'frequency_note': 'Clinic', 'goal': '', 'items': []}],
        }
        return _apply_soap(state, soap) if soap else state
    return {
        'id': plan.pk, 'title': plan.title, 'diagnosis': plan.diagnosis, 'icd10_code': plan.icd10_code,
        'onset_date': plan.onset_date.isoformat() if plan.onset_date else '', 'start_date': plan.start_date.isoformat(),
        'precautions': plan.precautions, 'education': plan.education,
        'goals': [{'id': g.pk, 'text': g.text, 'term': g.term,
                   'target_date': g.target_date.isoformat() if g.target_date else ''} for g in plan.goals.all()],
        'measures': [{'id': m.pk, 'name': m.name, 'unit': m.unit,
                      'baseline': '' if m.baseline is None else str(m.baseline),
                      'target': '' if m.target is None else str(m.target)} for m in plan.measures.all()],
        'phases': [{'id': ph.pk, 'name': ph.name, 'week_start': ph.week_start, 'week_end': ph.week_end,
                    'frequency_per_week': ph.frequency_per_week, 'frequency_note': ph.frequency_note, 'goal': ph.goal,
                    'items': [{'kind': i.kind, 'text': i.text, 'dosage': i.dosage} for i in ph.items.all()]}
                   for ph in plan.phases.all()],
    }


def _clean(data):
    """Validate the builder payload. Returns (cleaned, error)."""
    phases = []
    for i, ph in enumerate(data.get('phases') or []):
        name = (ph.get('name') or '').strip()
        if not name:
            return None, f'Phase {i + 1} needs a name.'
        start, end = _int(ph.get('week_start')), _int(ph.get('week_end'))
        if not start or not end or start < 1 or end < start or end > 104:
            return None, f'{name}: enter a valid week range (for example 1 to 2).'
        items = [{'kind': it.get('kind') if it.get('kind') in ('clinic', 'hep') else 'clinic',
                  'text': (it.get('text') or '').strip()[:200], 'dosage': (it.get('dosage') or '').strip()[:100]}
                 for it in ph.get('items') or [] if (it.get('text') or '').strip()]
        phases.append({'id': ph.get('id'), 'name': name[:100], 'week_start': start, 'week_end': end,
                       'freq': max(0, min(_int(ph.get('frequency_per_week'), 0), 14)),
                       'freq_note': (ph.get('frequency_note') or '').strip()[:50],
                       'goal': (ph.get('goal') or '').strip()[:300], 'items': items})
    if not phases:
        return None, 'Add at least one phase to the plan.'
    measures = []
    for m in data.get('measures') or []:
        if (m.get('name') or '').strip():
            measures.append({'id': m.get('id'), 'name': m['name'].strip()[:150], 'unit': (m.get('unit') or '').strip()[:20],
                             'baseline': _dec(m.get('baseline')), 'target': _dec(m.get('target'))})
    goals = []
    for g in data.get('goals') or []:
        if (g.get('text') or '').strip():
            goals.append({'id': g.get('id'), 'text': g['text'].strip()[:300],
                          'term': g.get('term') if g.get('term') in ('short', 'long') else 'short',
                          'target_date': _date(g.get('target_date'))})
    return {'phases': phases, 'measures': measures, 'goals': goals}, None


@transaction.atomic
def _apply(plan, data, cleaned, publish):
    plan.title = (data.get('title') or 'Treatment Plan').strip()[:200]
    plan.diagnosis = (data.get('diagnosis') or '').strip()[:200]
    plan.icd10_code = (data.get('icd10_code') or '').strip()[:20]
    plan.onset_date = _date(data.get('onset_date'))
    plan.start_date = _date(data.get('start_date')) or timezone.localdate()
    plan.precautions = (data.get('precautions') or '').strip()
    plan.education = (data.get('education') or '').strip()
    if publish and plan.status == TreatmentPlan.DRAFT:
        plan.status, plan.published_at = TreatmentPlan.ACTIVE, timezone.now()
    plan.save()

    def sync(related, rows, build):
        keep = []
        for order, row in enumerate(rows):
            obj = related.filter(pk=row['id']).first() if row.get('id') else None
            obj = build(obj, row, order)
            obj.save()
            keep.append(obj.pk)
        related.exclude(pk__in=keep).delete()

    def build_goal(obj, r, order):
        obj = obj or PlanGoal(plan=plan)
        obj.text, obj.term, obj.target_date, obj.order = r['text'], r['term'], r['target_date'], order
        return obj

    def build_measure(obj, r, order):
        obj = obj or PlanMeasure(plan=plan)
        obj.name, obj.unit, obj.baseline, obj.target, obj.order = r['name'], r['unit'], r['baseline'], r['target'], order
        return obj

    def build_phase(obj, r, order):
        obj = obj or PlanPhase(plan=plan)
        obj.name, obj.week_start, obj.week_end = r['name'], r['week_start'], r['week_end']
        obj.frequency_per_week, obj.frequency_note, obj.goal, obj.order = r['freq'], r['freq_note'], r['goal'], order
        return obj

    sync(plan.goals, cleaned['goals'], build_goal)
    sync(plan.measures, cleaned['measures'], build_measure)
    sync(plan.phases, cleaned['phases'], build_phase)
    # items are replaced wholesale
    phases = list(plan.phases.all())
    for phase, row in zip(phases, cleaned['phases']):
        phase.items.all().delete()
        PlanItem.objects.bulk_create([PlanItem(phase=phase, order=i, **it) for i, it in enumerate(row['items'])])
    if plan.status == TreatmentPlan.ACTIVE and not any(p.status == PlanPhase.CURRENT for p in phases):
        first = next((p for p in phases if p.status == PlanPhase.UPCOMING), None)
        if first:
            first.status = PlanPhase.CURRENT
            first.save(update_fields=['status'])


# ---------- builder ----------

@login_required
def plan_builder(request, pk=None, patient_pk=None):
    """New plan (patient_pk) or edit existing (pk)."""
    if pk:
        profile, plan = _plan_for(request, pk)
        patient = plan.patient
    else:
        profile, patient = own_patient(request, patient_pk)
        plan = None
    soap = _soap_source(patient, request.GET.get('from_soap', '')) if plan is None else None
    context = workspace_context(request.user, profile)
    context.update({
        'soap_note': soap, 'active': 'plans', 'patient': patient, 'plan': plan, 'state': _state(plan, patient, soap),
        'suggestions': SUGGESTIONS, 'presets': MEASURE_PRESETS,
        'save_url': reverse('accounts:plan-save', args=[plan.pk]) if plan else reverse('accounts:plan-create', args=[patient.pk]),
    })
    return render(request, 'accounts/plan_builder.html', context)


@login_required
def plan_save(request, pk=None, patient_pk=None):
    if request.method != 'POST':
        raise Http404
    if pk:
        profile, plan = _plan_for(request, pk)
    else:
        profile, patient = own_patient(request, patient_pk)
        plan = TreatmentPlan(patient=patient, professional=profile)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Could not read the form data.'}, status=400)
    cleaned, error = _clean(data)
    if error:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    publish = data.get('action') == 'publish'
    _apply(plan, data, cleaned, publish)
    messages.success(request, 'Plan published.' if publish else 'Draft saved.')
    return JsonResponse({'ok': True, 'redirect': reverse('accounts:plan-detail', args=[plan.pk])})


# ---------- viewing & interacting ----------

@login_required
def plan_detail(request, pk):
    profile, plan = _plan_for(request, pk)
    phases = list(plan.phases.prefetch_related('items'))
    for ph in phases:
        ph.clinic_items = [i for i in ph.items.all() if i.kind == 'clinic']
        ph.hep_items = [i for i in ph.items.all() if i.kind == 'hep']
    planned = sum(ph.frequency_per_week * (ph.week_end - ph.week_start + 1) for ph in phases)
    attended = Visit.objects.filter(patient=plan.patient, date__gte=plan.start_date).count()
    measures = list(plan.measures.prefetch_related('readings'))
    goals = list(plan.goals.all())
    total_weeks, current_week = plan.total_weeks, plan.current_week
    context = workspace_context(request.user, profile)
    context.update({
        'active': 'plans', 'plan': plan, 'patient': plan.patient, 'phases': phases, 'measures': measures, 'goals': goals,
        'planned_sessions': planned, 'attended_sessions': attended,
        'session_pct': min(100, round(attended / planned * 100)) if planned else 0,
        'total_weeks': total_weeks, 'current_week': current_week,
        'week_pct': round(current_week / total_weeks * 100) if total_weeks else 0,
        'goals_done': sum(g.achieved for g in goals), 'today': timezone.localdate(),
        'can_edit': plan.status in (TreatmentPlan.DRAFT, TreatmentPlan.ACTIVE),
    })
    return render(request, 'accounts/plan_detail.html', context)


@login_required
def plan_action(request, pk):
    profile, plan = _plan_for(request, pk)
    if request.method != 'POST':
        return redirect('accounts:plan-detail', pk=plan.pk)
    action = request.POST.get('action')
    back = redirect('accounts:plan-detail', pk=plan.pk)

    if action == 'publish' and plan.status == TreatmentPlan.DRAFT:
        plan.status, plan.published_at = TreatmentPlan.ACTIVE, timezone.now()
        plan.save()
        first = plan.phases.filter(status=PlanPhase.UPCOMING).first()
        if first and not plan.phases.filter(status=PlanPhase.CURRENT).exists():
            first.status = PlanPhase.CURRENT
            first.save(update_fields=['status'])
        messages.success(request, 'Plan published.')
    elif action in ('complete', 'discontinue', 'reopen'):
        plan.status = {'complete': TreatmentPlan.COMPLETED, 'discontinue': TreatmentPlan.DISCONTINUED,
                       'reopen': TreatmentPlan.ACTIVE}[action]
        plan.save()
        messages.success(request, f'Plan marked {plan.get_status_display().lower()}.')
    elif action == 'phase_status':
        phase = get_object_or_404(PlanPhase, pk=_int(request.POST.get('phase')), plan=plan)
        new = request.POST.get('status')
        if new in dict(PlanPhase.STATUS_CHOICES):
            if new == PlanPhase.CURRENT:  # only one phase is in progress at a time
                plan.phases.filter(status=PlanPhase.CURRENT).exclude(pk=phase.pk).update(status=PlanPhase.UPCOMING)
            phase.status = new
            phase.save(update_fields=['status'])
    elif action == 'goal_toggle':
        goal = get_object_or_404(PlanGoal, pk=_int(request.POST.get('goal')), plan=plan)
        goal.achieved = not goal.achieved
        goal.save(update_fields=['achieved'])
    elif action == 'log_reading':
        measure = get_object_or_404(PlanMeasure, pk=_int(request.POST.get('measure')), plan=plan)
        value = _dec(request.POST.get('value'))
        if value is None:
            messages.error(request, 'Enter a numeric value for the reading.')
        else:
            PlanReading.objects.create(measure=measure, value=value, date=_date(request.POST.get('date')) or timezone.localdate(),
                                       note=request.POST.get('note', '')[:200])
            messages.success(request, f'Logged {measure.name}.')
    elif action == 'delete' and plan.status == TreatmentPlan.DRAFT:
        patient_pk = plan.patient_id
        plan.delete()
        messages.success(request, 'Draft deleted.')
        return redirect(f"{reverse('accounts:patient-detail', args=[patient_pk])}?tab=plan")
    return back


@login_required
def plans_list(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    status = request.GET.get('status', '')
    plans = profile.plans.select_related('patient').prefetch_related('phases')
    if status in dict(TreatmentPlan.STATUS_CHOICES):
        plans = plans.filter(status=status)
    context = workspace_context(request.user, profile)
    context.update({'active': 'plans', 'plans': plans, 'status': status, 'status_choices': TreatmentPlan.STATUS_CHOICES})
    return render(request, 'accounts/plans_list.html', context)
