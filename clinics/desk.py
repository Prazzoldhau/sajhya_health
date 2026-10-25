"""The front desk: where a clinic's staff (manager, receptionist, assistant, other) work after signing in with the login the
owning physiotherapist gave them. Each role sees only what it needs (ClinicMember.PERMISSIONS) and never clinical records."""
import datetime
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.access import first_error
from accounts.models import Patient

from .forms import FrontDeskPatientForm
from .models import ClinicMember, QueueEntry

TABS = [('overview', 'Overview', 'overview'), ('queue', 'Queue', 'queue'), ('patients', 'Patients', 'patients'),
        ('register', 'Register patient', 'register'), ('team', 'Team', 'team')]


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
    tab = request.GET.get('tab') if request.GET.get('tab') in dict(tabs) else tabs[0][0]
    start, end = _today()
    todays = clinic.queue_entries.filter(joined_at__gte=start, joined_at__lt=end).select_related('patient')
    context = {'member': member, 'clinic': clinic, 'tabs': tabs, 'tab': tab, 'usable': clinic.is_usable,
               'can_contact': member.can('contact'), 'can_manage_queue': member.can('queue_manage') and clinic.is_usable,
               'can_register': member.can('register')}
    if tab == 'overview':
        context.update({
            'patient_total': clinic.patients.count(), 'team_count': clinic.members.filter(status=ClinicMember.ACTIVE).count() + 1,
            'queue_counts': {s: todays.filter(status=s).count() for s in (QueueEntry.WAITING, QueueEntry.CALLED, QueueEntry.COMPLETED)}})
    elif tab == 'queue':
        context['entries'] = todays.exclude(status=QueueEntry.CANCELLED)
    elif tab == 'patients':
        q = request.GET.get('q', '').strip()
        patients = clinic.patients.order_by('-id')
        if q:
            patients = patients.filter(Q(name__icontains=q) | Q(patient_code__icontains=q) | (Q(phone__icontains=q) if member.can('contact') else Q(pk__in=[])))
        context.update({'patients': patients[:200], 'q': q, 'patient_total': clinic.patients.count()})
    elif tab == 'register':
        context['form'] = FrontDeskPatientForm()
    elif tab == 'team':
        context['members'] = clinic.members.filter(status=ClinicMember.ACTIVE).select_related('physio')
    return render(request, 'clinics/desk.html', context)


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
