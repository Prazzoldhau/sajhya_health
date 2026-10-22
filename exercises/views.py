import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.access import accessible_patients, own_patient, require_workspace, workspace_context

from .models import DifficultyLevel, ExerciseMain, ExerciseStepImage, Prescription, PrescriptionExercise, Region, SubRegion

PAGE_SIZE = 24


def _exercise_json(e, detail=False):
    data = {
        'id': e.pk, 'name': e.exercise_name, 'type': e.exercise_type, 'level': e.difficulty_level,
        'level_label': e.get_difficulty_level_display(), 'sets': e.default_sets, 'reps': e.default_reps,
        'hold': e.hold_time_sec, 'rest': e.default_rest_time_sec, 'dose': e.dose_label, 'cover': e.cover,
    }
    if detail:
        data.update({
            'region': e.sub_region_fk.region_fk.label, 'sub_region': e.sub_region_fk.sub_region_name,
            'description': e.exercise_description, 'description_ne': e.exercise_description_nepali,
            'images': e.images, 'youtube_url': e.youtube_url, 'video_url': e.hosted_video_url,
            'step_labels': [s.label for s in e.step_images.all()],
        })
    return data


@login_required
def library(request):
    profile = require_workspace(request)

    sub_id, region_id = request.GET.get('sub', ''), request.GET.get('region', '')
    q, ex_type, level = request.GET.get('q', '').strip(), request.GET.get('type', ''), request.GET.get('level', '')

    exercises = ExerciseMain.objects.select_related('sub_region_fk__region_fk').prefetch_related(
        Prefetch('step_images', queryset=ExerciseStepImage.objects.order_by('order')))
    if sub_id.isdigit():
        exercises = exercises.filter(sub_region_fk_id=sub_id)
    elif region_id.isdigit():
        exercises = exercises.filter(sub_region_fk__region_fk_id=region_id)
    if q:
        exercises = exercises.filter(Q(exercise_name__icontains=q) | Q(exercise_type__icontains=q) | Q(exercise_description__icontains=q))
    if ex_type:
        exercises = exercises.filter(exercise_type=ex_type)
    if level.isdigit():
        exercises = exercises.filter(difficulty_level=level)

    page = Paginator(exercises.order_by('exercise_name'), PAGE_SIZE).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)

    regions = list(Region.objects.prefetch_related(
        Prefetch('subregions', queryset=SubRegion.objects.annotate(n=Count('exercises')).order_by('sub_region_name'))))

    patient = prescription = None
    if request.GET.get('patient', '').isdigit():
        _, patient = own_patient(request, request.GET['patient'])
        if request.GET.get('prescription', '').isdigit():
            prescription = Prescription.objects.filter(pk=request.GET['prescription'], patient=patient,
                                                       status=Prescription.ACTIVE).first()

    context = workspace_context(request.user, profile)
    context.update({
        'active': 'exercises', 'page_obj': page, 'regions': regions, 'total': ExerciseMain.objects.count(),
        'sub': sub_id, 'region': region_id, 'q': q, 'type': ex_type, 'level': level, 'querystring': params.urlencode(),
        'types': ExerciseMain.objects.order_by('exercise_type').values_list('exercise_type', flat=True).distinct(),
        'levels': DifficultyLevel.choices,
        'patient': patient, 'prescription': prescription,
        'patient_json': {'id': patient.pk, 'name': patient.name, 'code': patient.patient_code,
                         'condition': patient.diagnosis} if patient else None,
        'prescription_json': {'id': prescription.pk, 'label': prescription.condition_label} if prescription else None,
    })
    return render(request, 'exercises/library.html', context)


@login_required
def exercise_detail(request, pk):
    require_workspace(request)
    e = get_object_or_404(ExerciseMain.objects.select_related('sub_region_fk__region_fk'), pk=pk)
    return JsonResponse(_exercise_json(e, detail=True))


@login_required
def exercise_search(request):
    """Type-ahead used by the treatment plan builder's home-exercise rows."""
    require_workspace(request)
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    found = ExerciseMain.objects.filter(exercise_name__icontains=q).prefetch_related('step_images').order_by('exercise_name')[:12]
    return JsonResponse({'results': [{'id': e.pk, 'name': e.exercise_name, 'dose': e.dose_label, 'cover': e.cover} for e in found]})


