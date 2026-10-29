import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.access import first_error, require_workspace, workspace_context, workspace_profile
from accounts.models import Patient, ProfessionalProfile, Visit

from .access import clinic_allowance, clinic_for_member, clinic_for_owner
from .forms import ClinicForm, ClinicLoginForm, StaffForm, StaffLoginForm
from .login import close_staff_login, set_clinic_login, set_staff_login
from .models import Clinic, ClinicMember, ClinicSubscription, QueueEntry

TABS = [('overview', 'Overview'), ('team', 'Team'), ('patients', 'Patients'), ('queue', 'Queue'), ('settings', 'Clinic details')]
TAB_ICONS = {'overview': '⌂', 'team': '✚', 'patients': '♙', 'queue': '▦', 'settings': '⚙'}


def _back(clinic, tab):
    return redirect(f"{reverse('clinics:detail', args=[clinic.pk])}?tab={tab}")


def _today():
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime.combine(timezone.localdate(), datetime.time.min), tz)
    return start, start + datetime.timedelta(days=1)


# ------------------------------------------------------------------ registration + hub ("Clinic Connect")

def register(request):
    """Where "Register a clinic" buttons point. Registering needs a professional account: sign in, then the form opens."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?next={reverse('clinics:create')}")
    return redirect('clinics:create')


@login_required
def hub(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    own = Clinic.objects.filter(workspace=profile).first()
    if own:  # the clinic's own login has one clinic: go straight to it
        return redirect('clinics:detail', pk=own.pk)
    from billing.models import Plan
    sub = ClinicSubscription.objects.filter(professional=profile).first()
    owned = profile.owned_clinics.annotate(team=Count('members', filter=Q(members__status=ClinicMember.ACTIVE), distinct=True),
                                           patient_count=Count('patients', distinct=True))
    context = workspace_context(request.user, profile)
    context.update({
        'active': 'clinics', 'sub': sub, 'plan': Plan.objects.filter(code='clinic').first(),
        'owned': owned, 'can_create': owned.count() < clinic_allowance(profile),
        'memberships': ClinicMember.objects.filter(physio=profile, status=ClinicMember.ACTIVE, clinic__is_active=True).select_related('clinic', 'clinic__owner').annotate(patient_total=Count('clinic__patients')),
        'past_memberships': ClinicMember.objects.filter(physio=profile, status=ClinicMember.LEFT).select_related('clinic'),
        'invitations': ClinicMember.objects.filter(physio=profile, status=ClinicMember.INVITED).select_related('clinic', 'clinic__owner'),
    })
    return render(request, 'clinics/hub.html', context)


# ------------------------------------------------------------------ clinics

@login_required
def clinic_create(request):
    """Register a clinic: the full profile form. Submitting it also requests the Clinic plan (staff activate it), then the
    owner lands on the clinic dashboard."""
    profile = require_workspace(request)
    if Clinic.objects.filter(workspace=profile).exists():
        return redirect('clinics:hub')
    if profile.owned_clinics.count() >= clinic_allowance(profile):
        messages.info(request, 'You have reached the number of clinics your plan allows. Contact us to add more.')
        return redirect('clinics:hub')
    form = ClinicForm(request.POST or None, request.FILES or None, initial={'name': profile.practice_name, 'phone': profile.practice_phone})
    if request.method == 'POST' and form.is_valid():
        form.instance.owner = profile
        clinic = form.save()
        sub = ClinicSubscription.objects.filter(professional=profile).first()
        if sub is None:
            ClinicSubscription.objects.create(professional=profile, contact_phone=''.join(c for c in clinic.phone if c.isdigit())[:20],
                                              request_note=f'Registered clinic: {clinic.name}')
        elif sub.status in (ClinicSubscription.REJECTED, ClinicSubscription.CANCELLED):
            sub.status, sub.requested_at, sub.staff_note = ClinicSubscription.REQUESTED, timezone.now(), ''
            sub.save()
        if clinic.is_usable:
            messages.success(request, f'{clinic.name} is set up (code {clinic.code}). Now add your team.')
        else:
            messages.success(request, f'{clinic.name} registered (code {clinic.code}). Our team will contact you to activate the Clinic plan; '
                                      'until then you can complete the clinic profile.')
        return _back(clinic, 'overview')
    context = workspace_context(request.user, profile)
    context.update({'active': 'clinics', 'form': form})
    return render(request, 'clinics/create.html', context)


def _detail_context(request, profile, clinic, is_owner, tab, form=None, login_form=None):
    q = request.GET.get('q', '').strip()
    context = workspace_context(request.user, profile)
    tabs = [t for t in TABS if is_owner or t[0] != 'settings']
    others = (Clinic.objects.filter(is_active=True).exclude(pk=clinic.pk)
              .filter(Q(owner=profile) | Q(workspace=profile) | Q(members__physio=profile, members__status=ClinicMember.ACTIVE)).distinct().order_by('name'))
    context.update({'active': 'clinics', 'clinic': clinic, 'is_owner': is_owner, 'tab': tab, 'usable': clinic.is_usable,
                    'tabs': tabs, 'nav_items': [(key, label, TAB_ICONS[key]) for key, label in tabs], 'switch_clinics': others})
    start, end = _today()
    todays = clinic.queue_entries.filter(joined_at__gte=start, joined_at__lt=end).select_related('patient', 'patient__professional')
    if tab == 'overview':
        month_start = timezone.localdate().replace(day=1)
        visits = (Visit.objects.filter(patient__clinic=clinic, date__gte=month_start)
                  .values('therapist').annotate(n=Count('id'), people=Count('patient', distinct=True)).order_by('-n'))
        percent, missing = clinic.completeness()
        from . import usage as usage_helpers
        context['usage'] = usage_helpers.summary(clinic)
        context.update({
            'team_count': clinic.members.filter(status=ClinicMember.ACTIVE).count() + 1,
            'patient_total': clinic.patients.count(), 'month_label': f'{month_start:%B %Y}',
            'queue_counts': {s: todays.filter(status=s).count() for s in (QueueEntry.WAITING, QueueEntry.CALLED, QueueEntry.COMPLETED)},
            'activity': [{'name': v['therapist'] or 'Not recorded', 'visits': v['n'], 'patients': v['people']} for v in visits],
            'month_visits': sum(v['n'] for v in visits), 'percent': percent, 'missing': missing, 'module_rows': clinic.module_rows,
        })
    elif tab == 'team':
        context.update({'members': clinic.members.exclude(status__in=[ClinicMember.LEFT, ClinicMember.DECLINED]).select_related('physio'),
                        'staff_form': StaffForm(), 'past': clinic.members.filter(status__in=[ClinicMember.LEFT, ClinicMember.DECLINED]).select_related('physio')})
    elif tab == 'patients':
        patients = clinic.patients.select_related('professional').order_by('-last_activity', '-id')
        if q:
            patients = patients.filter(Q(name__icontains=q) | Q(patient_code__icontains=q))
        context.update({'patients': patients[:200], 'q': q, 'patient_total': clinic.patients.count()})
    elif tab == 'queue':
        context.update({'entries': todays.exclude(status=QueueEntry.CANCELLED)})
    elif tab == 'settings':
        context.update({'form': form or ClinicForm(instance=clinic),
                        'login_form': login_form or (ClinicLoginForm(clinic=clinic) if clinic.owner_id == profile.pk else None)})
    return context


@login_required
def clinic_detail(request, pk):
    """The clinic dashboard."""
    profile, clinic, is_owner = clinic_for_member(request, pk)
    tab = request.GET.get('tab') if request.GET.get('tab') in dict(TABS) else 'overview'
    if tab == 'settings' and not is_owner:
        tab = 'overview'
    return render(request, 'clinics/detail.html', _detail_context(request, profile, clinic, is_owner, tab))


@login_required
@require_POST
def clinic_update(request, pk):
    profile, clinic = clinic_for_owner(request, pk)
    form = ClinicForm(request.POST, request.FILES, instance=clinic)
    if form.is_valid():
        form.save()
        messages.success(request, 'Clinic details saved.')
        return _back(clinic, 'settings')
    messages.error(request, first_error(form))
    return render(request, 'clinics/detail.html', _detail_context(request, profile, clinic, True, 'settings', form=form))


@login_required
@require_POST
def clinic_login(request, pk):
    """The owner sets (or changes) the username and password the clinic itself signs in with."""
    profile, clinic = clinic_for_owner(request, pk)
    if clinic.owner_id != profile.pk:  # the clinic's own login cannot rename or lock itself out; only the owning physiotherapist can
        raise Http404
    form = ClinicLoginForm(request.POST, clinic=clinic)
    if form.is_valid():
        set_clinic_login(clinic, form.cleaned_data['username'], form.cleaned_data['password1'])
        messages.success(request, f'Clinic login saved. {clinic.name} signs in with the username "{form.cleaned_data["username"]}".')
        return _back(clinic, 'settings')
    return render(request, 'clinics/detail.html', _detail_context(request, profile, clinic, True, 'settings', login_form=form))


@login_required
@require_POST
def staff_login(request, pk, member_id):
    """The owner gives a staff member a sign-in, or changes its username and password."""
    profile, clinic = clinic_for_owner(request, pk)
    if clinic.owner_id != profile.pk:
        raise Http404
    member = get_object_or_404(ClinicMember, pk=member_id, clinic=clinic, physio__isnull=True, status=ClinicMember.ACTIVE)
    form = StaffLoginForm(request.POST, member=member)
    if form.is_valid():
        set_staff_login(member, form.cleaned_data['username'], form.cleaned_data['password1'])
        messages.success(request, f'{member.name} can now sign in with the username "{form.cleaned_data["username"]}" '
                                  f'and sees only what a {member.get_role_display().lower()} needs.')
    else:
        messages.error(request, first_error(form))
    return _back(clinic, 'team')


def _plan_needed(request, clinic):
    """Team and queue work once the Clinic plan is active; until then send the owner back with an explanation."""
    if clinic.is_usable:
        return None
    messages.info(request, 'This unlocks when your Clinic plan is activated. Our team will contact you.')
    return _back(clinic, 'overview')


# ------------------------------------------------------------------ team

@login_required
@require_GET
def physio_search(request):
    """Owner's type-ahead: only physios whose credentials are verified can be found."""
    profile = require_workspace(request)
    clinic = get_object_or_404(Clinic.objects.filter(Q(owner=profile) | Q(workspace=profile)), pk=request.GET.get('clinic', 0))
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    taken = clinic.members.filter(status__in=[ClinicMember.ACTIVE, ClinicMember.INVITED]).values_list('physio_id', flat=True)
    found = (ProfessionalProfile.objects.filter(status=ProfessionalProfile.APPROVED).exclude(pk=profile.pk).exclude(pk__in=[t for t in taken if t])
             .filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(account__user__username__icontains=q) | Q(license_number__icontains=q))
             .select_related('account__user')[:10])
    return JsonResponse({'results': [{'id': p.pk, 'name': p.full_name, 'title': p.title, 'username': p.account.user.username,
                                      'licence': ('...' + p.license_number[-4:]) if p.license_number else ''} for p in found]})


