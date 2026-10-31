"""The front desk: where a clinic's staff (manager, receptionist, assistant, other) work after signing in with the login the
owning physiotherapist gave them. Each role sees only what it needs (ClinicMember.PERMISSIONS) and never clinical records."""
import datetime
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.access import first_error
from accounts.appointments import PX_PER_MIN, apply_edit, assign_for_booking, aware, booked_prompt, build_grid, practitioner_options, sync_next_appointment, team_of
from accounts.forms import DURATION_CHOICES, AppointmentForm, RescheduleForm
from accounts.models import Appointment, Patient, Visit
from billing import catalog, exports
from billing import invoice as inv
from billing.forms import EntryPaymentForm, PatientBillForm
from billing.models import ADVANCE, BillingEntry, EntryPayment, PatientAdvance, advance_balance

from .forms import FrontDeskPatientForm
from .models import ClinicMember, QueueEntry
from .schedule import appointments_between, appointments_on, day_context, parse_day

TABS = [('overview', 'Dashboard', 'overview'), ('schedule', 'Schedule', 'schedule'), ('queue', 'Queue', 'queue'), ('patients', 'Patients', 'patients'),
        ('register', 'Register patient', 'register'), ('session', 'Record treatment', 'record_session'), ('billing', 'Billing', 'billing'), ('team', 'Team', 'team')]


def desk_member(request):
    """The signed-in staff member, if they still work at an active clinic; otherwise 404."""
    member = ClinicMember.objects.filter(user=request.user, physio__isnull=True, status=ClinicMember.ACTIVE).select_related('clinic', 'clinic__owner').first()
    if member is None or not member.clinic.is_active:
        raise Http404
    return member


def desk_view(permission=None):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            member = desk_member(request)
            if permission and not member.can(permission):
                raise Http404
            return view(request, member, *args, **kwargs)
        return wrapper
    return decorator


def _back(tab):
    return redirect(f"{reverse('clinics:desk')}?tab={tab}")


def _today():
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime.combine(timezone.localdate(), datetime.time.min), tz)
    return start, start + datetime.timedelta(days=1)


def _usable(request, member):
    if member.clinic.is_usable:
        return True
    messages.info(request, 'The clinic\'s plan is not active yet, so this is paused. Please ask the clinic owner.')
    return False


@desk_view()
def desk(request, member):
    clinic = member.clinic
    tabs = [(key, label) for key, label, perm in TABS if member.can(perm)]
    opens_on = 'overview' if 'overview' in dict(tabs) else 'queue' if 'queue' in dict(tabs) else tabs[0][0]  # the home page, else the queue, else the only tab
    tab = request.GET.get('tab') if request.GET.get('tab') in dict(tabs) else opens_on
    start, end = _today()
    todays = clinic.queue_entries.filter(joined_at__gte=start, joined_at__lt=end).select_related('patient')
    bare = tab == 'schedule' and request.GET.get('bare') == '1'  # the calendar alone, to open in its own browser tab
    context = {'member': member, 'clinic': clinic, 'tabs': tabs, 'tab_keys': [key for key, _ in tabs], 'tab': tab, 'bare': bare, 'usable': clinic.is_usable,
               'can_contact': member.can('contact'), 'can_manage_queue': member.can('queue_manage') and clinic.is_usable,
               'can_register': member.can('register'), 'can_record': member.can('record_session'),
               'billing_url': reverse('billing:billing') if member.can('billing') and clinic.workspace_id else '?tab=billing'}
    if tab == 'overview':
        context.update({
            'patient_total': clinic.patients.count(), 'team_count': clinic.members.filter(status=ClinicMember.ACTIVE).count() + 1,
            'queue_counts': {s: todays.filter(status=s).count() for s in (QueueEntry.WAITING, QueueEntry.CALLED, QueueEntry.COMPLETED)}})
        context.update(_dashboard_context(member, start, end, todays))
    elif tab == 'queue':
        context['entries'] = todays.exclude(status=QueueEntry.CANCELLED)
    elif tab == 'patients':
        q = request.GET.get('q', '').strip()
        patients = clinic.patients.prefetch_related('assigned').order_by('-id')
        if q:
            patients = patients.filter(Q(name__icontains=q) | Q(patient_code__icontains=q) | (Q(phone__icontains=q) if member.can('contact') else Q(pk__in=[])))
        context.update({'patients': patients[:200], 'q': q, 'patient_total': clinic.patients.count(), 'can_assign': member.can('assign') and clinic.is_usable,
                        'assign_team': clinic.members.filter(status=ClinicMember.ACTIVE, role__in=ClinicMember.BOOKABLE_ROLES).select_related('physio__account__profession')})
    elif tab == 'register':
        context['form'] = FrontDeskPatientForm()
    elif tab == 'billing':
        context.update(_billing_context(request, member))
    elif tab == 'schedule':
        context.update(_schedule_context(request, member))
    elif tab == 'session':
        context.update(_session_context(request, member))
    elif tab == 'team':
        context['members'] = clinic.members.filter(status=ClinicMember.ACTIVE).select_related('physio')
    return render(request, 'clinics/desk.html', context)


