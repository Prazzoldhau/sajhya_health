import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q, Sum
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.access import actor_of, can_see_contact, first_error
from .access import billing_context, billing_manager, billing_patient, billing_profile, billing_require, staff_member

from accounts.messaging import EMAIL_NOT_SET_UP, channel_links, email_ready

from . import catalog, exports
from . import package_docs as pdocs
from . import invoice as inv
from .forms import AdvanceForm, BillCorrectionForm, BillingEntryForm, EntryPaymentForm, PackagePaymentForm, PatientBillForm, PatientPackageForm
from .models import PRODUCT_TYPES, StockMove, PackageSession, package_session_rows, ServiceItem, ADVANCE, BillingEntry, EntryPayment, PackagePayment, PatientAdvance, PatientPackage, advance_balance, lock_patient


def revenue_for(profile, date):
    """Money actually received on one day: payments on bills (including late settlements of credit) plus package payments."""
    start = timezone.make_aware(datetime.datetime.combine(date, datetime.time.min))
    end = start + datetime.timedelta(days=1)
    entries = (EntryPayment.objects.filter(entry__professional=profile, entry__cancelled_at__isnull=True, paid_on=date).exclude(payment_mode=ADVANCE)
               .aggregate(t=Sum('amount'))['t'] or 0)
    entries += PatientAdvance.objects.filter(professional=profile, paid_on=date, kind__in=[PatientAdvance.DEPOSIT, PatientAdvance.REFUND], payment_mode__gt='').aggregate(t=Sum('amount'))['t'] or 0  # advances taken less refunds paid back
    packages = PackagePayment.objects.filter(package__professional=profile, created_at__gte=start, created_at__lt=end).aggregate(t=Sum('amount'))['t'] or 0
    return entries + packages


def _selected_date(request):
    try:
        return datetime.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        return timezone.localdate()


def _patient_page(request, patient):
    """Where to go after billing one patient: their own billing page (bills, packages and advances only, not the patient profile)."""
    return reverse('billing:patient', args=[patient.pk])


def _back(date):
    return redirect(f"{reverse('billing:billing')}?date={date.isoformat()}")


# ---------------------------------------------------------------------------
# Daily billing book
# ---------------------------------------------------------------------------

@login_required
def billing(request):
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    today = timezone.localdate()
    selected = _selected_date(request)

    form = BillingEntryForm(profile=profile, initial={'entry_date': selected})
    entries = profile.billing_entries.filter(entry_date=selected).select_related('patient').prefetch_related('advance_moves')
    mode_names = dict(BillingEntry._meta.get_field('payment_mode').choices)
    by_mode = {m: 0 for m in mode_names}
    total = 0
    for e in entries:
        if not e.is_cancelled:
            total += e.rate
    received = EntryPayment.objects.filter(entry__professional=profile, entry__cancelled_at__isnull=True, paid_on=selected).exclude(payment_mode=ADVANCE)
    for mode, amount in received.values_list('payment_mode', 'amount'):
        by_mode[mode] += amount
    collected = sum(by_mode.values())  # money received on bills
    advance_net = Decimal('0')
    for mode, amount in PatientAdvance.objects.filter(professional=profile, paid_on=selected, kind__in=[PatientAdvance.DEPOSIT, PatientAdvance.REFUND]).values_list('payment_mode', 'amount'):
        by_mode[mode or 'cash'] += amount
        advance_net += amount
    advance_held = PatientAdvance.objects.filter(professional=profile).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    month_total = profile.billing_entries.filter(cancelled_at__isnull=True, entry_date__year=selected.year, entry_date__month=selected.month).aggregate(t=Sum('rate'))['t'] or 0
    packages_due = sum((p.amount_due for p in PatientPackage.objects.filter(professional=profile).exclude(status='cancelled')), 0)
    owed = [e for e in profile.billing_entries.filter(cancelled_at__isnull=True, amount_paid__lt=F('rate')).select_related('patient').order_by('entry_date', 'id')]
    bills_due = sum((e.amount_due for e in owed), 0)

    search = None
    patient_id, text = request.GET.get('patient', ''), request.GET.get('q', '').strip()
    if patient_id.isdigit() or text:
        # search mode: only that patient's bills (every date), never the whole book
        found = profile.billing_entries.select_related('patient').prefetch_related('advance_moves')
        if patient_id.isdigit():
            found = found.filter(patient_id=int(patient_id))
            patient = profile.workspace_patients().filter(pk=int(patient_id)).first()
            label = patient.name if patient else 'this patient'
        else:
            found = found.filter(Q(patient_name__icontains=text) | Q(contact_number__icontains=text) | Q(invoice_number__icontains=text) | Q(patient__patient_code__icontains=text))
            label = text
        found = list(found.order_by('-entry_date', '-created_at')[:300])
        live = [e for e in found if not e.is_cancelled]
        search = {'advance': advance_balance(int(patient_id)) if patient_id.isdigit() else None, 'label': label, 'count': len(found), 'billed': sum((e.rate for e in live), 0), 'received': sum((e.amount_paid for e in live), 0),
                  'due': sum((e.amount_due for e in live), 0), 'text': text}
        entries = found
        owed = [e for e in owed if e in found]

    logs = (PackageSession.objects.filter(package__professional=profile, undone_at__isnull=True).select_related('package__patient', 'package__professional')
            .prefetch_related('package__session_log'))
    if search:  # one patient's (or one search's) package sessions on every date, like the bills
        if patient_id.isdigit():
            logs = logs.filter(package__patient_id=int(patient_id))
        else:
            logs = logs.filter(Q(package__patient__name__icontains=text) | Q(package__patient__patient_code__icontains=text))
        logs = logs.order_by('-date', '-id')[:300]
    else:
        logs = logs.filter(date=selected).order_by('id')
    package_sessions = package_session_rows(logs)

    context = billing_context(request, profile)
    context.update({
        'package_sessions': package_sessions, 'active': 'billing', 'billing_tab': 'book', 'search': search, 'form': form, 'entries': entries, 'selected': selected, 'today': today,
        'prev_date': selected - datetime.timedelta(days=1), 'next_date': selected + datetime.timedelta(days=1),
        'total': total, 'by_mode': [(mode_names[m], v) for m, v in by_mode.items()],
        'month_total': month_total, 'month_label': f'{selected:%B %Y}', 'package_payments': revenue_for(profile, selected) - collected - advance_net, 'collected': collected, 'advance_net': advance_net, 'received_total': revenue_for(profile, selected), 'advance_held': advance_held, 'advance_held_total': advance_held,
        'packages_due': packages_due, 'owed': owed, 'bills_due': bills_due, 'pay_form': EntryPaymentForm(), 'correct_form': BillCorrectionForm(), 'service_catalog': catalog.catalog_for(profile, staff_member(request).clinic.owner if staff_member(request) else None), 'open_new': request.GET.get('new') == '1', 'open_edit': request.GET.get('edit', '') if request.GET.get('edit', '').isdigit() else '',
    })
    return render(request, 'billing/billing.html', context)


