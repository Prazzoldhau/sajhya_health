import datetime
import mimetypes

from django.contrib.auth import login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from clinics.access import resolve_clinic
from sajhya_health.throttle import too_many

from .access import actor_of, can_see_contact, first_error, own_patient, own_profile, staff_required, workspace_context, workspace_profile
from .services import record_visit
from .forms import SUBTYPES, STEP_FORMS, STEP_TITLES, NextVisitForm, PatientEditForm, PatientForm, PatientNotesForm, PatientPhotoForm, ProfilePictureForm, SignupForm, VisitForm
from .treatments import parse_treatments
from billing.models import advance_balance
from billing.forms import AdvanceForm, BillCorrectionForm, EntryPaymentForm, PackagePaymentForm, PatientBillForm
from .models import Account, Appointment, Icd10Code, Patient, ProfessionalProfile, Visit


def package(request):
    from billing.models import Plan
    return render(request, 'accounts/package.html', {'plans': Plan.objects.all()})


def select_type(request, account_type):
    if account_type == 'clinic':
        return redirect('clinics:register')  # clinics are registered from a professional account
    if account_type not in SUBTYPES:
        return redirect('accounts:package')
    model, _, label = SUBTYPES[account_type]
    return render(request, 'accounts/select_type.html', {
        'account_type': account_type,
        'label': label,
        'options': model.objects.all(),
    })


def signup(request, account_type, subtype_id=None):
    if account_type == 'clinic':
        return redirect('clinics:register')
    subtype = None
    if account_type in SUBTYPES:
        subtype = get_object_or_404(SUBTYPES[account_type][0], pk=subtype_id)
    elif account_type != Account.CLIENT:
        return redirect('accounts:package')
    if request.method == 'POST' and too_many(request, 'signup', 10):
        messages.error(request, 'Too many accounts were created from this connection in the last hour. Please try again later.')
        return redirect(request.path)
    form = SignupForm(request.POST or None, request.FILES or None, account_type=account_type, subtype=subtype)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        if account_type == Account.PROFESSIONAL:
            return redirect('accounts:professional-step', step=2)
        return redirect('accounts:welcome')
    return render(request, 'accounts/signup.html', {
        'form': form, 'account_type': account_type, 'subtype': subtype})


@login_required
def welcome(request):
    """Landing page after sign-in. Approved professionals go straight to the dashboard; everyone else sees where they are
    (unfinished onboarding, under review, or rejected with the reason)."""
    profile = getattr(getattr(request.user, 'account', None), 'profile', None)
    if profile and profile.status == ProfessionalProfile.APPROVED:
        return redirect('accounts:dashboard')
    account = getattr(request.user, 'account', None)
    if profile is None and account is not None and account.account_type == Account.CLIENT:
        return redirect('portal:home')  # every Client account has a patient dashboard (services, and treatment once linked)
    if profile is None and account is not None and account.account_type == Account.STAFF:
        return redirect('clinics:desk')  # clinic staff work from the front desk
    next_step = None
    if profile and profile.status == ProfessionalProfile.DRAFT:
        next_step = min(profile.completed_step + 1, 5)
    elif profile and profile.status == ProfessionalProfile.REJECTED:
        next_step = 2
    return render(request, 'accounts/welcome.html', {'profile': profile, 'next_step': next_step})