def _dashboard_context(member, start, end, todays):
    """The front desk's home: today's appointments, the queue, new registrations and (for those who bill) today's money."""
    clinic = member.clinic
    owner = clinic.calendar_owner
    today_appts = list(Appointment.objects.filter(professional=owner, kind=Appointment.APPOINTMENT, start__gte=start, start__lt=end)
                       .exclude(status=Appointment.CANCELLED).select_related('patient', 'department', 'practitioner__physio').order_by('start', 'id'))
    now = timezone.now()
    context = {
        'appt_total': len(today_appts), 'appt_attended': sum(a.status == Appointment.ATTENDED for a in today_appts),
        'appt_waiting': sum(a.status == Appointment.SCHEDULED for a in today_appts),
        'next_up': [a for a in today_appts if a.status == Appointment.SCHEDULED and a.end >= now][:6],
        'registered_today': clinic.patients.filter(created_at__gte=start, created_at__lt=end).count(),
        'queue_now': list(todays.exclude(status__in=[QueueEntry.CANCELLED, QueueEntry.COMPLETED]).select_related('patient')[:6]),
        'can_book': member.can('appointments') and clinic.is_usable,
    }
    if member.can('billing'):
        today = timezone.localdate()
        bills = BillingEntry.objects.filter(patient__clinic=clinic)
        context['billed_today'] = bills.filter(entry_date=today, cancelled_at__isnull=True).aggregate(t=Sum('rate'))['t'] or 0
        got = EntryPayment.objects.filter(entry__patient__clinic=clinic, entry__cancelled_at__isnull=True, paid_on=today).exclude(payment_mode=ADVANCE).aggregate(t=Sum('amount'))['t'] or 0
        got += PatientAdvance.objects.filter(patient__clinic=clinic, paid_on=today, kind__in=[PatientAdvance.DEPOSIT, PatientAdvance.REFUND]).aggregate(t=Sum('amount'))['t'] or 0
        context['received_today'] = got
        context['due_total'] = sum((e.amount_due for e in bills.filter(cancelled_at__isnull=True, amount_paid__lt=F('rate'))[:500]), 0)
    return context


def _schedule_context(request, member):
    """The clinic's appointments for a day. A department's sign-in sees only its own department; a therapy assistant starts with the
    appointments that are with them; everyone else sees the whole clinic and can narrow it to a department."""
    clinic = member.clinic
    day = parse_day(request.GET.get('date'))
    owner = clinic.calendar_owner
    filters = {'professional': owner}
    departments = [] if member.department_id else list(owner.departments.all())
    chosen = ''
    if member.department_id:
        filters['department_id'] = member.department_id
    elif request.GET.get('dept') in {str(d.pk) for d in departments}:
        chosen = request.GET['dept']
        filters['department_id'] = int(chosen)
    mine = member.books_own_schedule and request.GET.get('all') != '1'
    if mine:
        filters['practitioner'] = member
    can_book = member.can('appointments') and clinic.is_usable
    view = request.GET.get('view') if request.GET.get('view') in ('calendar', 'list') else ('calendar' if member.can('appointments') else 'list')
    bare = request.GET.get('bare') == '1'
    days = int(request.GET['days']) if request.GET.get('days') in ('1', '3', '7') else (7 if bare else 3)  # the stand-alone calendar shows the whole week
    keep = (f'&dept={chosen}' if chosen else '') + ('&all=1' if member.books_own_schedule and not mine else '') + ('&bare=1' if bare else '')
    calendar = {}
    if view == 'calendar':
        day_list = [day + datetime.timedelta(days=i) for i in range(days)]
        events = appointments_between(day_list[0], day_list[-1], **filters)
        columns, hours, grid_height, grid_start = build_grid(owner, events, day_list, timezone.localdate(), patient_link=False, with_links=member.can('appointments'))
        calendar = {'columns': columns, 'hours': hours, 'grid_height': grid_height, 'grid_start_min': grid_start, 'px_per_min': PX_PER_MIN,
                    'range_label': f"{day_list[0]:%d %b}" + (f" - {day_list[-1]:%d %b %Y}" if days > 1 else f" {day_list[0]:%Y}"),
                    'prev_start': day - datetime.timedelta(days=days), 'next_start': day + datetime.timedelta(days=days)}
        appointments = [a for a in events if timezone.localtime(a.start).date() == day]
    else:
        appointments = appointments_on(day, **filters)
    return {**day_context(day), **calendar, 'view': view, 'days': days, 'keep': keep,
            'appointments': appointments, 'departments': departments, 'dept': chosen, 'mine': mine,
            'own_department': member.department if member.department_id else None, 'can_book': can_book,
            'prompt': booked_prompt(request, owner) if member.can('appointments') else None,
            'book_departments': list(owner.departments.all()) if can_book else [], 'book_team': [(p['id'], p['name'], p['depts']) for p in practitioner_options(owner)] if can_book else [],
            'session_types': Visit.SESSION_CHOICES, 'durations': DURATION_CHOICES, 'default_minutes': owner.default_session_minutes}


