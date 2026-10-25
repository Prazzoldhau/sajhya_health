import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.access import can_see_contact, first_error, own_patient, require_workspace, workspace_context, workspace_profile

from .forms import BillCorrectionForm, BillingEntryForm, EntryPaymentForm, PackagePaymentForm, PatientBillForm, PatientPackageForm
from .models import BillingEntry, EntryPayment, PackagePayment, PatientPackage


def revenue_for(profile, date):
    """Money actually received on one day: payments on bills (including late settlements of credit) plus package payments."""
    start = timezone.make_aware(datetime.datetime.combine(date, datetime.time.min))
    end = start + datetime.timedelta(days=1)
    entries = EntryPayment.objects.filter(entry__professional=profile, entry__cancelled_at__isnull=True, paid_on=date).aggregate(t=Sum('amount'))['t'] or 0
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
        if not e.is_cancelled:
            total += e.rate
    received = EntryPayment.objects.filter(entry__professional=profile, entry__cancelled_at__isnull=True, paid_on=selected)
    for mode, amount in received.values_list('payment_mode', 'amount'):
        by_mode[mode] += amount
    collected = sum(by_mode.values())
    month_total = profile.billing_entries.filter(cancelled_at__isnull=True, entry_date__year=selected.year, entry_date__month=selected.month).aggregate(t=Sum('rate'))['t'] or 0
    packages_due = sum((p.amount_due for p in PatientPackage.objects.filter(professional=profile).exclude(status='cancelled')), 0)
    owed = [e for e in profile.billing_entries.filter(cancelled_at__isnull=True, amount_paid__lt=F('rate')).select_related('patient').order_by('entry_date', 'id')]
    bills_due = sum((e.amount_due for e in owed), 0)

    context = workspace_context(request.user, profile)
    context.update({
        'active': 'billing', 'billing_tab': 'book', 'form': form, 'entries': entries, 'selected': selected, 'today': today,
        'prev_date': selected - datetime.timedelta(days=1), 'next_date': selected + datetime.timedelta(days=1),
        'total': total, 'by_mode': [(mode_names[m], v) for m, v in by_mode.items()],
        'month_total': month_total, 'month_label': f'{selected:%B %Y}', 'package_payments': revenue_for(profile, selected) - collected, 'collected': collected,
        'packages_due': packages_due, 'owed': owed, 'bills_due': bills_due, 'pay_form': EntryPaymentForm(), 'correct_form': BillCorrectionForm(), 'open_new': request.GET.get('new') == '1', 'open_edit': request.GET.get('edit', '') if request.GET.get('edit', '').isdigit() else '',
    })
    return render(request, 'billing/billing.html', context)


@login_required
def entry_save(request, pk=None):
    """Create a billing entry, or edit one when pk is given."""
    profile = require_workspace(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile) if pk else None
    if request.method != 'POST':
        return redirect('billing:billing')
    if entry is not None and entry.is_cancelled:
        messages.error(request, 'A cancelled bill cannot be edited. Restore it first.')
        return _back(entry.entry_date)
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
        if not pk:
            form.apply_payment(obj, request.user)
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
        form.apply_payment(entry, request.user)
        messages.success(request, f'Bill {entry.invoice_number} saved for {patient.name}.' + (f' NPR {entry.amount_due:g} is due.' if entry.amount_due else ''))
    else:
        messages.error(request, first_error(form))
    return back


@login_required
def entry_payment(request, pk):
    """Receive money against a bill that was left on credit (in full or in part), then return to the page it came from."""
    profile = require_workspace(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    nxt = request.POST.get('next', '')
    back = redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else reverse('billing:billing'))
    if request.method != 'POST':
        return back
    form = EntryPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return back
    paid = entry.record_payment(form.cleaned_data['amount'], form.cleaned_data['payment_mode'], form.cleaned_data['notes'], user=request.user)
    if paid is None:
        messages.info(request, 'That bill is already fully paid.')
    else:
        messages.success(request, f'NPR {paid.amount:g} received for {entry.invoice_number}.' + (f' NPR {entry.amount_due:g} still due.' if entry.amount_due else ' Fully paid.'))
    return back


@login_required
def entry_correct(request, pk):
    """Fix a bill's amount, date, service or how it was paid (cash / credit / part paid). The patient's details are not part of it."""
    profile = require_workspace(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    nxt = request.POST.get('next', '')
    back = redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else f"{reverse('billing:billing')}?date={entry.entry_date.isoformat()}")
    if request.method != 'POST':
        return back
    if entry.is_cancelled:
        messages.error(request, 'A cancelled bill cannot be edited. Restore it first.')
        return back
    form = BillCorrectionForm(request.POST, instance=entry)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return back
    bill = form.save()
    bill.set_amount_paid(form.received_total(), bill.payment_mode, request.user)
    messages.success(request, f'{bill.invoice_number} updated - {bill.status_label.lower()}' + (f', NPR {bill.amount_due:g} due.' if bill.amount_due else '.'))
    return back


@login_required
def entry_cancel(request, pk):
    """Cancel a bill (a mistake, or the patient never came): it stays on record, struck through, and counts for nothing."""
    profile = require_workspace(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    nxt = request.POST.get('next', '')
    back = redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else f"{reverse('billing:billing')}?date={entry.entry_date.isoformat()}")
    if request.method != 'POST':
        return back
    if entry.is_cancelled:
        return back
    entry.cancelled_at, entry.cancel_reason = timezone.now(), request.POST.get('reason', '').strip()[:255]
    entry.save(update_fields=['cancelled_at', 'cancel_reason', 'updated_at'])
    note = f' NPR {entry.amount_paid:g} that was received is no longer counted as money taken - refund it to the patient.' if entry.amount_paid else ''
    messages.success(request, f'{entry.invoice_number} cancelled.{note}')
    return back


@login_required
def entry_restore(request, pk):
    profile = require_workspace(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    nxt = request.POST.get('next', '')
    back = redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else f"{reverse('billing:billing')}?date={entry.entry_date.isoformat()}")
    if request.method == 'POST' and entry.is_cancelled:
        entry.cancelled_at, entry.cancel_reason = None, ''
        entry.save(update_fields=['cancelled_at', 'cancel_reason', 'updated_at'])
        messages.success(request, f'{entry.invoice_number} restored.')
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
