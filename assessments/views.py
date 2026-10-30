import datetime
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import own_patient, workspace_context

from . import clinical, disciplines
from .models import AssessmentForm, AssessmentResult, AssessmentScale, AssessmentSession, ClinicalForm, ClinicalRecord
from .scoring import fmt, interpret, score_answers


def _tab_url(patient):
    return reverse('accounts:patient-detail', args=[patient.pk]) + '?tab=assessments'


def _context(request, profile, patient, **extra):
    context = workspace_context(request.user, profile)
    context.update({'active': 'patients', 'patient': patient, **extra})
    return context


def _available(profile):
    """The disciplines this person may use that actually have something to assess with (for the switcher)."""
    have = set(AssessmentForm.objects.filter(is_active=True).values_list('discipline', flat=True))
    have |= set(AssessmentScale.objects.filter(is_active=True).values_list('discipline', flat=True))
    have |= set(ClinicalForm.objects.filter(is_active=True).values_list('discipline', flat=True))
    return [d for d in disciplines.allowed(profile) if d in have or d == disciplines.discipline_of(profile)]


@login_required
def choose(request, pk):
    """Step 1: pick a ready-made form (a bundle of scales), a clinical form, or tick individual scales. Only the person's own discipline is offered
    (with a switcher for people who work across disciplines, such as the clinic's own login)."""
    profile, patient = own_patient(request, pk)
    current = disciplines.chosen(profile, request.GET.get('discipline'))
    visible = disciplines.visible_filter([current])
    forms = AssessmentForm.objects.filter(is_active=True, discipline__in=visible).prefetch_related('formscale_set__scale')
    form_cards = [{'form': f, 'scale_ids': ','.join(str(fs.scale_id) for fs in f.formscale_set.all() if fs.scale.is_active),
                   'names': [fs.scale.short_name for fs in f.formscale_set.all() if fs.scale.is_active]} for f in forms]
    groups = OrderedDict()
    labels = dict(AssessmentScale.CATEGORY_CHOICES)
    for scale in AssessmentScale.objects.filter(is_active=True, discipline__in=visible).order_by('category', 'name'):
        groups.setdefault(labels[scale.category], []).append(scale)
    switcher = [(d, disciplines.LABELS[d], d == current) for d in _available(profile)] if len(disciplines.allowed(profile)) > 1 else []
    return render(request, 'assessments/choose.html', _context(request, profile, patient, form_cards=form_cards, groups=groups, current=current,
                                                               current_label=disciplines.LABELS[current], switcher=switcher,
                                                               clinical_forms=ClinicalForm.objects.filter(is_active=True, discipline__in=visible)))


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


def _selected_scales(ids_text, profile):
    ids = [int(x) for x in (ids_text or '').split(',') if x.strip().isdigit()]
    visible = disciplines.visible_filter(disciplines.allowed(profile))  # never another discipline's scales, whatever was posted
    found = {s.pk: s for s in AssessmentScale.objects.filter(pk__in=ids, is_active=True, discipline__in=visible).prefetch_related('items', 'bands')}
    return [found[i] for i in ids if i in found]  # keeps the order the clinician (or the form) chose


@login_required
def fill(request, pk):
    """Step 2: answer the chosen scales on one page; saving creates one session with a result per answered scale."""
    profile, patient = own_patient(request, pk)
    source = request.POST if request.method == 'POST' else request.GET
    scales = _selected_scales(source.get('scales'), profile)
    visible = disciplines.visible_filter(disciplines.allowed(profile))
    form = AssessmentForm.objects.filter(pk=source.get('form'), discipline__in=visible).first() if source.get('form', '').isdigit() else None
    discipline = disciplines.discipline_of(profile) or disciplines.chosen(profile, source.get('discipline'))
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
                    patient=patient, form=form, form_name=form.name if form else '', discipline=discipline, assessed_on=assessed_on,
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
                       scale_ids=','.join(str(s.pk) for s in scales), discipline=discipline,
                       assessed_on=posted.get('assessed_on') or timezone.localdate().isoformat(),
                       assessor=posted.get('assessor', profile.full_name), notes=posted.get('notes', ''), today=timezone.localdate().isoformat())
    return render(request, 'assessments/fill.html', context)


def _own_session(request, session_id):
    session = get_object_or_404(AssessmentSession.objects.select_related('patient'), pk=session_id)
    profile, patient = own_patient(request, session.patient_id)  # 404 for another professional's patient
    if session.discipline not in disciplines.visible_filter(disciplines.allowed(profile)):  # and for another discipline's assessment
        raise Http404
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


# ---------------------------------------------------------------------------
# Clinical forms (history and examination forms such as the paediatric occupational therapy assessment)
# ---------------------------------------------------------------------------

def _clinical_form(profile, form_id):
    return get_object_or_404(ClinicalForm, pk=form_id, is_active=True, discipline__in=disciplines.visible_filter(disciplines.allowed(profile)))


@login_required
def clinical_fill(request, pk, form_id):
    profile, patient = own_patient(request, pk)
    form = _clinical_form(profile, form_id)
    errors, assessed_on = [], timezone.localdate()
    posted = request.POST if request.method == 'POST' else None
    answers = clinical.parse(form.definition, posted) if posted else {}
    if posted:
        try:
            assessed_on = datetime.date.fromisoformat(posted.get('assessed_on', ''))
        except ValueError:
            errors.append('Enter the date of the assessment.')
        else:
            if assessed_on > timezone.localdate():
                errors.append('The assessment date cannot be in the future.')
        if not clinical.has_real_answers(form.definition, answers):
            errors.append('Fill in at least one answer before saving.')
        if not errors:
            record = ClinicalRecord.objects.create(patient=patient, form=form, form_code=form.code, form_name=form.name, form_version=form.version, discipline=form.discipline,
                                                   definition=form.definition, answers=answers, assessed_on=assessed_on, assessor=posted.get('assessor', '').strip()[:200])
            patient.touch()
            messages.success(request, f'{form.name} saved.')
            return redirect('assessments:clinical-detail', record_id=record.pk)
    context = _context(request, profile, patient, form_obj=form, sections=clinical.build(form.definition, answers, patient), errors=errors,
                       assessed_on=posted.get('assessed_on') if posted else assessed_on.isoformat(), assessor=posted.get('assessor', '') if posted else profile.full_name,
                       today=timezone.localdate().isoformat())
    return render(request, 'assessments/clinical_fill.html', context)


def _own_record(request, record_id):
    record = get_object_or_404(ClinicalRecord.objects.select_related('patient'), pk=record_id)
    profile, patient = own_patient(request, record.patient_id)
    if record.discipline not in disciplines.visible_filter(disciplines.allowed(profile)):
        raise Http404
    return profile, patient, record


@login_required
def clinical_detail(request, record_id):
    profile, patient, record = _own_record(request, record_id)
    return render(request, 'assessments/clinical_detail.html', _context(request, profile, patient, record=record, sections=clinical.summary(record.definition, record.answers),
                                                                        discipline_label=disciplines.LABELS.get(record.discipline, '')))


@login_required
@require_POST
def clinical_delete(request, record_id):
    profile, patient, record = _own_record(request, record_id)
    record.delete()
    messages.success(request, 'Assessment removed.')
    return redirect(_tab_url(patient))
