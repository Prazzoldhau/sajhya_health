import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.access import can_see_contact, first_error, own_patient, require_workspace, workspace_context, workspace_profile

from .forms import BillingEntryForm, PackagePaymentForm, PatientBillForm, PatientPackageForm
from .models import BillingEntry, PackagePayment, PatientPackage


def revenue_for(profile, date):
    """Money taken on one day: billing-book entries plus package payments recorded that day."""
    start = timezone.make_aware(datetime.datetime.combine(date, datetime.time.min))
    end = start + datetime.timedelta(days=1)
    entries = profile.billing_entries.filter(entry_date=date).aggregate(t=Sum('rate'))['t'] or 0
    packages = PackagePayment.objects.filter(package__professional=profile, created_at__gte=start, created_at__lt=end).aggregate(t=Sum('amount'))['t'] or 0
    return entries + packages


def _selected_date(request):
    try:
        return datetime.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        return timezone.localdate()


def _back(date):
    return redirect(f"{reverse('billing:billing')}?date={date.isoformat()}")


# ---------------------------------------------------------------------------
# Daily billing book
# ---------------------------------------------------------------------------

@login_required
def billing(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    today = timezone.localdate()
    selected = _selected_date(request)

    form = BillingEntryForm(profile=profile, initial={'entry_date': selected})
    entries = profile.billing_entries.filter(entry_date=selected).select_related('patient')
    mode_names = dict(BillingEntry._meta.get_field('payment_mode').choices)
    by_mode = {m: 0 for m in mode_names}
    total = 0
    for e in entries:
        by_mode[e.payment_mode] += e.rate
        total += e.rate
    month_total = profile.billing_entries.filter(entry_date__year=selected.year, entry_date__month=selected.month).aggregate(t=Sum('rate'))['t'] or 0
    packages_due = sum((p.amount_due for p in PatientPackage.objects.filter(professional=profile).exclude(status='cancelled')), 0)

    context = workspace_context(request.user, profile)
    context.update({
        'active': 'billing', 'billing_tab': 'book', 'form': form, 'entries': entries, 'selected': selected, 'today': today,
        'prev_date': selected - datetime.timedelta(days=1), 'next_date': selected + datetime.timedelta(days=1),
        'total': total, 'by_mode': [(mode_names[m], v) for m, v in by_mode.items()],
        'month_total': month_total, 'month_label': f'{selected:%B %Y}', 'package_payments': revenue_for(profile, selected) - total,
        'packages_due': packages_due, 'open_new': request.GET.get('new') == '1',
    })
    return render(request, 'billing/billing.html', context)


@login_required
def entry_save(request, pk=None):
    """Create a billing entry, or edit one when pk is given."""
    profile = require_workspace(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile) if pk else None
    if request.method != 'POST':
        return redirect('billing:billing')
    form = BillingEntryForm(request.POST, instance=entry, profile=profile)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.professional = profile
        patient = form.cleaned_data.get('patient')
        if patient:  # fill any blanks from the patient record
            obj.age = obj.age if obj.age is not None else patient.age
            obj.sex = obj.sex or patient.gender
            obj.contact_number = obj.contact_number or (patient.phone if can_see_contact(profile, patient) else '')
        obj.save()
        messages.success(request, f'Saved - {obj.invoice_number}')
        return _back(obj.entry_date)
    messages.error(request, first_error(form))
    return redirect('billing:billing')


@login_required
def patient_bill(request, patient_id):
    """Add a bill for one patient from that patient's Billing tab, then return to the tab."""
    profile, patient = own_patient(request, patient_id)
    back = redirect(f"{reverse('accounts:patient-detail', args=[patient.pk])}?tab=billing")
    if request.method != 'POST':
        return back
    form = PatientBillForm(request.POST)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.professional = profile
        entry.patient = patient
        entry.patient_name = patient.name
        entry.age = patient.age
        entry.sex = patient.gender
        entry.contact_number = patient.phone if can_see_contact(profile, patient) else ''
        entry.save()
        messages.success(request, f'Bill {entry.invoice_number} saved for {patient.name}.')
    else:
        messages.error(request, first_error(form))
    return back


@login_required
def entry_delete(request, pk):
    profile = require_workspace(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    if request.method == 'POST':
        date = entry.entry_date
        entry.delete()
        messages.success(request, 'Entry deleted.')
        return _back(date)
    return redirect('billing:billing')


# ---------------------------------------------------------------------------
# Patient packages: 1 / 2 / 3 / 4 weeks, a set number of sessions, a flat price
# ---------------------------------------------------------------------------

PACKAGE_FILTERS = ['active', 'due', 'completed', 'expired', 'cancelled']


@login_required
def packages(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    all_packages = list(PatientPackage.objects.filter(professional=profile).select_related('patient').prefetch_related('payments'))
    flt = request.GET.get('show', '')
    if flt == 'due':
        shown = [p for p in all_packages if p.effective_status != 'cancelled' and not p.is_fully_paid]
    elif flt in PACKAGE_FILTERS:
        shown = [p for p in all_packages if p.effective_status == flt]
    else:
        shown = all_packages

    preset = None
    if request.GET.get('patient', '').isdigit():
        preset = profile.patients.filter(pk=request.GET['patient']).first()

    live = [p for p in all_packages if p.effective_status == 'active']
    context = workspace_context(request.user, profile)
    context.update({
        'active': 'billing', 'billing_tab': 'packages', 'packages': shown, 'show': flt, 'filters': PACKAGE_FILTERS,
        'form': PatientPackageForm(profile=profile, initial={'start_date': timezone.localdate(), 'amount_paid_now': 0}),
        'payment_form': PackagePaymentForm(),
        'active_count': len(live), 'sessions_left': sum(p.sessions_remaining for p in live),
        'total_due': sum((p.amount_due for p in all_packages if p.effective_status != 'cancelled'), 0),
        'collected': sum((p.amount_paid for p in all_packages if p.effective_status != 'cancelled'), 0),
        'preset': {'id': preset.pk, 'name': preset.name, 'code': preset.patient_code} if preset else None,
        'open_new': request.GET.get('new') == '1' or preset is not None,
    })
    return render(request, 'billing/packages.html', context)


def _packages_back(request, patient=None):
    if request.POST.get('next') == 'patient' and patient is not None:
        return redirect(f"{reverse('accounts:patient-detail', args=[patient.pk])}?tab=billing")
    return redirect('billing:packages')


@login_required
def package_create(request):
    profile = require_workspace(request)
    if request.method != 'POST':
        return redirect('billing:packages')
    form = PatientPackageForm(request.POST, profile=profile)
    if form.is_valid():
        package = form.save(commit=False)
        package.professional = profile
        package.save()
        paid = form.cleaned_data.get('amount_paid_now') or 0
        if paid > 0:
            package.record_payment(paid, notes='Paid at booking')
        messages.success(request, f'Package started for {package.patient.name} - {package.get_duration_display()}, {package.total_sessions} sessions.')
        return _packages_back(request, package.patient)
    messages.error(request, first_error(form))
    return redirect('billing:packages')


@login_required
def package_payment(request, pk):
    profile = require_workspace(request)
    package = get_object_or_404(PatientPackage, pk=pk, professional=profile)
    if request.method == 'POST':
        form = PackagePaymentForm(request.POST)
        if package.is_fully_paid:
            messages.error(request, 'This package has no balance left to pay.')
        elif form.is_valid():
            payment = package.record_payment(form.cleaned_data['amount'], form.cleaned_data['payment_mode'], form.cleaned_data['notes'])
            messages.success(request, f'Payment recorded - NPR {payment.amount}.')
        else:
            messages.error(request, 'Enter a valid payment amount.')
    return _packages_back(request, package.patient)


@login_required
def package_cancel(request, pk):
    profile = require_workspace(request)
    package = get_object_or_404(PatientPackage, pk=pk, professional=profile)
    if request.method == 'POST':
        package.status = PatientPackage.CANCELLED
        package.save()
        messages.success(request, 'Package cancelled.')
    return _packages_back(request, package.patient)