@login_required
def entry_save(request, pk=None):
    """Create a billing entry, or edit one when pk is given."""
    profile = billing_require(request)
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
        if not pk:
            obj.created_by_name, obj.created_by_role = actor_of(request.user, profile)
        if not pk:
            short = catalog.stock_problem(profile, request.POST.get('lines'))
            if short:
                messages.error(request, short)
                return redirect('billing:billing')
        obj.save()
        carried = None
        if not pk:
            catalog.save_lines(obj, request.POST.get('lines'))
            form.apply_payment(obj, request.user)
            carried = getattr(form, 'carried', 0)
        messages.success(request, f'Saved - {obj.invoice_number}' + (f'. NPR {carried:g} carried over as advance for {obj.patient_name}.' if carried else ''))
        return _back(obj.entry_date)
    messages.error(request, first_error(form))
    return redirect('billing:billing')


@login_required
def patient_bill(request, patient_id):
    """Add a bill for one patient from that patient's Billing tab, then return to the tab."""
    profile, patient = billing_patient(request, patient_id)
    back = redirect(_patient_page(request, patient))
    if request.method != 'POST':
        return back
    short = catalog.stock_problem(profile, request.POST.get('lines'))
    if short:
        messages.error(request, short)
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
        entry.created_by_name, entry.created_by_role = actor_of(request.user, profile)
        entry.save()
        catalog.save_lines(entry, request.POST.get('lines'))
        form.apply_payment(entry, request.user)
        carried = getattr(form, 'carried', 0)
        if form.cleaned_data.get('payment_status') == 'advance' and entry.amount_paid == 0:
            messages.info(request, f'{patient.name} has no advance balance, so the bill is left on credit.')
        messages.success(request, f'Bill {entry.invoice_number} saved for {patient.name}.' + (f' NPR {entry.amount_due:g} is due.' if entry.amount_due else '') + (f' NPR {carried:g} carried over as advance - balance NPR {advance_balance(patient.pk):g}.' if carried else ''))
    else:
        messages.error(request, first_error(form))
    return back


def _advance_back(request, patient):
    """Where to return after taking or refunding an advance: the page it came from, else the patient's billing tab."""
    nxt = request.POST.get('next', '')
    if nxt.startswith('/') and not nxt.startswith('//'):
        return redirect(nxt)
    return redirect(_patient_page(request, patient))


@login_required
def advances(request):
    """Advances held: who has paid ahead, how much is left, and the full movement history of one patient."""
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    moves = list(PatientAdvance.objects.filter(professional=profile).select_related('patient', 'entry').order_by('paid_on', 'created_at', 'id'))
    today = timezone.localdate()
    month_start = today.replace(day=1)
    people = {}
    month = {PatientAdvance.DEPOSIT: Decimal('0'), PatientAdvance.USED: Decimal('0'), PatientAdvance.REFUND: Decimal('0')}
    for m in moves:
        p = people.setdefault(m.patient_id, {'patient': m.patient, 'balance': Decimal('0'), 'taken': Decimal('0'), 'used': Decimal('0'), 'refunded': Decimal('0'), 'last': m.paid_on})
        p['balance'] += m.amount
        p['last'] = max(p['last'], m.paid_on)
        if m.kind == PatientAdvance.DEPOSIT:
            p['taken'] += m.amount
        elif m.kind == PatientAdvance.USED:
            p['used'] += -m.amount
        elif m.kind == PatientAdvance.REFUND:
            p['refunded'] += -m.amount
        if m.paid_on >= month_start and m.kind in month:
            month[m.kind] += abs(m.amount)
    text = request.GET.get('q', '').strip().lower()
    show = 'all' if request.GET.get('show') == 'all' else 'balance'
    rows = [p for p in people.values() if (show == 'all' or p['balance'] > 0)
            and (not text or text in p['patient'].name.lower() or text in p['patient'].patient_code.lower())]
    rows.sort(key=lambda p: (-p['balance'], p['patient'].name.lower()))
    for p in rows:
        p['contact'] = p['patient'].phone if can_see_contact(profile, p['patient']) else ''

    chosen = None
    pid = request.GET.get('patient', '')
    if pid.isdigit() and int(pid) in people:
        chosen = people[int(pid)]
    elif rows:
        chosen = people[rows[0]['patient'].pk]
    ledger = []
    if chosen:
        running = Decimal('0')
        for m in (m for m in moves if m.patient_id == chosen['patient'].pk):
            running += m.amount
            ledger.append({'move': m, 'running': running})
        ledger.reverse()  # newest first
    held = sum((p['balance'] for p in people.values()), Decimal('0'))
    context = billing_context(request, profile)
    context.update({
        'active': 'billing', 'billing_tab': 'advances', 'rows': rows, 'chosen': chosen, 'ledger': ledger, 'q': request.GET.get('q', '').strip(), 'show': show,
        'advance_held_total': held, 'held': held, 'holders': sum(1 for p in people.values() if p['balance'] > 0), 'month_taken': month[PatientAdvance.DEPOSIT],
        'month_used': month[PatientAdvance.USED], 'month_refunded': month[PatientAdvance.REFUND], 'month_label': f'{today:%B %Y}',
        'advance_form': AdvanceForm(), 'next_url': request.get_full_path(),
    })
    return render(request, 'billing/advances.html', context)


