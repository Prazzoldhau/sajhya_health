import calendar
import datetime
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import AppointmentForm, BlockForm, RescheduleForm, TaskForm
from .models import Appointment, Department, Task, Visit
from .services import record_visit
from .access import can_see_contact, first_error, workspace_context, workspace_profile

PX_PER_MIN = 1.5
DAY_MIN_WIDTH, LANE_MIN_WIDTH = 170, 140  # px: a day is at least this wide, and each appointment at the same time needs this much; wider than the window scrolls sideways
DEFAULT_FIRST_HOUR, DEFAULT_LAST_HOUR = 8, 18
DEPARTMENT_TINTS = 6  # colours the calendar cycles through for departments
TYPE_CLASS = {Visit.INITIAL: 'initial', Visit.TREATMENT: 'treatment', Visit.FOLLOW_UP: 'followup'}


def aware(date, time):
    return timezone.make_aware(datetime.datetime.combine(date, time))


def fmt_time(dt):
    local = timezone.localtime(dt)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def sync_next_appointment(patient):
    """Keep Patient.next_appointment (used by the dashboard and patient page) in step with the calendar."""
    nxt = patient.appointments.filter(
        kind=Appointment.APPOINTMENT, status=Appointment.SCHEDULED, start__gte=timezone.now()
    ).order_by('start').first()
    patient.next_appointment = timezone.localtime(nxt.start).date() if nxt else None
    patient.save(update_fields=['next_appointment'])


KIND_KEY = {'booked': 'appointment_booked', 'rescheduled': 'appointment_rescheduled', 'reminder': 'appointment_reminder', 'cancelled': 'appointment_cancelled'}


def appointment_message(appt, kind='booked'):
    """The WhatsApp text for a patient about this appointment, in the professional's own wording (see Messages)."""
    from . import messaging
    profile = appt.professional
    return messaging.render(messaging.body_for(profile, KIND_KEY.get(kind, 'appointment_booked')), messaging.appointment_values(profile, appt))


def appointment_whatsapp(profile, appt, kind='booked'):
    """wa.me link with the message ready; it opens the patient's own chat when their number is on file and visible to this user."""
    from . import messaging
    phone = appt.patient.phone if can_see_contact(profile, appt.patient) else ''
    return messaging.whatsapp_url(phone, appointment_message(appt, kind), profile.whatsapp_web)


def appointment_links(profile, appt, kind='booked'):
    """Every way to send this appointment message to the patient (their own app first)."""
    from . import messaging
    phone = appt.patient.phone if can_see_contact(profile, appt.patient) else ''
    return messaging.channel_links(phone, appointment_message(appt, kind), appt.patient.messaging_app, profile.whatsapp_web)


def booked_prompt(request, profile):
    """A banner offering the WhatsApp message right after an appointment was booked or moved (?booked=<id>&kind=...)."""
    raw = request.GET.get('booked', '')
    if not raw.isdigit():
        return None
    kind = request.GET.get('kind') if request.GET.get('kind') in ('rescheduled', 'cancelled') else 'booked'
    wanted = Appointment.CANCELLED if kind == 'cancelled' else Appointment.SCHEDULED
    appt = profile.appointments.filter(pk=int(raw), kind=Appointment.APPOINTMENT, status=wanted).select_related('patient', 'professional').first()
    if appt is None or appt.patient is None:
        return None
    return {'name': appt.patient.name, 'kind': kind, 'links': appointment_links(profile, appt, kind), 'url': appointment_links(profile, appt, kind)[0]['url'], 'when': f'{timezone.localtime(appt.start):%a %d %b} at {fmt_time(appt.start)}',
            'has_phone': bool(appt.patient.phone and can_see_contact(profile, appt.patient))}


def _layout_lanes(items):
    """Side-by-side columns for overlapping appointments within one day. Returns how many sit side by side at the busiest moment."""
    items.sort(key=lambda e: e['start_min'])
    group, group_end, lanes = [], -1, []

    def close():
        for e in group:
            e['width'] = round(100 / max(len(lanes), 1), 2)
            e['left'] = round(e['lane'] * e['width'], 2)

    for e in items:
        if e['start_min'] >= group_end and group:
            close()
            group, lanes = [], []
        for i, lane_end in enumerate(lanes):
            if lane_end <= e['start_min']:
                e['lane'], lanes[i] = i, e['end_min']
                break
        else:
            e['lane'] = len(lanes)
            lanes.append(e['end_min'])
        group.append(e)
        group_end = max(group_end, e['end_min'])
    close()
    return max((e['lane'] for e in items), default=-1) + 1