@login_required
@require_POST
def member_invite(request, pk):
    profile, clinic = clinic_for_owner(request, pk)
    if (blocked := _plan_needed(request, clinic)):
        return blocked
    physio = ProfessionalProfile.objects.filter(pk=request.POST.get('physio_id') or 0, status=ProfessionalProfile.APPROVED).exclude(pk=profile.pk).first()
    if physio is None:
        messages.error(request, 'Only physios with verified credentials can be added. Search and pick one from the list.')
        return _back(clinic, 'team')
    member, created = ClinicMember.objects.get_or_create(clinic=clinic, physio=physio, defaults={'role': ClinicMember.PHYSIO, 'status': ClinicMember.INVITED})
    if not created:
        if member.status in (ClinicMember.ACTIVE, ClinicMember.INVITED):
            messages.info(request, f'{physio.full_name} is already {"on the team" if member.status == ClinicMember.ACTIVE else "invited"}.')
            return _back(clinic, 'team')
        member.status = ClinicMember.INVITED
        member.save(update_fields=['status'])
    messages.success(request, f'Invitation sent to {physio.full_name}. They join when they accept it in their Clinic Connect tab.')
    return _back(clinic, 'team')


@login_required
@require_POST
def staff_add(request, pk):
    profile, clinic = clinic_for_owner(request, pk)
    if (blocked := _plan_needed(request, clinic)):
        return blocked
    form = StaffForm(request.POST)
    if form.is_valid():
        member = form.save(commit=False)
        member.clinic, member.status, member.joined_at = clinic, ClinicMember.ACTIVE, timezone.now()
        member.save()
        messages.success(request, f'{member.name} added as {member.get_role_display().lower()}.')
    else:
        messages.error(request, first_error(form))
    return _back(clinic, 'team')