@login_required
def advance_add(request, patient_id):
    """Take money from a patient in advance, to be used against their next bills."""
    profile, patient = billing_patient(request, patient_id)
    back = _advance_back(request, patient)
    if request.method != 'POST':
        return back
    form = AdvanceForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return back
    move = form.save(commit=False)
    move.patient, move.professional, move.kind, move.recorded_by = patient, profile, PatientAdvance.DEPOSIT, request.user
    move.save()
    used = 0
    for entry in profile.billing_entries.filter(patient=patient, cancelled_at__isnull=True, amount_paid__lt=F('rate')).order_by('entry_date', 'id'):
        if request.POST.get('settle') and advance_balance(patient.pk) > 0:  # optionally clear the oldest unpaid bills first
            used += entry.use_advance(request.user)
    balance = advance_balance(patient.pk)
    messages.success(request, f'NPR {move.amount:g} advance taken from {patient.name}.' + (f' NPR {used:g} used for unpaid bills.' if used else '') + f' Balance: NPR {balance:g}.')
    return back


@login_required
def advance_refund(request, patient_id):
    """Pay back part or all of what a patient has left in advance."""
    profile, patient = billing_patient(request, patient_id)
    back = _advance_back(request, patient)
    if request.method != 'POST':
        return back
    form = AdvanceForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return back
    amount = form.cleaned_data['amount']
    with transaction.atomic():
        lock_patient(patient.pk)  # check the balance and pay it back under one lock, so a double click cannot refund it twice
        if amount > advance_balance(patient.pk):
            messages.error(request, f'Only NPR {advance_balance(patient.pk):g} is held for {patient.name}.')
            return back
        PatientAdvance.objects.create(patient=patient, professional=profile, kind=PatientAdvance.REFUND, amount=-amount, payment_mode=form.cleaned_data['payment_mode'],
                                      notes=form.cleaned_data['notes'], recorded_by=request.user)
    messages.success(request, f'NPR {amount:g} refunded to {patient.name}. Balance: NPR {advance_balance(patient.pk):g}.')
    return back


@login_required
def entry_payment(request, pk):
    """Receive money against a bill that was left on credit (in full or in part), then return to the page it came from."""
    profile = billing_require(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    nxt = request.POST.get('next', '')
    back = redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else reverse('billing:billing'))
    if request.method != 'POST':
        return back
    form = EntryPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return back
    if form.cleaned_data['payment_mode'] == ADVANCE:
        used = entry.use_advance(request.user, limit=form.cleaned_data['amount'])
        if not used:
            messages.error(request, 'This patient has no advance balance to use.' if entry.patient_id else 'Only a bill linked to a patient can use an advance.')
            return back
        entry.refresh_from_db()
        messages.success(request, f'NPR {used:g} taken from the advance for {entry.invoice_number}.' + (f' NPR {entry.amount_due:g} still due.' if entry.amount_due else ' Fully paid.'))
        return back
    given, owed = form.cleaned_data['amount'], entry.amount_due
    paid = entry.record_payment(given, form.cleaned_data['payment_mode'], form.cleaned_data['notes'], user=request.user)
    if paid is not None and given > paid.amount and entry.patient_id:  # handed over more than is owed: keep the extra as advance
        entry.carry_over(given - paid.amount, form.cleaned_data['payment_mode'], user=request.user)
        messages.info(request, f'NPR {given - paid.amount:g} extra was carried over as the patient\'s advance.')
    if paid is None:
        messages.info(request, 'That bill is already fully paid.')
    else:
        messages.success(request, f'NPR {paid.amount:g} received for {entry.invoice_number}.' + (f' NPR {entry.amount_due:g} still due.' if entry.amount_due else ' Fully paid.'))
    return back


@login_required
def entry_correct(request, pk):
    """Fix a bill's amount, date, service or how it was paid (cash / credit / part paid). The patient's details are not part of it."""
    profile = billing_require(request)
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
    profile = billing_require(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    nxt = request.POST.get('next', '')
    back = redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else f"{reverse('billing:billing')}?date={entry.entry_date.isoformat()}")
    if request.method != 'POST':
        return back
    if entry.is_cancelled:
        return back
    returned = entry.release_advance(request.user)  # what was taken from an advance goes back to the patient's balance
    entry.cancelled_at, entry.cancel_reason = timezone.now(), request.POST.get('reason', '').strip()[:255]
    entry.save(update_fields=['cancelled_at', 'cancel_reason', 'updated_at'])
    catalog.release_stock(entry, *actor_of(request.user, profile))
    note = (f' NPR {returned:g} went back to the patient\'s advance balance.' if returned else '') + (f' NPR {entry.amount_paid:g} that was received is no longer counted as money taken - refund it to the patient.' if entry.amount_paid else '')
    messages.success(request, f'{entry.invoice_number} cancelled.{note}')
    return back