@desk_view('assign')
@require_POST
def patient_assign(request, member, patient_id):
    """Reception chooses which therapists a patient is assigned to; only they (and the clinic owner) can open the patient's record."""
    clinic = member.clinic
    if not _usable(request, member):
        return _back('patients')
    patient = get_object_or_404(clinic.patients, pk=patient_id)
    team = clinic.members.filter(status=ClinicMember.ACTIVE, role__in=ClinicMember.BOOKABLE_ROLES, pk__in=[int(i) for i in request.POST.getlist('members') if i.isdigit()])
    patient.assigned.set(team)
    names = ', '.join(m.display_name for m in team)
    messages.success(request, f'{patient.name} is assigned to {names}.' if names else f'{patient.name} is not assigned to anyone.')
    return _back('patients')


def _appt_back(day, booked=None, kind='booked', bare=False):
    extra = (f'&booked={booked}&kind={kind}' if booked else '') + ('&view=calendar&days=7&bare=1' if bare else '')
    return redirect(f"{reverse('clinics:desk')}?tab=schedule&date={day}{extra}")


def _clinic_appointment(member, pk):
    """A scheduled appointment of this clinic's calendar, else 404."""
    return get_object_or_404(Appointment, pk=pk, professional=member.clinic.calendar_owner, kind=Appointment.APPOINTMENT, status=Appointment.SCHEDULED)


@desk_view('appointments')
@require_POST
def appt_create(request, member):
    """Reception books a clinic patient into the clinic's appointment book (a department and a therapist if wanted)."""
    clinic = member.clinic
    if not _usable(request, member):
        return _appt_back(timezone.localdate(), bare=request.POST.get('bare') == '1')
    owner = clinic.calendar_owner
    form = AppointmentForm(request.POST, profile=owner)
    if not form.is_valid() or form.cleaned_data['patient'].clinic_id != clinic.pk:
        messages.error(request, first_error(form) if form.errors else 'Search and pick one of the clinic\'s patients.')
        return _appt_back(timezone.localdate(), bare=request.POST.get('bare') == '1')
    d = form.cleaned_data
    start = aware(d['date'], d['start_time'])
    appt = Appointment.objects.create(professional=owner, patient=d['patient'], start=start, end=start + datetime.timedelta(minutes=d['duration']),
                                      session_type=d['session_type'], notes=d['notes'], department=d['department'], practitioner=d['practitioner'])
    assign_for_booking(appt)
    sync_next_appointment(d['patient'])
    messages.success(request, f"Appointment booked for {d['patient'].name}.")
    return _appt_back(d['date'], appt.pk, bare=request.POST.get('bare') == '1')


@desk_view('appointments')
@require_POST
def appt_edit(request, member, appt_id):
    appt = _clinic_appointment(member, appt_id)
    form = RescheduleForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return _appt_back(timezone.localtime(appt.start).date(), bare=request.POST.get('bare') == '1')
    dropped = apply_edit(member.clinic.calendar_owner, appt, form.cleaned_data)
    if dropped:
        messages.warning(request, f'{dropped} does not work in that department, so the appointment is not booked with anyone yet.')
    messages.success(request, 'Appointment rescheduled.')
    return _appt_back(form.cleaned_data['date'], appt.pk, 'rescheduled', bare=request.POST.get('bare') == '1')