def _task_label(task, today):
    if not task.due:
        return 'No due date'
    local = timezone.localtime(task.due)
    clock = f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"
    if local.date() == today:
        return f'Due today - {clock}'
    return f"Due {local:%b} {local.day} - {clock}"


def build_grid(profile, events, day_list, today, patient_link=True, with_links=True):
    """Place events on a time grid, one column per day. Returns (columns, hours, grid_height, grid_start_min).
    patient_link=False leaves the patient's page link out and with_links=False leaves the message links out (for screens that may not see them)."""
    tints = {d.pk: i % DEPARTMENT_TINTS for i, d in enumerate(profile.departments.all())}
    first_hour, last_hour = DEFAULT_FIRST_HOUR, DEFAULT_LAST_HOUR
    for ev in events:
        first_hour = min(first_hour, timezone.localtime(ev.start).hour)
        last_hour = max(last_hour, min(timezone.localtime(ev.end).hour + 1, 24))
    grid_start_min = first_hour * 60

    columns = []
    for day in day_list:
        items = []
        for ev in events:
            s, e = timezone.localtime(ev.start), timezone.localtime(ev.end)
            if s.date() != day:
                continue
            start_min = s.hour * 60 + s.minute
            end_min = min(e.hour * 60 + e.minute if e.date() == day else 24 * 60, 24 * 60)
            items.append({
                'id': ev.pk, 'kind': ev.kind, 'status': ev.status,
                'title': ev.patient.name if ev.patient else (ev.title or ev.get_kind_display()),
                'time_label': f'{fmt_time(ev.start)} - {fmt_time(ev.end)}',
                'type_label': ev.get_session_type_display() if ev.patient else ev.get_kind_display(),
                'css': TYPE_CLASS.get(ev.session_type, 'treatment') if ev.kind == Appointment.APPOINTMENT else ev.kind,
                'start_min': start_min, 'end_min': max(end_min, start_min + 15),
                'top': round((start_min - grid_start_min) * PX_PER_MIN),
                'height': max(round((end_min - start_min) * PX_PER_MIN), 26),
                'patient_url': reverse('accounts:patient-detail', args=[ev.patient_id]) if ev.patient and patient_link else '',
                'patient_code': ev.patient.patient_code if ev.patient else '',
                'wa': {k: appointment_whatsapp(profile, ev, k) for k in ('booked', 'reminder', 'rescheduled')} if with_links and ev.kind == Appointment.APPOINTMENT and ev.patient and ev.status == Appointment.SCHEDULED else {},
                'links': {k: appointment_links(profile, ev, k) for k in ('booked', 'reminder', 'rescheduled')} if with_links and ev.kind == Appointment.APPOINTMENT and ev.patient and ev.status == Appointment.SCHEDULED else {},
                'notes': ev.notes, 'raw_title': ev.title, 'session_type': ev.session_type,
                'department': ev.department.name if ev.department_id else '', 'department_id': ev.department_id or '',
                'practitioner': ev.practitioner.label if ev.practitioner_id else '', 'practitioner_id': ev.practitioner_id or '',
                'tint': tints.get(ev.department_id, '') if ev.department_id and ev.kind == Appointment.APPOINTMENT else '',
                'date': s.date().isoformat(), 'start_hm': s.strftime('%H:%M'), 'end_hm': e.strftime('%H:%M'),
            })
        side_by_side = _layout_lanes(items)
        for it in items:
            it['links_json'] = json.dumps(it['links'])
        columns.append({
            'date': day, 'iso': day.isoformat(), 'is_today': day == today, 'min_width': max(DAY_MIN_WIDTH, side_by_side * LANE_MIN_WIDTH),
            'label': f"{day:%a}, {ordinal(day.day)} {day:%b}", 'events': items,
        })

    hours = [{'label': f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}", 'top': round((h * 60 - grid_start_min) * PX_PER_MIN)}
             for h in range(first_hour, last_hour)]
    return columns, hours, (last_hour - first_hour) * 60 * PX_PER_MIN, grid_start_min