@login_required
def professional_step(request, step):
    profile = own_profile(request)
    if profile.status not in (ProfessionalProfile.DRAFT, ProfessionalProfile.REJECTED):
        return redirect('accounts:welcome')
    if step not in STEP_FORMS and step != 5:
        raise Http404
    if step > profile.completed_step + 1:  # no skipping ahead
        return redirect('accounts:professional-step', step=profile.completed_step + 1)

    context = {'profile': profile, 'step': step, 'titles': STEP_TITLES,
               'steps': [(n, STEP_TITLES[n], n <= profile.completed_step) for n in range(1, 6)]}

    if step == 5:
        if request.method == 'POST':
            if profile.completed_step < 4:
                return redirect('accounts:professional-step', step=profile.completed_step + 1)
            profile.status = ProfessionalProfile.SUBMITTED
            profile.submitted_at = timezone.now()
            profile.rejection_reason = ''
            profile.save(update_fields=['status', 'submitted_at', 'rejection_reason'])
            return redirect('accounts:welcome')
        return render(request, 'accounts/professional_review.html', context)

    save_for_later = request.POST.get('action') == 'later'
    form = STEP_FORMS[step](request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST':
        if save_for_later:
            for field in form.fields.values():  # partial progress is allowed
                field.required = False
        if form.is_valid():
            form.save()
            if save_for_later:
                return redirect('accounts:welcome')
            if step > profile.completed_step:
                profile.completed_step = step
                profile.save(update_fields=['completed_step'])
            return redirect('accounts:professional-step', step=step + 1)
    context['form'] = form
    return render(request, 'accounts/professional_step.html', context)


@login_required
def professional_document(request, field, profile_id=None):
    """Credential files are private: only the owner or staff can open them."""
    if field not in ProfessionalProfile.DOCUMENT_FIELDS:
        raise Http404
    if profile_id is not None and request.user.is_staff:
        profile = get_object_or_404(ProfessionalProfile, pk=profile_id)
    else:
        profile = own_profile(request)
    document = getattr(profile, field)
    if not document:
        raise Http404
    content_type = mimetypes.guess_type(document.name)[0] or 'application/octet-stream'
    return FileResponse(document.open('rb'), content_type=content_type)




@staff_required
def review_list(request):
    status = request.GET.get('status', ProfessionalProfile.SUBMITTED)
    profiles = ProfessionalProfile.objects.select_related('account__user', 'account__profession')
    if status != 'all':
        profiles = profiles.filter(status=status)
    return render(request, 'accounts/review_list.html', {
        'profiles': profiles.order_by('submitted_at', 'created_at'),
        'status': status,
        'status_choices': ProfessionalProfile.STATUS_CHOICES,
    })


@staff_required
def review_detail(request, profile_id):
    profile = get_object_or_404(ProfessionalProfile, pk=profile_id)
    if request.method == 'POST':
        decision = request.POST.get('decision')
        reason = request.POST.get('reason', '').strip()
        if decision == 'approve':
            profile.status = ProfessionalProfile.APPROVED
            profile.rejection_reason = ''
        elif decision == 'reject' and reason:
            profile.status = ProfessionalProfile.REJECTED
            profile.rejection_reason = reason
        else:
            messages.error(request, 'Give a reason when rejecting an application.')
            return redirect('accounts:review-detail', profile_id=profile.pk)
        profile.reviewed_at = timezone.now()
        profile.reviewed_by = request.user
        profile.save()
        messages.success(request, f'{profile.full_name}: {profile.get_status_display()}')
        return redirect('accounts:review-list')
    return render(request, 'accounts/review_detail.html', {'profile': profile})


@login_required
def dashboard(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    context = workspace_context(request.user, profile)
    context.update(_dashboard_data(profile))
    context['active'] = 'dashboard'
    return render(request, 'accounts/dashboard.html', context)


def followups_due(patients, today):
    """Active patients not seen for 14 days (or never): the dashboard's Follow-ups Due card and the patient-list filter share this."""
    stale = today - datetime.timedelta(days=14)
    return patients.filter(status=Patient.ACTIVE).filter(Q(last_visit__isnull=True) | Q(last_visit__lte=stale))


def _dashboard_data(profile):
    from billing.views import revenue_for
    today = timezone.localdate()
    patients = profile.workspace_patients()
    day_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
    day_end = day_start + datetime.timedelta(days=1)
    week_end_dt = day_start + datetime.timedelta(days=8)
    live = profile.appointments.filter(kind=Appointment.APPOINTMENT, status=Appointment.SCHEDULED)
    needs_followup = followups_due(patients, today)

    visits = Visit.objects.filter(patient__in=patients)
    window_start = today - datetime.timedelta(days=6)
    prev_start = window_start - datetime.timedelta(days=7)
    visits_week = visits.filter(date__gte=window_start, date__lte=today).count()
    visits_prev = visits.filter(date__gte=prev_start, date__lt=window_start).count()
    per_day = {d: 0 for d in (window_start + datetime.timedelta(days=i) for i in range(7))}
    for d in visits.filter(date__gte=window_start, date__lte=today).values_list('date', flat=True):
        per_day[d] += 1
    peak = max(per_day.values()) or 1
    chart = [{'label': d.strftime('%a'), 'count': n, 'height': max(round(n / peak * 100), 4)} for d, n in per_day.items()]

    change = visits_week - visits_prev
    return {
        'today': today,
        'stats': {
            'total': patients.count(),
            'active': patients.filter(status=Patient.ACTIVE).count(),
            'today_appointments': live.filter(start__gte=day_start, start__lt=day_end).count(),
            'week_appointments': live.filter(start__gte=day_start, start__lt=week_end_dt).count(),
            'followups_due': needs_followup.count(),
            'visits_week': visits_week, 'visits_change': change, 'visits_change_abs': abs(change),
            'revenue_today': revenue_for(profile, today),
        },
        'upcoming': live.filter(start__gte=day_start).select_related('patient').order_by('start')[:5],
        'recent': profile.recent_patients(4),
        'reminders': needs_followup.order_by(F('last_visit').asc(nulls_first=True))[:3],
        'chart': chart,
    }


@login_required
def profile_picture(request):
    profile = own_profile(request)
    form = ProfilePictureForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile photo updated.')
        return redirect('accounts:welcome')
    return render(request, 'accounts/profile_picture.html', {'form': form, 'profile': profile})


AGE_BUCKETS = {'child': (0, 17), 'adult': (18, 40), 'middle': (41, 60), 'senior': (61, 150)}
SORTS = {'recent': '-created_at', 'name': 'name', 'visit': '-last_visit'}


@login_required
def patient_list(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    from billing.models import PatientAllowance
    all_patients = profile.workspace_patients()
    patients = all_patients.select_related('clinic')

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    followup = request.GET.get('followup') == 'due'
    age = request.GET.get('age', '')
    sort = request.GET.get('sort', 'recent')
    if q:
        patients = patients.filter(Q(name__icontains=q) | (Q(phone__icontains=q) & (Q(clinic__isnull=True) | Q(clinic__owner=profile) | Q(clinic__workspace=profile))) | Q(patient_code__icontains=q))
    if status in dict(Patient.STATUS_CHOICES):
        patients = patients.filter(status=status)
    if followup:
        patients = followups_due(patients, timezone.localdate())
    if age in AGE_BUCKETS:
        low, high = AGE_BUCKETS[age]
        today = timezone.localdate()
        # age between low and high  <=>  born after (today - high - 1y) and on/before (today - low y)
        oldest = today.replace(year=today.year - high - 1) if today.month != 2 or today.day != 29 else today.replace(year=today.year - high - 1, day=28)
        youngest = today.replace(year=today.year - low) if today.month != 2 or today.day != 29 else today.replace(year=today.year - low, day=28)
        patients = patients.filter(date_of_birth__gt=oldest, date_of_birth__lte=youngest)
    patients = patients.order_by(SORTS.get(sort, SORTS['recent']), '-id')

    page_obj = Paginator(patients, 10).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    counts = all_patients.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status=Patient.ACTIVE)),
        on_hold=Count('id', filter=Q(status=Patient.ON_HOLD)),
        discharged=Count('id', filter=Q(status=Patient.DISCHARGED)),
    )
    recent = list(profile.recent_patients(5))
    hidden = {p.pk for p in list(page_obj) + recent if not can_see_contact(profile, p)}
    context = workspace_context(request.user, profile)
    context.update({
        'allowance': PatientAllowance.for_profile(profile), 'hidden_contact': hidden, 'active': 'patients', 'page_obj': page_obj, 'counts': counts, 'q': q, 'status': status, 'followup': followup,
        'age': age, 'sort': sort, 'querystring': params.urlencode(),
        'recent_patients': recent,
        'status_choices': Patient.STATUS_CHOICES,
        'form': PatientForm(),
    })
    return render(request, 'accounts/patients.html', context)