@desk_view('appointments')
@require_POST
def appt_cancel(request, member, appt_id):
    appt = _clinic_appointment(member, appt_id)
    appt.status = Appointment.CANCELLED
    appt.save(update_fields=['status'])
    sync_next_appointment(appt.patient)
    messages.success(request, 'Appointment cancelled.')
    return _appt_back(timezone.localtime(appt.start).date(), appt.pk, 'cancelled', bare=request.POST.get('bare') == '1')


def billing_owner(clinic):
    """The workspace the clinic's bills are kept in: its own login when it has one, otherwise the owning physiotherapist."""
    return clinic.workspace or clinic.owner


def _billing_context(request, member):
    clinic = member.clinic
    today = timezone.localdate()
    try:
        selected = datetime.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        selected = today
    bills = BillingEntry.objects.filter(patient__clinic=clinic)
    day = list(bills.filter(entry_date=selected).select_related('patient').order_by('-created_at'))
    owed = list(bills.filter(cancelled_at__isnull=True, amount_paid__lt=F('rate')).select_related('patient').order_by('entry_date', 'id')[:60])
    got = EntryPayment.objects.filter(entry__patient__clinic=clinic, entry__cancelled_at__isnull=True, paid_on=selected).exclude(payment_mode=ADVANCE).aggregate(t=Sum('amount'))['t'] or 0
    got += PatientAdvance.objects.filter(patient__clinic=clinic, paid_on=selected, kind__in=[PatientAdvance.DEPOSIT, PatientAdvance.REFUND]).aggregate(t=Sum('amount'))['t'] or 0
    for e in day + owed:  # a ready-made WhatsApp message per bill
        url = request.build_absolute_uri(reverse('billing:invoice-public', args=[inv.invoice_token(e)]))
        e.whatsapp = inv.whatsapp_link(e, e.contact_number or e.patient.phone, url)
        from accounts.messaging import channel_links
        e.links = channel_links(e.contact_number or e.patient.phone, inv.share_message(e, url), e.patient.messaging_app, e.professional.whatsapp_web)
    return {
        'selected': selected, 'today': today, 'prev_date': selected - datetime.timedelta(days=1), 'next_date': selected + datetime.timedelta(days=1),
        'day_bills': day, 'owed': owed, 'billed': sum((e.rate for e in day if not e.is_cancelled), 0), 'received': got,
        'due_total': sum((e.amount_due for e in owed), 0), 'bill_form': PatientBillForm(initial={'entry_date': selected}), 'pay_form': EntryPaymentForm(), 'service_catalog': catalog.catalog_for(billing_owner(clinic)),
        'can_bill': member.clinic.is_usable,
    }


def _session_context(request, member):
    """The assistant's page for recording what was done: the patient, the treatment given, the exercises supervised."""
    clinic = member.clinic
    today = timezone.localdate()
    preset = clinic.patients.filter(pk=request.GET.get('patient') or 0).first()
    mine = (Visit.objects.filter(patient__clinic=clinic, date=today, therapist=member.name, recorded_by_role=member.get_role_display())
            .select_related('patient').prefetch_related('treatments').order_by('-id'))
    return {'today': today, 'preset': {'id': preset.pk, 'name': preset.name, 'code': preset.patient_code} if preset else None, 'my_sessions': list(mine[:30]),
            'session_types': Visit.SESSION_CHOICES}


@desk_view('record_session')
@require_GET
def treatment_search(request, member):
    """Type-ahead for the treatment page: the clinical / electrotherapy list, or the exercise library (?kind=exercise)."""
    from accounts.treatments import search_options
    from assessments import disciplines
    from billing import catalog
    # the exercise libraries of the departments this person works in (every library when none are set)
    kinds = {catalog.kind_of(d.name) for d in member.departments.all()} & set(disciplines.SPECIFIC)
    visible = disciplines.visible_filter(sorted(kinds)) if kinds else None
    return JsonResponse({'results': search_options(request.GET.get('q', ''), request.GET.get('kind', ''), visible)})