def _release_patients(member):
    """Patients a physio registered inside the clinic belong to the clinic: when they leave or are removed those patients
    pass to the clinic owner, so the leaver no longer has any access to them."""
    if member.physio_id:
        Patient.objects.filter(professional_id=member.physio_id, clinic=member.clinic).update(professional=member.clinic.owner)


@login_required
@require_POST
def member_remove(request, pk, member_id):
    profile, clinic = clinic_for_owner(request, pk)
    member = get_object_or_404(ClinicMember, pk=member_id, clinic=clinic)
    member.status = ClinicMember.LEFT
    member.save(update_fields=['status'])
    _release_patients(member)
    close_staff_login(member)
    messages.success(request, f'{member.display_name} removed from the team.')
    return _back(clinic, 'team')


@login_required
@require_POST
def invitation_respond(request, member_id):
    profile = require_workspace(request)
    member = get_object_or_404(ClinicMember, pk=member_id, physio=profile, status=ClinicMember.INVITED)
    if request.POST.get('action') == 'accept':
        member.status, member.joined_at = ClinicMember.ACTIVE, timezone.now()
        messages.success(request, f'You joined {member.clinic.name}. The clinic can see counts of visits for patients you register under it, never their details.')
    else:
        member.status = ClinicMember.DECLINED
        messages.info(request, 'Invitation declined.')
    member.save(update_fields=['status', 'joined_at'])
    return redirect('clinics:hub')


