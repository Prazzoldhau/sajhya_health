import datetime
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import own_patient, workspace_context

from .models import AssessmentForm, AssessmentResult, AssessmentScale, AssessmentSession
from .scoring import fmt, interpret, score_answers


def _tab_url(patient):
    return reverse('accounts:patient-detail', args=[patient.pk]) + '?tab=assessments'


def _context(request, profile, patient, **extra):
    context = workspace_context(request.user, profile)
    context.update({'active': 'patients', 'patient': patient, **extra})
    return context


@login_required
def choose(request, pk):
    """Step 1: pick a ready-made form (a bundle of scales) or tick individual scales."""
    profile, patient = own_patient(request, pk)
    forms = AssessmentForm.objects.filter(is_active=True).prefetch_related('formscale_set__scale')
    form_cards = [{'form': f, 'scale_ids': ','.join(str(fs.scale_id) for fs in f.formscale_set.all() if fs.scale.is_active),
                   'names': [fs.scale.short_name for fs in f.formscale_set.all() if fs.scale.is_active]} for f in forms]
    groups = OrderedDict()
    labels = dict(AssessmentScale.CATEGORY_CHOICES)
    for scale in AssessmentScale.objects.filter(is_active=True).order_by('category', 'name'):
        groups.setdefault(labels[scale.category], []).append(scale)
    return render(request, 'assessments/choose.html', _context(request, profile, patient, form_cards=form_cards, groups=groups))


def _blocks(scales, posted=None):
    """Scales with their questions and any already-posted answers, ready for the fill template."""
    posted = posted or {}
    blocks = []
    for scale in scales:
        items = []
        for item in scale.items.all():
            current = posted.get(f'i_{item.pk}', '')
            items.append({'item': item, 'value': current,
                          'options': [{'value': fmt(o['value']), 'label': o['label'], 'checked': current != '' and fmt(o['value']) == fmt_posted(current)} for o in item.options]})
        blocks.append({'scale': scale, 'items': items, 'notes': posted.get(f'n_{scale.pk}', ''), 'max': scale.max_score()})
    return blocks


def fmt_posted(text):
    from decimal import Decimal, InvalidOperation
    try:
        return fmt(Decimal(text))
    except InvalidOperation:
        return text


def _selected_scales(ids_text):
    ids = [int(x) for x in (ids_text or '').split(',') if x.strip().isdigit()]
    found = {s.pk: s for s in AssessmentScale.objects.filter(pk__in=ids, is_active=True).prefetch_related('items', 'bands')}
    return [found[i] for i in ids if i in found]  # keeps the order the clinician (or the form) chose


@login_required
def fill(request, pk):
    """Step 2: answer the chosen scales on one page; saving creates one session with a result per answered scale."""
    profile, patient = own_patient(request, pk)
    source = request.POST if request.method == 'POST' else request.GET
    scales = _selected_scales(source.get('scales'))
    form = AssessmentForm.objects.filter(pk=source.get('form')).first() if source.get('form', '').isdigit() else None
    if not scales:
        messages.error(request, 'Choose at least one scale or form first.')
        return redirect('assessments:choose', pk=patient.pk)

    errors, posted = [], {}
    if request.method == 'POST':
        posted = request.POST
        try:
            assessed_on = datetime.date.fromisoformat(request.POST.get('assessed_on', ''))
        except ValueError:
            assessed_on = None
            errors.append('Enter the date of the assessment.')
        if assessed_on and assessed_on > timezone.localdate():
            errors.append('The assessment date cannot be in the future.')

        scored = []
        for scale in scales:
            raw = {item.pk: request.POST.get(f'i_{item.pk}', '') for item in scale.items.all()}
            result, problems = score_answers(scale, raw)
            errors.extend(problems)
            if result:
                scored.append((scale, result))
        if not scored and not errors:
            errors.append('Answer at least one scale before saving.')

        if not errors:
            with transaction.atomic():
                session = AssessmentSession.objects.create(
                    patient=patient, form=form, form_name=form.name if form else '', assessed_on=assessed_on,
                    assessor=request.POST.get('assessor', '').strip()[:200], notes=request.POST.get('notes', '').strip())
                for scale, result in scored:
                    label, tone = interpret(scale, result['score'])
                    AssessmentResult.objects.create(
                        session=session, scale=scale, scale_code=scale.code, scale_name=scale.name, scale_version=scale.version, unit=scale.unit,
                        higher_is_better=scale.higher_is_better, mcid=scale.mcid, answers=result['answers'], score=result['score'],
                        max_score=result['max_score'], interpretation=label, tone=tone, notes=request.POST.get(f'n_{scale.pk}', '').strip()[:500])
            patient.touch()
            messages.success(request, f'Assessment saved ({len(scored)} scale{"s" if len(scored) != 1 else ""}).')
            return redirect(_tab_url(patient))

    context = _context(request, profile, patient, blocks=_blocks(scales, posted), form_obj=form, errors=errors,
                       scale_ids=','.join(str(s.pk) for s in scales),
                       assessed_on=posted.get('assessed_on') or timezone.localdate().isoformat(),
                       assessor=posted.get('assessor', profile.full_name), notes=posted.get('notes', ''), today=timezone.localdate().isoformat())
    return render(request, 'assessments/fill.html', context)


def _own_session(request, session_id):
    session = get_object_or_404(AssessmentSession.objects.select_related('patient'), pk=session_id)
    profile, patient = own_patient(request, session.patient_id)  # 404 for another professional's patient
    return profile, patient, session


@login_required
def detail(request, session_id):
    profile, patient, session = _own_session(request, session_id)
    return render(request, 'assessments/detail.html', _context(request, profile, patient, session=session, results=session.results.all()))


@login_required
@require_POST
def delete(request, session_id):
    profile, patient, session = _own_session(request, session_id)
    session.delete()
    messages.success(request, 'Assessment removed.')
    return redirect(_tab_url(patient))