@desk_view('record_session')
@require_POST
def session_create(request, member):
    """The therapy assistant records a session: what treatment was given and which exercises were supervised. It becomes a session on the
    patient's record (shown to the physiotherapist with the assistant's name and role) and can finish the patient in today's queue."""
    from accounts.services import record_visit
    from accounts.treatments import parse_treatments
    clinic = member.clinic
    back = redirect(f"{reverse('clinics:desk')}?tab=session")
    patient = clinic.patients.exclude(status=Patient.DISCHARGED).filter(pk=request.POST.get('patient_id') or 0).first()
    if patient is None:
        messages.error(request, 'Search and pick one of the clinic\'s patients.')
        return back
    given = [{**t, 'kind': 'clinical'} for t in parse_treatments(request.POST.get('treatments'))]
    supervised = [{**t, 'kind': 'exercise'} for t in parse_treatments(request.POST.get('exercises'))]
    if not given and not supervised:
        messages.error(request, 'Add the treatment that was given and/or the exercises that were supervised.')
        return redirect(f"{reverse('clinics:desk')}?tab=session&patient={patient.pk}")
    try:
        day = datetime.date.fromisoformat(request.POST.get('date', ''))
    except ValueError:
        day = timezone.localdate()
    if day > timezone.localdate() or day < timezone.localdate() - datetime.timedelta(days=30):
        messages.error(request, 'The date must be today or a day in the last 30 days.')
        return redirect(f"{reverse('clinics:desk')}?tab=session&patient={patient.pk}")
    kind = request.POST.get('session_type')
    kind = kind if kind in dict(Visit.SESSION_CHOICES) else Visit.TREATMENT
    notes = (request.POST.get('notes') or '').strip()[:2000]
    _, used = record_visit(patient, member.name, day, kind, '', notes, given + supervised, recorded_by_role=member.get_role_display())
    if request.POST.get('finish_queue'):
        start, end = _today()
        QueueEntry.objects.filter(clinic=clinic, patient=patient, joined_at__gte=start, joined_at__lt=end,
                                  status__in=[QueueEntry.WAITING, QueueEntry.CALLED]).update(status=QueueEntry.COMPLETED, finished_at=timezone.now())
    messages.success(request, f'Recorded for {patient.name}: {len(given)} treatment{"s" if len(given) != 1 else ""} and {len(supervised)} supervised exercise{"s" if len(supervised) != 1 else ""}.'
                     + (' One package session used.' if used else ''))
    return back


@desk_view('billing')
@require_POST
def bill_create(request, member):
    """Bill a clinic patient at the front desk. The bill is kept in the clinic's own workspace and shows who entered it."""
    clinic = member.clinic
    if not _usable(request, member):
        return _back('billing')
    patient = clinic.patients.filter(pk=request.POST.get('patient_id') or 0).first()
    if patient is None:
        messages.error(request, 'Search and pick one of the clinic\'s patients to bill.')
        return _back('billing')
    form = PatientBillForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return _back('billing')
    entry = form.save(commit=False)
    entry.professional, entry.patient, entry.patient_name, entry.age, entry.sex = billing_owner(clinic), patient, patient.name, patient.age, patient.gender
    entry.contact_number = patient.phone if member.can('contact') else ''
    entry.created_by_name, entry.created_by_role = member.name, member.get_role_display()
    entry.save()
    catalog.save_lines(entry, request.POST.get('lines'))
    form.apply_payment(entry, request.user)
    carried = getattr(form, 'carried', 0)
    messages.success(request, f'Bill {entry.invoice_number} saved for {patient.name}.' + (f' NPR {entry.amount_due:g} is due.' if entry.amount_due else '')
                     + (f' NPR {carried:g} carried over as advance - balance NPR {advance_balance(patient.pk):g}.' if carried else ''))
    return redirect(f"{reverse('clinics:desk')}?tab=billing&date={entry.entry_date.isoformat()}")


@desk_view('billing')
@require_POST
def bill_payment(request, member, entry_id):
    """Receive money for a bill left on credit (or part paid). More than is owed is kept as the patient's advance."""
    entry = get_object_or_404(BillingEntry, pk=entry_id, patient__clinic=member.clinic)
    back = redirect(f"{reverse('clinics:desk')}?tab=billing&date={request.POST.get('date', '')}")
    form = EntryPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return back
    given, mode = form.cleaned_data['amount'], form.cleaned_data['payment_mode']
    if mode == ADVANCE:
        used = entry.use_advance(request.user, limit=given)
        messages.success(request, f'NPR {used:g} taken from the advance for {entry.invoice_number}.') if used else messages.error(request, 'This patient has no advance balance to use.')
        return back
    paid = entry.record_payment(given, mode, form.cleaned_data['notes'], user=request.user)
    if paid is None:
        messages.info(request, 'That bill is already fully paid.')
        return back
    if given > paid.amount:
        entry.carry_over(given - paid.amount, mode, user=request.user)
    messages.success(request, f'NPR {paid.amount:g} received for {entry.invoice_number}.' + (f' NPR {entry.amount_due:g} still due.' if entry.amount_due else ' Fully paid.')
                     + (f' NPR {given - paid.amount:g} extra kept as advance.' if given > paid.amount else ''))
    return back