def _add_exercises(prescription, rows, start_order):
    created = 0
    for offset, row in enumerate(rows):
        exercise = ExerciseMain.objects.filter(pk=row.get('id')).first()
        if exercise is None:
            continue

        def num(key, default, low=0, high=999):
            try:
                return max(low, min(int(row.get(key, default)), high))
            except (TypeError, ValueError):
                return default
        PrescriptionExercise.objects.create(
            prescription=prescription, exercise=exercise, exercise_name=exercise.exercise_name,
            difficulty_level=exercise.difficulty_level, order=start_order + offset,
            sets=num('sets', exercise.default_sets, 1, 50), reps=num('reps', exercise.default_reps, 1, 500),
            hold_time_sec=num('hold', exercise.hold_time_sec, 0, 600), rest_time_sec=num('rest', exercise.default_rest_time_sec, 0, 600),
            schedule_morning=bool(row.get('morning', True)), schedule_day=bool(row.get('day', False)),
            schedule_evening=bool(row.get('evening', False)))
        created += 1
    return created


@login_required
@transaction.atomic
def prescribe(request):
    if request.method != 'POST':
        raise Http404
    profile = require_workspace(request)
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Could not read the request.'}, status=400)
    patient = accessible_patients(profile).filter(pk=data.get('patient_id') or 0).first()
    if patient is None:
        return JsonResponse({'ok': False, 'error': 'Choose a patient first.'}, status=400)
    rows = data.get('exercises') or []
    if not rows:
        return JsonResponse({'ok': False, 'error': 'Select at least one exercise.'}, status=400)

    existing = set(ExerciseMain.objects.filter(pk__in=[r.get('id') for r in rows if str(r.get('id', '')).isdigit()]).values_list('pk', flat=True))
    rows = [r for r in rows if str(r.get('id', '')).isdigit() and int(r['id']) in existing]
    if not rows:  # checked before anything is created, so a bad request never supersedes the patient's current prescription
        return JsonResponse({'ok': False, 'error': 'None of the selected exercises exist any more.'}, status=400)

    prescription = None
    if data.get('prescription_id'):
        prescription = Prescription.objects.filter(pk=data['prescription_id'], patient=patient, status=Prescription.ACTIVE).first()
    if prescription:
        start = (prescription.exercises.aggregate(m=Max('order'))['m'] or -1) + 1
    else:
        prescription = Prescription.objects.create(patient=patient, professional=profile,
                                                   condition_label=(data.get('condition_label') or '').strip()[:100])
        start = 0
    count = _add_exercises(prescription, rows, start)
    messages.success(request, f'Prescribed {count} exercise{"s" if count != 1 else ""} to {patient.name}.')
    return JsonResponse({'ok': True, 'redirect': f"{reverse('accounts:patient-detail', args=[patient.pk])}?tab=exercises"})


@login_required
@transaction.atomic
def prescription_action(request, pk):
    profile = require_workspace(request)
    prescription = get_object_or_404(Prescription, pk=pk, patient__in=accessible_patients(profile))
    back = redirect(f"{reverse('accounts:patient-detail', args=[prescription.patient_id])}?tab=exercises")
    if request.method != 'POST':
        return back
    action = request.POST.get('action')

    if action in ('complete', 'cancel', 'reopen'):
        prescription.status = {'complete': Prescription.COMPLETED, 'cancel': Prescription.CANCELLED, 'reopen': Prescription.ACTIVE}[action]
        prescription.save()
        messages.success(request, f'Prescription marked {prescription.get_status_display().lower()}.')
    elif action == 'toggle':
        item = get_object_or_404(PrescriptionExercise, pk=request.POST.get('item'), prescription=prescription)
        item.is_completed = not item.is_completed
        item.completed_at = timezone.now() if item.is_completed else None
        item.save(update_fields=['is_completed', 'completed_at'])
    elif action == 'remove':
        get_object_or_404(PrescriptionExercise, pk=request.POST.get('item'), prescription=prescription).delete()
    elif action == 'reassign':
        copy = Prescription.objects.create(patient=prescription.patient, professional=profile,
                                           condition_label=prescription.condition_label)
        for item in prescription.exercises.all():
            PrescriptionExercise.objects.create(
                prescription=copy, exercise=item.exercise, exercise_name=item.exercise_name,
                difficulty_level=item.difficulty_level, sets=item.sets, reps=item.reps, hold_time_sec=item.hold_time_sec,
                rest_time_sec=item.rest_time_sec, order=item.order, schedule_morning=item.schedule_morning,
                schedule_day=item.schedule_day, schedule_evening=item.schedule_evening)
        messages.success(request, 'Prescription re-assigned as a fresh copy.')
    return back