@login_required
def patient_add(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    clinic = None
    clinic_id = request.POST.get('clinic') or request.GET.get('clinic')
    own_clinic = profile.clinic_workspace if hasattr(profile, 'clinic_workspace') else None
    if own_clinic is not None:  # signed in as a clinic: every patient is registered under that clinic, and the clinic plan covers them
        clinic_id = own_clinic.pk
    if clinic_id:  # arriving from a clinic page: the clinic is fixed; anything that is not one of my usable clinics is refused
        clinic = resolve_clinic(profile, clinic_id)
        if clinic is None:
            messages.error(request, 'That clinic is not available. Patients can only be added inside a clinic that is active and that you belong to.')
            return redirect('accounts:patients')
    form = PatientForm(request.POST or None, request.FILES or None)
    from billing.models import PatientAllowance
    allowance = PatientAllowance.for_profile(profile)
    if clinic is None and not allowance.can_add:  # the free patients are used up: buy slots first (clinic patients are covered by the clinic plan)
        messages.info(request, f'You have used all {allowance.allowed} patient slots ({allowance.free_limit} free). Buy more to add this patient - NPR {allowance.rate:g} each.')
        return redirect(f"{reverse('accounts:settings')}?tab=plan")
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            if clinic is None:  # re-check under a lock so two quick submissions cannot both take the last slot
                locked = PatientAllowance.objects.select_for_update().get(pk=allowance.pk)
                if not locked.can_add:
                    messages.info(request, 'You have used all your patient slots. Buy more to add this patient.')
                    return redirect(f"{reverse('accounts:settings')}?tab=plan")
            patient = form.save(commit=False)
            patient.professional = profile
            patient.clinic = clinic
            patient.registered_by_name, patient.registered_by_role = actor_of(request.user, profile)
            patient.save()
        messages.success(request, f'{patient.name} added ({patient.patient_code}){f" to {clinic.name}" if clinic else ""}.')
        if clinic and own_clinic is None:  # a clinic's own login stays in its workspace; the owner returns to the clinic page
            return redirect(f"{reverse('clinics:detail', args=[clinic.pk])}?tab=patients")
        return redirect('accounts:patients')
    context = workspace_context(request.user, profile)
    context.update({'active': 'patients', 'form': form, 'clinic': clinic})
    return render(request, 'accounts/patient_add.html', context)


@login_required
def patient_detail(request, pk):
    profile, patient = own_patient(request, pk)
    patient.touch()  # opening a patient puts them at the top of "Recent patients"
    tab = request.GET.get('tab', 'overview')
    if tab not in ('overview', 'plan', 'exercises', 'visits', 'billing', 'profile', 'assessments', 'soap', 'notes', 'documents'):
        tab = 'overview'
    context = workspace_context(request.user, profile)
    context.update({
        'active': 'patients', 'patient': patient, 'tab': tab, 'show_contact': can_see_contact(profile, patient),
        'session_count': patient.visits.count(),
        'recent_visits': patient.visits.prefetch_related('treatments')[:3],
        'visits': patient.visits.prefetch_related('treatments') if tab == 'visits' else None,
        'plans': patient.plans.prefetch_related('phases') if tab == 'plan' else None,
        'prescriptions': patient.prescriptions.prefetch_related('exercises__exercise__step_images', 'exercises__feedback_logs') if tab == 'exercises' else None,
        'bill_entries': patient.billing_entries.all()[:50] if tab == 'billing' else None,
        'packages': patient.packages.prefetch_related('payments') if tab == 'billing' else None,
        'payment_form': PackagePaymentForm(),
        'bill_form': PatientBillForm(initial={'entry_date': timezone.localdate()}) if tab == 'billing' else None,
        'pay_form': EntryPaymentForm() if tab == 'billing' else None,
        'advance_balance': advance_balance(patient.pk) if tab == 'billing' else None,
        'advance_moves': patient.advances.select_related('entry')[:15] if tab == 'billing' else None,
        'advance_form': AdvanceForm() if tab == 'billing' else None,
        'correct_form': BillCorrectionForm() if tab == 'billing' else None,
        'visit_form': VisitForm(initial={'date': timezone.localdate()}),
        'next_form': NextVisitForm(initial={'date': timezone.localdate() + datetime.timedelta(days=7)}),
        'notes_form': PatientNotesForm(instance=patient),
    })
    if tab == 'overview':
        context['portal_link'] = getattr(patient, 'portal_link', None)
        context['portal_invite'] = patient.portal_invites.filter(used_at__isnull=True).first()
        if context['portal_invite'] and not context['portal_invite'].is_open:
            context['portal_invite'] = None
    if tab == 'soap':
        context['soap_notes'] = patient.soap_notes.all()
    if tab == 'assessments':
        from assessments.services import patient_summary
        context['summary'] = patient_summary(patient)
    if tab == 'profile':
        from profiles.views import profile_context
        context.update(profile_context(patient, request.GET.get('section'), request.GET.get('therapy', 'physio')))
    return render(request, 'accounts/patient_detail.html', context)


@login_required
def patient_edit(request, pk):
    profile, patient = own_patient(request, pk)
    form = PatientEditForm(request.POST or None, request.FILES or None, instance=patient)
    show_contact = can_see_contact(profile, patient)
    if not show_contact:
        for name in ('phone', 'email', 'address'):
            del form.fields[name]  # a clinic physio can neither read nor overwrite the patient's contact details
    if request.method == 'POST' and form.is_valid():
        form.save()  # (also removes a replaced picture)
        messages.success(request, 'Patient updated.')
        return redirect('accounts:patient-detail', pk=patient.pk)
    context = workspace_context(request.user, profile)
    context.update({'active': 'patients', 'patient': patient, 'form': form, 'show_contact': show_contact})
    return render(request, 'accounts/patient_edit.html', context)


@login_required
def patient_visit_add(request, pk):
    profile, patient = own_patient(request, pk)
    if request.method == 'POST':
        form = VisitForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            given = parse_treatments(request.POST.get('treatments'))
            _, used = record_visit(patient, profile.full_name, data['date'], data['session_type'], data['progress'], data['notes'], given, professional=profile)
            messages.success(request, 'Session recorded' + (f' with {len(given)} treatment{"s" if len(given) != 1 else ""}.' if given else '.') + (' One package session used.' if used else ''))
        else:
            messages.error(request, 'Could not save the session - check the date and session type.')
    return redirect('accounts:patient-detail', pk=patient.pk)


@login_required
def patient_notes(request, pk):
    profile, patient = own_patient(request, pk)
    if request.method == 'POST':
        form = PatientNotesForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, 'Notes saved.')
    return redirect(f"{reverse('accounts:patient-detail', args=[patient.pk])}?tab=notes")