@desk_view('billing')
def bill_pdf(request, member, entry_id):
    entry = get_object_or_404(BillingEntry, pk=entry_id, patient__clinic=member.clinic)
    response = HttpResponse(inv.build_pdf(entry), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{entry.invoice_number}.pdf"'
    response['Cache-Control'] = 'private, no-store'
    return response


@desk_view('billing')
def bill_export(request, member):
    """Excel of the clinic's bills for the chosen dates (managers and receptionists; phone numbers only where their role may see them)."""
    f = exports.Filters.from_query(request.GET)
    content = exports.build_workbook(exports.clinic_scope(member.clinic, member.can('contact')), f)
    response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="billing_{f.start:%Y%m%d}_{f.end:%Y%m%d}.xlsx"'
    response['Cache-Control'] = 'private, no-store'
    return response


@desk_view('register')
@require_POST
def register_patient(request, member):
    """A walk-in is registered under the clinic (counts toward its monthly cap) and belongs to the owning physiotherapist's team."""
    if not _usable(request, member):
        return _back('overview')
    form = FrontDeskPatientForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return render(request, 'clinics/desk.html', {
            'member': member, 'clinic': member.clinic, 'tab': 'register', 'form': form, 'usable': True, 'can_contact': True, 'can_register': True,
            'tabs': [(key, label) for key, label, perm in TABS if member.can(perm)]})
    patient = form.save(commit=False)
    patient.professional, patient.clinic = member.clinic.owner, member.clinic
    patient.registered_by_name, patient.registered_by_role = member.name, member.get_role_display()
    patient.save()
    messages.success(request, f'{patient.name} registered ({patient.patient_code}). Add them to the queue when they are ready.')
    return _back('queue' if member.can('queue') else 'patients')


@desk_view('queue')
@require_GET
def patient_search(request, member):
    """Type-ahead for the queue: names and IDs only, plus a phone number for roles that may see contact details."""
    q = request.GET.get('q', '').strip()
    patients = member.clinic.patients.exclude(status=Patient.DISCHARGED)
    if q:
        patients = patients.filter(Q(name__icontains=q) | Q(patient_code__icontains=q))
    return JsonResponse({'results': [{'id': p.pk, 'name': p.name, 'code': p.patient_code, 'phone': p.phone if member.can('contact') else '',
                                      'age': p.age, 'gender': p.gender} for p in patients.order_by('name')[:10]]})


@desk_view('queue_manage')
@require_POST
def queue_add(request, member):
    clinic = member.clinic
    if not _usable(request, member):
        return _back('queue')
    patient = clinic.patients.exclude(status=Patient.DISCHARGED).filter(pk=request.POST.get('patient_id') or 0).first()
    if patient is None:
        messages.error(request, 'Search and pick one of the clinic\'s patients to add to the queue.')
        return _back('queue')
    start, end = _today()
    if clinic.queue_entries.filter(patient=patient, joined_at__gte=start, joined_at__lt=end, status__in=[QueueEntry.WAITING, QueueEntry.CALLED]).exists():
        messages.info(request, f'{patient.name} is already in today\'s queue.')
        return _back('queue')
    QueueEntry.objects.create(clinic=clinic, patient=patient)
    messages.success(request, f'{patient.name} added to the queue.')
    return _back('queue')


@desk_view('queue_manage')
@require_POST
def queue_action(request, member, entry_id):
    if not _usable(request, member):
        return _back('queue')
    entry = get_object_or_404(QueueEntry, pk=entry_id, clinic=member.clinic)
    action, now = request.POST.get('action'), timezone.now()
    if action == 'call' and entry.status == QueueEntry.WAITING:
        entry.status, entry.called_at = QueueEntry.CALLED, now
    elif action == 'complete' and entry.status in (QueueEntry.WAITING, QueueEntry.CALLED):
        entry.status, entry.finished_at = QueueEntry.COMPLETED, now
    elif action == 'cancel' and entry.status in (QueueEntry.WAITING, QueueEntry.CALLED) and member.can('register'):
        entry.status, entry.finished_at = QueueEntry.CANCELLED, now
    else:
        messages.error(request, 'That cannot be done to this queue entry.')
        return _back('queue')
    entry.save()
    return _back('queue')