@login_required
@require_POST
def leave(request, pk):
    profile = require_workspace(request)
    member = get_object_or_404(ClinicMember, clinic_id=pk, physio=profile, status=ClinicMember.ACTIVE)
    member.status = ClinicMember.LEFT
    member.save(update_fields=['status'])
    _release_patients(member)
    messages.success(request, f'You left {member.clinic.name}.')
    return redirect('clinics:hub')


# ------------------------------------------------------------------ queue

@login_required
@require_GET
def patient_search(request, pk):
    """Type-ahead for the queue: the clinic's own patients. Names and IDs only - never contact details."""
    profile, clinic, _ = clinic_for_member(request, pk)
    q = request.GET.get('q', '').strip()
    patients = clinic.patients.exclude(status=Patient.DISCHARGED)
    if q:
        patients = patients.filter(Q(name__icontains=q) | Q(patient_code__icontains=q))
    return JsonResponse({'results': [{'id': p.pk, 'name': p.name, 'code': p.patient_code, 'phone': '', 'age': p.age, 'gender': p.gender} for p in patients.order_by('name')[:10]]})


@login_required
@require_POST
def queue_add(request, pk):
    profile, clinic, _ = clinic_for_member(request, pk)
    if (blocked := _plan_needed(request, clinic)):
        return blocked
    patient = clinic.patients.exclude(status=Patient.DISCHARGED).filter(pk=request.POST.get('patient_id') or 0).first()  # the clinic's patients only
    if patient is None:
        messages.error(request, 'Search and pick one of the clinic\'s patients to add to the queue.')
        return _back(clinic, 'queue')
    start, end = _today()
    if clinic.queue_entries.filter(patient=patient, joined_at__gte=start, joined_at__lt=end, status__in=[QueueEntry.WAITING, QueueEntry.CALLED]).exists():
        messages.info(request, f'{patient.name} is already in today\'s queue.')
        return _back(clinic, 'queue')
    QueueEntry.objects.create(clinic=clinic, patient=patient, added_by=profile)
    messages.success(request, f'{patient.name} added to the queue.')
    return _back(clinic, 'queue')


@login_required
@require_POST
def queue_action(request, pk, entry_id):
    profile, clinic, _ = clinic_for_member(request, pk)
    if (blocked := _plan_needed(request, clinic)):
        return blocked
    entry = get_object_or_404(QueueEntry, pk=entry_id, clinic=clinic)
    action, now = request.POST.get('action'), timezone.now()
    if action == 'call' and entry.status == QueueEntry.WAITING:
        entry.status, entry.called_at = QueueEntry.CALLED, now
    elif action == 'complete' and entry.status in (QueueEntry.WAITING, QueueEntry.CALLED):
        entry.status, entry.finished_at = QueueEntry.COMPLETED, now
    elif action == 'cancel' and entry.status in (QueueEntry.WAITING, QueueEntry.CALLED):
        entry.status, entry.finished_at = QueueEntry.CANCELLED, now
    else:
        messages.error(request, 'That cannot be done to this queue entry.')
        return _back(clinic, 'queue')
    entry.save()
    return _back(clinic, 'queue')