@login_required
def patient_next_visit(request, pk):
    from .appointments import aware, sync_next_appointment
    profile, patient = own_patient(request, pk)
    if request.method == 'POST':
        form = NextVisitForm(request.POST)
        if form.is_valid():
            start = aware(form.cleaned_data['date'], form.cleaned_data['start_time'])
            Appointment.objects.create(professional=profile, patient=patient, start=start,
                                       end=start + datetime.timedelta(minutes=45), session_type=Visit.FOLLOW_UP)
            sync_next_appointment(patient)
            messages.success(request, 'Next visit booked - it is on your calendar.')
        else:
            messages.error(request, 'Pick a valid date and time.')
    return redirect('accounts:patient-detail', pk=patient.pk)


@login_required
def icd10_search(request):
    """Autocomplete for the diagnosis fields: match a code prefix or any word of the title."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    codes = Icd10Code.objects.filter(code__istartswith=q.replace(' ', ''))[:15]
    results = list(codes)
    if len(results) < 15:
        taken = {c.code for c in results}
        title_q = Q()
        for word in q.split():
            title_q &= Q(title__icontains=word)
        results += [c for c in Icd10Code.objects.filter(title_q)[:30] if c.code not in taken][:15 - len(results)]
    return JsonResponse({'results': [{'code': c.code, 'title': c.title} for c in results]})


@login_required
def patient_photo(request, pk, version=None):
    """Patient pictures are private: only the owning professional can load them."""
    profile, patient = own_patient(request, pk)
    if not patient.photo:
        raise Http404
    response = FileResponse(patient.photo.open('rb'), content_type='image/jpeg')
    response['Cache-Control'] = 'private, max-age=86400'  # the file name in the URL changes whenever the picture does
    return response


@login_required
def patient_photo_update(request, pk):
    profile, patient = own_patient(request, pk)
    if request.method == 'POST':
        form = PatientPhotoForm(request.POST, request.FILES, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile picture removed.' if form.cleaned_data.get('remove') else 'Profile picture updated.')
        else:
            messages.error(request, first_error(form))
    return redirect('accounts:patient-detail', pk=patient.pk)