@login_required
def entry_restore(request, pk):
    profile = billing_require(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    nxt = request.POST.get('next', '')
    back = redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else f"{reverse('billing:billing')}?date={entry.entry_date.isoformat()}")
    if request.method == 'POST' and entry.is_cancelled:
        entry.cancelled_at, entry.cancel_reason = None, ''
        entry.save(update_fields=['cancelled_at', 'cancel_reason', 'updated_at'])
        catalog.retake_stock(entry, *actor_of(request.user, profile))
        messages.success(request, f'{entry.invoice_number} restored.')
    return back


@login_required
def entry_delete(request, pk):
    billing_manager(request)
    profile = billing_require(request)
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    if request.method == 'POST':
        date = entry.entry_date
        if not entry.is_cancelled:
            catalog.release_stock(entry, *actor_of(request.user, profile))
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
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    all_packages = list(PatientPackage.objects.filter(professional=profile).select_related('patient', 'professional').prefetch_related('payments', 'session_log'))
    flt = request.GET.get('show', '')
    if flt == 'due':
        shown = [p for p in all_packages if p.effective_status != 'cancelled' and not p.is_fully_paid]
    elif flt in PACKAGE_FILTERS:
        shown = [p for p in all_packages if p.effective_status == flt]
    else:
        shown = all_packages

    preset = None
    if request.GET.get('patient', '').isdigit():
        preset = profile.workspace_patients().filter(pk=request.GET['patient']).first()

    live = [p for p in all_packages if p.effective_status == 'active']
    context = billing_context(request, profile)
    context.update({
        'advance_held_total': PatientAdvance.objects.filter(professional=profile).aggregate(t=Sum('amount'))['t'] or 0,
        'active': 'billing', 'billing_tab': 'packages', 'packages': shown, 'show': flt, 'filters': PACKAGE_FILTERS, 'today': timezone.localdate(),
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
    nxt = request.POST.get('next', '')
    if nxt == 'patient' and patient is not None:
        return redirect(_patient_page(request, patient))
    if nxt.startswith('/') and not nxt.startswith('//'):  # e.g. back to the Payments due page
        return redirect(nxt)
    return redirect('billing:packages')


@login_required
def package_create(request):
    profile = billing_require(request)
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
    profile = billing_require(request)
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
def package_use(request, pk):
    """Front desk or admin: record that the patient used a session of their package on a date."""
    profile = billing_require(request)
    package = get_object_or_404(PatientPackage, pk=pk, professional=profile)
    if request.method != 'POST':
        return _packages_back(request)
    try:
        day = datetime.date.fromisoformat(request.POST.get('date', ''))
    except ValueError:
        day = timezone.localdate()
    if day > timezone.localdate():
        messages.error(request, 'A session cannot be recorded for a future date.')
    elif day < package.start_date:
        messages.error(request, f'That is before the package started on {package.start_date:%b} {package.start_date.day}.')
    else:
        name, role = actor_of(request.user, profile)
        entry = package.use_session(day, name, role, request.POST.get('note', '').strip())
        if entry is None:
            messages.error(request, f'This package is {package.effective_status_display.lower()}, so no more sessions can be recorded.')
        else:
            left = package.sessions_remaining
            messages.success(request, f'Session recorded for {package.patient.name}: {package.sessions_used} of {package.total_sessions} used' + (f', {left} left.' if left else '. The package is now complete.'))
    return _packages_back(request)


@login_required
def package_session_undo(request, pk, entry_id):
    """Take back a session that was recorded by mistake (it stays in the log as undone)."""
    profile = billing_require(request)
    package = get_object_or_404(PatientPackage, pk=pk, professional=profile)
    entry = get_object_or_404(package.session_log, pk=entry_id)
    if request.method == 'POST':
        name, _ = actor_of(request.user, profile)
        messages.success(request, 'Session taken back.' if package.undo_session(entry, name) else 'That session was already taken back.')
    return _packages_back(request)


@login_required
def package_cancel(request, pk):
    profile = billing_require(request)
    package = get_object_or_404(PatientPackage, pk=pk, professional=profile)
    if request.method == 'POST':
        package.status = PatientPackage.CANCELLED
        package.save()
        messages.success(request, 'Package cancelled.')
    return _packages_back(request, package.patient)


# ---------------------------------------------------------------------------
# The bill as a document: invoice page, PDF, and sending it on
# ---------------------------------------------------------------------------

def _pdf_response(entry, online_url='', download=False):
    response = HttpResponse(inv.build_pdf(entry, online_url), content_type='application/pdf')
    disposition = 'attachment' if download else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="{entry.invoice_number}.pdf"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def invoice(request, pk):
    """The printable invoice with the ways to send it: download, print / save as PDF, WhatsApp, share, e-mail, copy link."""
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    entry = get_object_or_404(BillingEntry.objects.select_related('patient'), pk=pk, professional=profile)
    public_url = request.build_absolute_uri(reverse('billing:invoice-public', args=[inv.invoice_token(entry)]))
    phone = entry.contact_shown or (entry.patient.phone if entry.patient_id and can_see_contact(profile, entry.patient) else '')
    email = entry.patient.email if entry.patient_id and can_see_contact(profile, entry.patient) else ''
    back = request.GET.get('next', '')
    context = billing_context(request, profile)
    from .models import advance_balance
    context.update({
        'lines': entry.line_items, 'carried': entry.carried_over, 'cash_handed_over': entry.cash_handed_over, 'advance_now': advance_balance(entry.patient_id) if entry.patient_id else 0,
        'active': 'billing', 'entry': entry, 'practice': inv.practice_of(entry), 'payments': entry.payments.all(), 'public_url': public_url,
        'links': channel_links(phone, inv.share_message(entry, public_url), entry.patient.messaging_app if entry.patient_id else 'whatsapp', profile.whatsapp_web), 'whatsapp': inv.whatsapp_link(entry, phone, public_url), 'whatsapp_chat': inv.whatsapp_chat(phone, profile.whatsapp_web), 'message': inv.share_message(entry, public_url), 'phone': phone, 'email': email,
        'back': back if back.startswith('/') and not back.startswith('//') else reverse('billing:billing') + f'?date={entry.entry_date.isoformat()}',
        'link_days': inv.LINK_DAYS,
    })
    return render(request, 'billing/invoice.html', context)


@login_required
def invoice_png(request, pk):
    """The invoice as a picture drawn on the server: what the page falls back to when the browser cannot draw it."""
    profile = billing_profile(request)
    if profile is None:
        raise Http404
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    response = HttpResponse(inv.build_png(entry), content_type='image/png')
    response['Content-Disposition'] = f'inline; filename="{entry.invoice_number}.png"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def invoice_pdf(request, pk):
    profile = billing_profile(request)
    if profile is None:
        raise Http404
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    return _pdf_response(entry, download=request.GET.get('download') == '1')


def invoice_public(request, token):
    """The link a patient receives: the PDF, no sign-in needed. It is signed, so it cannot be guessed, and it expires."""
    entry = inv.entry_from_token(token)
    if entry is None:
        raise Http404
    return _pdf_response(entry, request.build_absolute_uri(request.path))


@login_required
def invoice_email(request, pk):
    profile = billing_profile(request)
    if profile is None:
        raise Http404
    entry = get_object_or_404(BillingEntry, pk=pk, professional=profile)
    back = redirect('billing:invoice', pk=entry.pk)
    if request.method != 'POST':
        return back
    if not email_ready():
        messages.error(request, EMAIL_NOT_SET_UP)
        return back
    address = request.POST.get('email', '').strip()
    try:
        validate_email(address)
    except ValidationError:
        messages.error(request, 'Enter a valid e-mail address.')
        return back
    url = request.build_absolute_uri(reverse('billing:invoice-public', args=[inv.invoice_token(entry)]))
    practice = inv.practice_of(entry)['name']
    mail = EmailMessage(subject=f'Invoice {entry.invoice_number} from {practice}', body=inv.share_message(entry, url) + f'\n\nThe invoice is attached as a PDF.\n\n{practice}',
                        to=[address], reply_to=[e for e in [profile.account.user.email] if e])
    mail.attach(f'{entry.invoice_number}.pdf', inv.build_pdf(entry, url), 'application/pdf')
    try:
        mail.send()
    except Exception:  # the mail server is the one thing we cannot control: say so plainly instead of a server error
        messages.error(request, 'The e-mail could not be sent right now. Use WhatsApp or the PDF download instead, or try again later.')
        return back
    messages.success(request, f'Invoice {entry.invoice_number} e-mailed to {address}.')
    return back


# ---------------------------------------------------------------------------
# The billing sheet and downloads
# ---------------------------------------------------------------------------

@login_required
def sheet(request):
    """All bills as a spreadsheet-style table (filter, sort, totals) with the Excel / CSV download one click away."""
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    f = exports.Filters.from_query(request.GET)
    scope = exports.profile_scope(profile)
    rows = exports.sheet_rows(scope, f, limit=exports.MAX_SHEET_ROWS + 1)
    truncated = len(rows) > exports.MAX_SHEET_ROWS
    rows = rows[:exports.MAX_SHEET_ROWS]
    sheet_data = [{'date': r['date'].isoformat(), 'invoice': r['invoice'], 'patient': r['patient'], 'code': r['code'], 'phone': r['phone'], 'service': r['service'],
                   'amount': float(r['amount']), 'received': float(r['received']), 'due': float(r['due']), 'status': r['status'], 'mode': r['mode'], 'cancelled': r['status'] == 'Cancelled'}
                  for r in rows]
    context = billing_context(request, profile)
    context.update({'month_nav': f.month_nav(), 'sheet_data': sheet_data, 'sheet_range': {'start': f.start.isoformat(), 'end': f.end.isoformat()},
                    'active': 'billing', 'billing_tab': 'sheet', 'f': f, 'qs': f.querystring(), 'rows': rows, 'totals': exports.totals(rows), 'truncated': truncated,
                    'shown': len(rows), 'statuses': exports.STATUSES, 'modes': exports.MODES, 'columns': [(h, key) for h, _, key in exports.BILL_COLUMNS],
                    'numeric': exports.NUMERIC,
                    'advance_held_total': PatientAdvance.objects.filter(professional=profile).aggregate(t=Sum('amount'))['t'] or 0})
    return render(request, 'billing/sheet.html', context)


def _download(content, filename, content_type):
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def export_xlsx(request):
    profile = billing_profile(request)
    if profile is None:
        raise Http404
    f = exports.Filters.from_query(request.GET)
    return _download(exports.build_workbook(exports.profile_scope(profile), f), f'billing_{f.start:%Y%m%d}_{f.end:%Y%m%d}.xlsx',
                     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@login_required
def export_csv(request):
    profile = billing_profile(request)
    if profile is None:
        raise Http404
    f = exports.Filters.from_query(request.GET)
    return _download(exports.build_csv(exports.profile_scope(profile), f), f'billing_{f.start:%Y%m%d}_{f.end:%Y%m%d}.csv', 'text/csv; charset=utf-8')


# ---------------------------------------------------------------------------
# The price list
# ---------------------------------------------------------------------------

@login_required
def services(request):
    billing_manager(request)
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    context = billing_context(request, profile)
    departments = list(profile.departments.all())
    context.update({'active': 'billing', 'billing_tab': 'services', 'items': ServiceItem.objects.filter(professional=profile, is_product=False).select_related('department'),
                    'products': ServiceItem.objects.filter(professional=profile, is_product=True).select_related('department'), 'product_types': PRODUCT_TYPES,
                    'stock_moves': StockMove.objects.filter(item__professional=profile).select_related('item', 'bill')[:30],
                    'departments': [{'obj': d, 'kind': catalog.kind_of(d.name)} for d in departments],
                    'advance_held_total': PatientAdvance.objects.filter(professional=profile).aggregate(t=Sum('amount'))['t'] or 0})
    return render(request, 'billing/services.html', context)


@login_required
def service_save(request, pk):
    """Add a service (pk 0) or change one: name, price, service / add-on, in use."""
    billing_manager(request)
    profile = billing_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('billing:services')
    item = get_object_or_404(ServiceItem, pk=pk, professional=profile) if pk else None
    name = (request.POST.get('name') or '').strip()[:100]
    try:
        price = Decimal(request.POST.get('price', ''))
    except Exception:  # noqa: BLE001 - any bad number is the same message
        price = None
    if not name or price is None or price < 0 or price >= Decimal('10000000'):
        messages.error(request, 'Give the service a name and a price of zero or more.')
        return redirect('billing:services')
    if ServiceItem.objects.filter(professional=profile, name__iexact=name).exclude(pk=pk or 0).exists():
        messages.error(request, f'"{name}" is already on your price list.')
        return redirect('billing:services')
    if ServiceItem.objects.filter(professional=profile).count() >= 60 and item is None:
        messages.error(request, 'The price list can hold up to 60 items.')
        return redirect('billing:services')
    if item is None:
        item = ServiceItem(professional=profile, order=ServiceItem.objects.filter(professional=profile).count())
        item.active = True
    else:
        item.active = request.POST.get('active') == 'on'
    kind = request.POST.get('kind')
    item.name, item.price, item.is_addon, item.is_product = name, price.quantize(Decimal('0.01')), kind == 'addon', kind == 'product'
    if item.is_product:
        item.track_stock = request.POST.get('track_stock') == 'on'
        try:
            item.low_stock_at = min(max(int(request.POST.get('low_stock_at', item.low_stock_at)), 0), 9999)
        except ValueError:
            pass
    ptype = request.POST.get('product_type', '')
    item.product_type = ptype if item.is_product and ptype in dict(PRODUCT_TYPES) else ''
    item.department = profile.departments.filter(pk=int(request.POST['department'])).first() if request.POST.get('department', '').isdigit() else None
    item.save()
    messages.success(request, f'{item.name} saved at NPR {item.price:g}.')
    return redirect('billing:services')


@login_required
def stock_adjust(request, pk):
    """Receive stock, remove some (damaged, expired) or correct the count of a product; each change is logged with who made it."""
    billing_manager(request)
    profile = billing_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('billing:services')
    item = get_object_or_404(ServiceItem, pk=pk, professional=profile, is_product=True)
    try:
        number = int(request.POST.get('number', ''))
    except ValueError:
        number = -1
    action = request.POST.get('action')
    name, role = actor_of(request.user, profile)
    note = request.POST.get('note', '').strip()
    if number < 0 or number > 100000 or action not in ('receive', 'remove', 'set') or (action != 'set' and number == 0):
        messages.error(request, 'Give a number of items.')
    else:
        if not item.track_stock:
            item.track_stock = True
            item.save(update_fields=['track_stock'])
        if action == 'receive':
            item.change_stock(number, StockMove.RECEIVED, name, role, note)
        elif action == 'remove':
            item.change_stock(-number, StockMove.REMOVED, name, role, note)
        else:
            item.change_stock(number - item.stock, StockMove.ADJUST, name, role, note)
        messages.success(request, f'{item.name}: {item.stock} in stock.')
    return redirect(reverse('billing:services') + '#products')


@login_required
def service_delete(request, pk):
    billing_manager(request)
    profile = billing_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('billing:services')
    ServiceItem.objects.filter(pk=pk, professional=profile).delete()
    messages.success(request, 'Removed from the price list.')
    return redirect('billing:services')


@login_required
def services_seed(request):
    billing_manager(request)
    profile = billing_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('billing:services')
    department = profile.departments.filter(pk=int(request.POST['department'])).first() if request.POST.get('department', '').isdigit() else None
    if request.POST.get('products'):
        added = catalog.seed_products(profile)
        if added:
            messages.success(request, f'{added} aids and products added. Change the prices to yours.')
        else:
            messages.info(request, 'Those aids and products are already on your list.')
        return redirect('billing:services')
    added = catalog.seed_suggested(profile, department)
    if added:
        messages.success(request, f'{added} services added' + (f' for {department.name}' if department else '') + '. Change the prices to yours.')
    else:
        messages.info(request, 'Those services are already on your price list.' if department else 'Your price list already has services.')
    return redirect('billing:services')


# ---------------------------------------------------------------------------
# A package as documents: the package invoice and a receipt for each payment
# ---------------------------------------------------------------------------

def _package_for(request, pk):
    profile = billing_profile(request)
    if profile is None:
        raise Http404
    package = get_object_or_404(PatientPackage.objects.select_related('patient', 'professional').prefetch_related('payments', 'session_log'), pk=pk, professional=profile)
    return profile, package


def _payment_for(request, pk):
    profile = billing_profile(request)
    if profile is None:
        raise Http404
    payment = get_object_or_404(PackagePayment.objects.select_related('package__patient', 'package__professional'), pk=pk, package__professional=profile)
    return profile, payment


def _pkg_pdf(content, name, download=False):
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'{"attachment" if download else "inline"}; filename="{name}.pdf"'
    response['Cache-Control'] = 'private, no-store'
    return response


def _doc_page(request, profile, package, payment=None):
    """The package invoice (payment None) or a payment's receipt, laid out for printing and for sending."""
    kind = 'receipt' if payment else 'invoice'
    if payment:
        public_url = request.build_absolute_uri(reverse('billing:package-receipt-public', args=[pdocs.receipt_token(payment)]))
        message = pdocs.receipt_message(payment, public_url)
        number, urls = payment.receipt_number, {'pdf': reverse('billing:package-receipt-pdf', args=[payment.pk]), 'email': reverse('billing:package-receipt-email', args=[payment.pk])}
    else:
        public_url = request.build_absolute_uri(reverse('billing:package-invoice-public', args=[pdocs.invoice_token(package)]))
        message = pdocs.invoice_message(package, public_url)
        number, urls = package.invoice_number, {'pdf': reverse('billing:package-invoice-pdf', args=[package.pk]), 'email': reverse('billing:package-invoice-email', args=[package.pk])}
    patient = package.patient
    phone = patient.phone if can_see_contact(profile, patient) else ''
    email = patient.email if can_see_contact(profile, patient) else ''
    context = billing_context(request, profile)
    due, paid = pdocs.balance_after(payment) if payment else (package.amount_due, package.amount_paid)
    context.update({
        'active': 'billing', 'kind': kind, 'package': package, 'payment': payment, 'number': number, 'practice': pdocs.practice_of(package.professional), 'patient': patient,
        'facts': pdocs.invoice_lines(package), 'sessions': pdocs.session_rows(package), 'payments': sorted(package.payments.all(), key=lambda x: (x.created_at, x.pk)), 'due_after': due, 'paid_so_far': paid,
        'public_url': public_url, 'message': message, 'phone': phone, 'email': email, 'urls': urls, 'link_days': pdocs.LINK_DAYS,
        'links': channel_links(phone, message, patient.messaging_app, profile.whatsapp_web), 'whatsapp_chat': inv.whatsapp_chat(phone, profile.whatsapp_web),
        'file_name': number, 'back': reverse('billing:packages'),
    })
    return render(request, 'billing/package_doc.html', context)


@login_required
def package_invoice(request, pk):
    profile, package = _package_for(request, pk)
    return _doc_page(request, profile, package)


@login_required
def package_invoice_pdf(request, pk):
    profile, package = _package_for(request, pk)
    return _pkg_pdf(pdocs.build_invoice_pdf(package), package.invoice_number, request.GET.get('download') == '1')


def package_invoice_public(request, token):
    package = pdocs.package_from_token(token)
    if package is None:
        raise Http404
    return _pkg_pdf(pdocs.build_invoice_pdf(package, request.build_absolute_uri(request.path)), package.invoice_number)


@login_required
def package_receipt(request, pk):
    profile, payment = _payment_for(request, pk)
    return _doc_page(request, profile, payment.package, payment)


@login_required
def package_receipt_pdf(request, pk):
    profile, payment = _payment_for(request, pk)
    return _pkg_pdf(pdocs.build_receipt_pdf(payment), payment.receipt_number, request.GET.get('download') == '1')


def package_receipt_public(request, token):
    payment = pdocs.payment_from_token(token)
    if payment is None:
        raise Http404
    return _pkg_pdf(pdocs.build_receipt_pdf(payment, request.build_absolute_uri(request.path)), payment.receipt_number)


def _send_pdf_email(request, profile, package, payment, back):
    if not email_ready():
        messages.error(request, EMAIL_NOT_SET_UP)
        return back
    address = request.POST.get('email', '').strip()
    try:
        validate_email(address)
    except ValidationError:
        messages.error(request, 'Enter a valid e-mail address.')
        return back
    practice = pdocs.practice_of(package.professional)['name']
    if payment:
        url = request.build_absolute_uri(reverse('billing:package-receipt-public', args=[pdocs.receipt_token(payment)]))
        subject, text, name, content = f'Receipt {payment.receipt_number} from {practice}', pdocs.receipt_message(payment, url), payment.receipt_number, pdocs.build_receipt_pdf(payment, url)
    else:
        url = request.build_absolute_uri(reverse('billing:package-invoice-public', args=[pdocs.invoice_token(package)]))
        subject, text, name, content = f'Package invoice {package.invoice_number} from {practice}', pdocs.invoice_message(package, url), package.invoice_number, pdocs.build_invoice_pdf(package, url)
    mail = EmailMessage(subject=subject, body=text + f'\n\nThe document is attached as a PDF.\n\n{practice}', to=[address], reply_to=[e for e in [profile.account.user.email] if e])
    mail.attach(f'{name}.pdf', content, 'application/pdf')
    try:
        mail.send()
    except Exception:  # the mail server is the one thing we cannot control: say so plainly instead of a server error
        messages.error(request, 'The e-mail could not be sent right now. Use WhatsApp or the PDF download instead, or try again later.')
        return back
    messages.success(request, f'Sent by e-mail to {address}.')
    return back


@login_required
def package_invoice_email(request, pk):
    profile, package = _package_for(request, pk)
    back = redirect('billing:package-invoice', pk=package.pk)
    if request.method != 'POST':
        return back
    return _send_pdf_email(request, profile, package, None, back)


@login_required
def package_receipt_email(request, pk):
    profile, payment = _payment_for(request, pk)
    back = redirect('billing:package-receipt', pk=payment.pk)
    if request.method != 'POST':
        return back
    return _send_pdf_email(request, profile, payment.package, payment, back)


# ---------------------------------------------------------------------------
# Payments due: everything patients still owe, on a page of its own
# ---------------------------------------------------------------------------

DUE_FILTERS = [('', 'All'), ('bills', 'Bills only'), ('packages', 'Packages only'), ('week', 'Over 7 days'), ('old', 'Over 30 days')]


def _due_groups(profile, today):
    """Everyone who owes something, one entry per patient: their unpaid bills and package balances, the total, and how long the oldest has been waiting."""
    from accounts import messaging
    groups = {}

    def group(patient, name, phone):
        key = ('p', patient.pk) if patient is not None else ('n', name.lower())
        if key not in groups:
            groups[key] = {'patient': patient, 'name': name, 'code': patient.patient_code if patient is not None else '', 'phone': phone, 'bills': [], 'packages': [], 'total': Decimal('0'), 'oldest': today}
        return groups[key]

    bills = profile.billing_entries.filter(cancelled_at__isnull=True, amount_paid__lt=F('rate')).select_related('patient').order_by('entry_date', 'id')
    for e in bills:
        phone = (e.patient.phone if can_see_contact(profile, e.patient) else '') if e.patient_id else e.contact_number
        g = group(e.patient, e.patient_name, phone or e.contact_number)
        g['bills'].append(e)
        g['total'] += e.amount_due
        g['oldest'] = min(g['oldest'], e.entry_date)
    for p in PatientPackage.objects.filter(professional=profile).exclude(status='cancelled').select_related('patient'):
        if p.is_fully_paid:
            continue
        g = group(p.patient, p.patient.name, p.patient.phone if can_see_contact(profile, p.patient) else '')
        g['packages'].append(p)
        g['total'] += p.amount_due
        g['oldest'] = min(g['oldest'], p.start_date)
    out = list(groups.values())
    for g in out:
        g['days'] = (today - g['oldest']).days
        g['band'] = 'old' if g['days'] > 30 else 'week' if g['days'] > 7 else 'new'
        text = messaging.render(messaging.body_for(profile, 'payment_due'), {**messaging.practice_values(profile), 'patient': g['name'], 'amount': f"{g['total']:g}"})
        g['reminder'] = messaging.whatsapp_url(g['phone'], text, profile.whatsapp_web)
    return out


@login_required
def dues(request):
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    today = timezone.localdate()
    flt = request.GET.get('show', '')
    text = request.GET.get('q', '').strip().lower()
    sort = request.GET.get('sort', '')
    everyone = _due_groups(profile, today)
    summary = {'total': sum((g['total'] for g in everyone), Decimal('0')), 'patients': len(everyone), 'bills': sum((e.amount_due for g in everyone for e in g['bills']), Decimal('0')),
               'packages': sum((p.amount_due for g in everyone for p in g['packages']), Decimal('0')), 'oldest': max((g['days'] for g in everyone), default=0)}
    aging = [{'label': label, 'value': sum((g['total'] for g in everyone if g['band'] == band), Decimal('0')), 'count': sum(1 for g in everyone if g['band'] == band), 'band': band}
             for band, label in (('new', 'Up to 7 days'), ('week', '8 to 30 days'), ('old', 'Over 30 days'))]
    top = max((a['value'] for a in aging), default=0) or 1
    for a in aging:
        a['pct'] = round(100 * a['value'] / top) if a['value'] else 0
    shown = everyone
    if flt == 'bills':
        shown = [g for g in shown if g['bills']]
    elif flt == 'packages':
        shown = [g for g in shown if g['packages']]
    elif flt == 'week':
        shown = [g for g in shown if g['days'] > 7]
    elif flt == 'old':
        shown = [g for g in shown if g['days'] > 30]
    if text:
        shown = [g for g in shown if text in g['name'].lower() or text in g['code'].lower() or text in (g['phone'] or '').lower()
                 or any(text in e.invoice_number.lower() for e in g['bills'])]
    shown = sorted(shown, key=(lambda g: -g['days']) if sort == 'oldest' else (lambda g: -g['total']))
    context = billing_context(request, profile)
    context.update({'active': 'billing', 'billing_tab': 'dues', 'groups': shown, 'summary': summary, 'aging': aging, 'filters': DUE_FILTERS, 'show': flt, 'q': request.GET.get('q', '').strip(),
                    'sort': sort, 'pay_form': EntryPaymentForm(), 'shown_total': sum((g['total'] for g in shown), Decimal('0'))})
    return render(request, 'billing/dues.html', context)


@login_required
def patient_billing(request, patient_id):
    """One patient's billing and nothing else: new bill, advances, packages (start, pay, use) and the bill history. The front desk gets it too."""
    profile = billing_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    patient = get_object_or_404(profile.workspace_patients(), pk=patient_id)
    member = staff_member(request)
    bills = list(patient.billing_entries.prefetch_related('advance_moves', 'payments')[:50])
    live = [b for b in bills if not b.is_cancelled]
    context = billing_context(request, profile)
    context.update({
        'active': 'billing', 'billing_tab': 'book', 'patient': patient, 'show_contact': can_see_contact(profile, patient), 'back_url': reverse('billing:patient', args=[patient.pk]),
        'bill_entries': bills, 'packages': patient.packages.prefetch_related('payments'), 'payment_form': PackagePaymentForm(), 'bill_form': PatientBillForm(initial={'entry_date': timezone.localdate()}),
        'pay_form': EntryPaymentForm(), 'correct_form': BillCorrectionForm(), 'advance_form': AdvanceForm(), 'advance_balance': advance_balance(patient.pk), 'advance_moves': patient.advances.select_related('entry')[:15],
        'service_catalog': catalog.catalog_for(profile, member.clinic.owner if member else None),
        'totals': {'billed': sum((b.rate for b in live), Decimal('0')), 'received': sum((b.amount_paid for b in live), Decimal('0')), 'due': sum((b.amount_due for b in live), Decimal('0'))},
    })
    return render(request, 'billing/patient.html', context)