@login_required
def appointments(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')

    today = timezone.localdate()
    try:
        start_date = datetime.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        start_date = today
    bare = request.GET.get('bare') == '1'  # the appointment book alone, to open in its own browser tab
    days = int(request.GET['days']) if request.GET.get('days') in ('1', '3', '7') else (7 if bare else 3)  # the whole week there
    day_list = [start_date + datetime.timedelta(days=i) for i in range(days)]

    departments = list(profile.departments.all())
    tints = {d.pk: i % DEPARTMENT_TINTS for i, d in enumerate(departments)}
    dept = request.GET.get('dept', '')
    chosen = dept if dept == 'none' or dept in {str(d.pk) for d in departments} else ''  # show one department, or only appointments without one
    shown = profile.appointments.all()
    if chosen == 'none':
        shown = shown.filter(department__isnull=True)
    elif chosen:
        shown = shown.filter(department_id=int(chosen))
    events = list(
        shown.filter(
            start__gte=aware(day_list[0], datetime.time.min),
            start__lt=aware(day_list[-1] + datetime.timedelta(days=1), datetime.time.min),
        ).exclude(status=Appointment.CANCELLED).select_related('patient', 'professional', 'department', 'practitioner__physio'))

    columns, hours, grid_height, grid_start_min = build_grid(profile, events, day_list, today)

    # mini month calendar for the left panel
    month_first = start_date.replace(day=1)
    weeks = [[{'date': d, 'in_month': d.month == month_first.month, 'is_today': d == today,
               'in_range': day_list[0] <= d <= day_list[-1]} for d in week]
             for week in calendar.Calendar(firstweekday=6).monthdatescalendar(month_first.year, month_first.month)]
    prev_month = (month_first - datetime.timedelta(days=1)).replace(day=1)
    next_month = (month_first + datetime.timedelta(days=32)).replace(day=1)

    tasks = list(profile.tasks.all())
    for i, t in enumerate(tasks):
        t.label = _task_label(t, today)
        t.tint = i % 4

    context = workspace_context(request.user, profile)
    context.update({
        'active': 'appointments', 'bare': bare, 'bare_q': '&bare=1' if bare else '', 'base_template': 'accounts/bare_shell.html' if bare else 'accounts/pro_base.html',
        'side_open': not bare and getattr(profile, 'clinic_workspace', None) is None,  # a clinic's own login (reception) gets the whole width
        'columns': columns, 'hours': hours, 'days': days,
        'grid_height': grid_height, 'grid_start_min': grid_start_min,
        'px_per_min': PX_PER_MIN, 'start_date': start_date, 'today': today,
        'prev_date': start_date - datetime.timedelta(days=days),
        'next_date': start_date + datetime.timedelta(days=days),
        'range_label': f"{day_list[0]:%d %b}" + (f" - {day_list[-1]:%d %b %Y}" if days > 1 else f" {day_list[0]:%Y}"),
        'weeks': weeks, 'month_label': f'{month_first:%B %Y}', 'prev_month': prev_month, 'next_month': next_month,
        'departments': [{'id': d.pk, 'name': d.name, 'tint': tints[d.pk]} for d in departments], 'dept': chosen,
        'practitioners': practitioner_options(profile),
        'tasks': tasks, 'open_count': sum(not t.done for t in tasks), 'done_count': sum(t.done for t in tasks),
        'panel': request.GET.get('panel', 'calendar'),
        'appointment_form': AppointmentForm(profile=profile, initial={'date': today, 'duration': profile.default_session_minutes}),
        'block_form': BlockForm(initial={'date': today}, auto_id='blk_%s'),
        'task_form': TaskForm(),
        'prompt': booked_prompt(request, profile), 'open_new': request.GET.get('new') == '1', 'session_choices': Visit.SESSION_CHOICES,
        'duration_default': profile.default_session_minutes,
    })
    return render(request, 'accounts/appointments.html', context)


def team_of(profile):
    """The clinic team an appointment can be booked with (empty for a personal workspace)."""
    from clinics.models import ClinicMember
    clinic = getattr(profile, 'clinic_workspace', None)
    if clinic is None:
        return ClinicMember.objects.none()
    return clinic.members.filter(status=ClinicMember.ACTIVE, role__in=ClinicMember.BOOKABLE_ROLES).select_related('physio__account__profession')


def assign_for_booking(appt):
    """Booking a clinic patient with a team member assigns the patient to them, so they can open the patient's record."""
    who, patient = appt.practitioner, appt.patient
    if who is not None and patient is not None and patient.clinic_id and patient.clinic_id == who.clinic_id:
        patient.assigned.add(who)


def practitioner_options(profile):
    """The clinic team an appointment can be booked with, each with the departments they work in (empty = any), for the booking forms."""
    return [{'id': m.pk, 'name': m.choice_label, 'depts': ','.join(str(d.pk) for d in m.departments.all())} for m in team_of(profile).prefetch_related('departments')]


def apply_edit(profile, appt, d):
    """Move an appointment (or block) and change its details from a validated RescheduleForm; the department and the person it is with
    must belong to this practice, otherwise they are cleared."""
    appt.start, appt.end = aware(d['date'], d['start_time']), aware(d['date'], d['end_time'])
    if appt.kind == Appointment.APPOINTMENT:
        appt.session_type = d['session_type'] or appt.session_type
        appt.notes = d['notes']
        appt.department = profile.departments.filter(pk=int(d['department'])).first() if d['department'].isdigit() else None
        appt.practitioner = team_of(profile).filter(pk=int(d['practitioner'])).first() if d['practitioner'].isdigit() else None
        dropped = None
        if appt.practitioner is not None and not appt.practitioner.works_in(appt.department):
            dropped, appt.practitioner = appt.practitioner.display_name, None  # they do not work in that department
    else:
        appt.title = d['title']
        dropped = None
    appt.save()
    if appt.patient:
        sync_next_appointment(appt.patient)
        assign_for_booking(appt)
    return dropped


def _back(date, days, booked=None, kind='booked', bare=False):
    extra = (f'&booked={booked}&kind={kind}' if booked else '') + ('&bare=1' if bare else '')
    return redirect(f"{reverse('accounts:appointments')}?date={date}&days={days}{extra}")


@login_required
def appointment_create(request):
    profile = workspace_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('accounts:appointments')
    days = request.POST.get('days', 3)
    form = AppointmentForm(request.POST, profile=profile)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return redirect('accounts:appointments')
    d = form.cleaned_data
    start = aware(d['date'], d['start_time'])
    appt = Appointment.objects.create(
        professional=profile, patient=d['patient'], start=start,
        end=start + datetime.timedelta(minutes=d['duration']), session_type=d['session_type'], notes=d['notes'], department=d['department'], practitioner=d['practitioner'])
    assign_for_booking(appt)
    sync_next_appointment(d['patient'])
    messages.success(request, f"Appointment booked for {d['patient'].name}.")
    return _back(d['date'], days, booked=appt.pk, bare=request.POST.get('bare') == '1')


@login_required
def block_create(request):
    profile = workspace_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('accounts:appointments')
    days = request.POST.get('days', 3)
    form = BlockForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return redirect('accounts:appointments')
    d = form.cleaned_data
    Appointment.objects.create(
        professional=profile, kind=d['kind'], title=d['title'],
        start=aware(d['date'], d['start_time']), end=aware(d['date'], d['end_time']))
    messages.success(request, 'Calendar updated.')
    return _back(d['date'], days, bare=request.POST.get('bare') == '1')


@login_required
def appointment_edit(request, pk):
    """Move an appointment (or a block) to another day or time and change its type, label or notes."""
    profile = workspace_profile(request)
    if profile is None:
        raise Http404
    appt = get_object_or_404(Appointment, pk=pk, professional=profile)
    if request.method != 'POST':
        return redirect('accounts:appointments')
    days = request.POST.get('days', 3)
    form = RescheduleForm(request.POST)
    if appt.status != Appointment.SCHEDULED and appt.kind == Appointment.APPOINTMENT:
        messages.error(request, 'Only a scheduled appointment can be changed.')
        return _back(timezone.localtime(appt.start).date(), days, bare=request.POST.get('bare') == '1')
    if not form.is_valid():
        messages.error(request, first_error(form))
        return _back(timezone.localtime(appt.start).date(), days, bare=request.POST.get('bare') == '1')
    d = form.cleaned_data
    dropped = apply_edit(profile, appt, d)
    if dropped:
        messages.warning(request, f'{dropped} does not work in that department, so the appointment is not booked with anyone yet.')
    messages.success(request, 'Appointment rescheduled.' if appt.kind == Appointment.APPOINTMENT else 'Calendar updated.')
    return _back(d['date'], days, booked=appt.pk if appt.kind == Appointment.APPOINTMENT else None, kind='rescheduled', bare=request.POST.get('bare') == '1')


@login_required
def appointment_action(request, pk):
    profile = workspace_profile(request)
    if profile is None:
        raise Http404
    appt = get_object_or_404(Appointment, pk=pk, professional=profile)
    if request.method != 'POST':
        return redirect('accounts:appointments')
    action, local_date = request.POST.get('action'), timezone.localtime(appt.start).date()
    patient = appt.patient
    if action == 'attend' and appt.kind == Appointment.APPOINTMENT and appt.status == Appointment.SCHEDULED:
        appt.status = Appointment.ATTENDED
        appt.save(update_fields=['status'])
        _, used = record_visit(patient, profile.full_name, local_date, appt.session_type, notes=appt.notes)
        messages.success(request, f'Marked as attended - session recorded for {patient.name}.' + (' One package session used.' if used else ''))
    elif action == 'cancel' and appt.kind == Appointment.APPOINTMENT:
        appt.status = Appointment.CANCELLED
        appt.save(update_fields=['status'])
        messages.success(request, 'Appointment cancelled.')
    elif action == 'delete':
        appt.delete()
        messages.success(request, 'Removed from the calendar.')
    if patient:
        sync_next_appointment(patient)
    if action == 'cancel' and appt.kind == Appointment.APPOINTMENT and patient:
        return _back(local_date, request.POST.get('days', 3), booked=appt.pk, kind='cancelled', bare=request.POST.get('bare') == '1')
    return _back(local_date, request.POST.get('days', 3), bare=request.POST.get('bare') == '1')


@login_required
def task_add(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    if request.method == 'POST':
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.professional = profile
            task.save()
    return redirect(f"{reverse('accounts:appointments')}?panel=todo")


@login_required
def task_toggle(request, pk):
    profile = workspace_profile(request)
    task = get_object_or_404(Task, pk=pk, professional=profile) if profile else None
    if task and request.method == 'POST':
        task.done = not task.done
        task.save(update_fields=['done'])
    return redirect(f"{reverse('accounts:appointments')}?panel=todo")


@login_required
def task_delete(request, pk):
    profile = workspace_profile(request)
    task = get_object_or_404(Task, pk=pk, professional=profile) if profile else None
    if task and request.method == 'POST':
        task.delete()
    return redirect(f"{reverse('accounts:appointments')}?panel=todo")


@login_required
def patient_search(request):
    """Type-ahead for the booking form: match name, phone or patient ID."""
    profile = workspace_profile(request)
    if profile is None:
        return JsonResponse({'results': []})
    q = request.GET.get('q', '').strip()
    patients = profile.workspace_patients().exclude(status='discharged').select_related('clinic')
    if q:
        patients = patients.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(patient_code__icontains=q))
    return JsonResponse({'results': [
        {'id': p.pk, 'name': p.name, 'code': p.patient_code, 'phone': p.phone if can_see_contact(profile, p) else '', 'age': p.age, 'gender': p.gender}
        for p in patients.order_by('name')[:10]]})


@login_required
def departments_page(request):
    """The practice's departments (Physical Therapy, Occupational Therapy...): add, remove, or start from the suggested list."""
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    if request.method == 'POST':
        if request.POST.get('action') == 'suggest':
            for name in Department.SUGGESTED:
                Department.objects.get_or_create(professional=profile, name=name)
            messages.success(request, 'Suggested departments added. Remove the ones you do not use.')
        else:
            name = ' '.join(request.POST.get('name', '').split())[:80]
            if not name:
                messages.error(request, 'Type the department name.')
            elif profile.departments.filter(name__iexact=name).exists():
                messages.error(request, f'{name} is already a department.')
            else:
                Department.objects.create(professional=profile, name=name)
                messages.success(request, f'{name} added.')
        return redirect('accounts:departments')
    context = workspace_context(request.user, profile)
    context.update({'active': 'appointments', 'departments': profile.departments.annotate(booked=Count('appointments')), 'suggested': Department.SUGGESTED})
    return render(request, 'accounts/departments.html', context)


@login_required
def department_delete(request, pk):
    profile = workspace_profile(request)
    if profile is None:
        raise Http404
    department = get_object_or_404(Department, pk=pk, professional=profile)
    if request.method == 'POST':
        name = department.name
        department.delete()  # appointments already booked keep their time and patient, they just lose the label
        messages.success(request, f'{name} removed. Its appointments stay on the calendar without a department.')
    return redirect('accounts:departments')
