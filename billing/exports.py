"""Billing as a spreadsheet: the same rows feed the on-screen sheet and the Excel / CSV downloads, so what you see is what you export.

A "scope" says whose money this is (a professional's or clinic login's own workspace, or one clinic's front desk); the filters (period, status,
payment mode, search) are read from the query string by `Filters`.
"""
import csv
import datetime
import io
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import ADVANCE, BillingEntry, EntryPayment, PatientAdvance, PatientPackage

MAX_SHEET_ROWS = 2000     # rows shown in the browser (the download has no such limit)
MAX_EXPORT_ROWS = 50000
STATUSES = [('', 'All statuses'), ('paid', 'Paid'), ('partial', 'Part paid'), ('due', 'Due (credit)'), ('unpaid', 'Any balance due'), ('cancelled', 'Cancelled')]
MODES = [('', 'All payment modes'), ('cash', 'Cash'), ('card', 'Card'), ('online', 'Online'), ('other', 'Other')]

BILL_COLUMNS = [  # (header, width, key)
    ('Date', 12, 'date'), ('Invoice', 16, 'invoice'), ('Patient', 26, 'patient'), ('Patient ID', 20, 'code'), ('Phone', 15, 'phone'), ('Service', 22, 'service'),
    ('Amount (NPR)', 14, 'amount'), ('Received (NPR)', 15, 'received'), ('Due (NPR)', 12, 'due'), ('Status', 12, 'status'), ('Payment mode', 14, 'mode'),
    ('Kept as advance (NPR)', 20, 'carried'), ('Billed by', 22, 'billed_by'), ('Notes', 30, 'notes'),
]
NUMERIC = {'amount', 'received', 'due', 'carried'}


@dataclass
class Scope:
    """Which bills, payments, advances and packages belong to this export."""
    entries: object
    payments: object
    advances: object
    packages: object
    show_phone: bool = True
    phone_fallback: bool = False  # also use the patient record's number when the bill has none (only where the viewer may see contact details)
    title: str = 'Billing'


def profile_scope(profile, can_see_phone=True):
    """A professional's (or a clinic login's) own books. Phone numbers come from the bills themselves, which were only given a number
    the biller was allowed to see."""
    return Scope(entries=BillingEntry.objects.filter(professional=profile), payments=EntryPayment.objects.filter(entry__professional=profile),
                 advances=PatientAdvance.objects.filter(professional=profile), packages=PatientPackage.objects.filter(professional=profile),
                 show_phone=can_see_phone, title=profile.practice_name or profile.full_name)


def clinic_scope(clinic, can_see_phone=True):
    """The front desk's view: every bill of the clinic's patients, whoever keeps the books."""
    return Scope(entries=BillingEntry.objects.filter(patient__clinic=clinic), payments=EntryPayment.objects.filter(entry__patient__clinic=clinic),
                 advances=PatientAdvance.objects.filter(patient__clinic=clinic), packages=PatientPackage.objects.filter(patient__clinic=clinic),
                 show_phone=can_see_phone, phone_fallback=can_see_phone, title=clinic.name)


@dataclass
class Filters:
    start: datetime.date
    end: datetime.date
    status: str = ''
    mode: str = ''
    q: str = ''

    @classmethod
    def from_query(cls, query):
        today = timezone.localdate()

        def day(name, default):
            try:
                return datetime.date.fromisoformat(query.get(name, ''))
            except ValueError:
                return default
        start, end = day('from', today.replace(day=1)), day('to', today)
        if end < start:
            start, end = end, start
        return cls(start, end, query.get('status', '') if query.get('status', '') in dict(STATUSES) else '', query.get('mode', '') if query.get('mode', '') in dict(MODES) else '',
                   (query.get('q') or '').strip()[:100])

    def querystring(self):
        parts = {'from': self.start.isoformat(), 'to': self.end.isoformat(), 'status': self.status, 'mode': self.mode, 'q': self.q}
        from urllib.parse import urlencode
        return urlencode({k: v for k, v in parts.items() if v})


def bills(scope, f):
    """The filtered bills, oldest first, as a queryset."""
    qs = scope.entries.filter(entry_date__gte=f.start, entry_date__lte=f.end).select_related('patient').prefetch_related('payments', 'advance_moves')
    if f.status == 'cancelled':
        qs = qs.filter(cancelled_at__isnull=False)
    elif f.status:
        qs = qs.filter(cancelled_at__isnull=True)
        if f.status == 'paid':
            qs = qs.filter(amount_paid__gte=F('rate'))
        elif f.status == 'partial':
            qs = qs.filter(amount_paid__gt=0, amount_paid__lt=F('rate'))
        elif f.status == 'due':
            qs = qs.filter(amount_paid=0)
        elif f.status == 'unpaid':
            qs = qs.filter(amount_paid__lt=F('rate'))
    if f.mode:
        qs = qs.filter(payment_mode=f.mode)
    if f.q:
        qs = qs.filter(Q(patient_name__icontains=f.q) | Q(invoice_number__icontains=f.q) | Q(contact_number__icontains=f.q) | Q(service__icontains=f.q)
                       | Q(patient__patient_code__icontains=f.q) | Q(created_by_name__icontains=f.q))
    return qs.order_by('entry_date', 'created_at', 'id')


def bill_row(e, scope):
    """One bill as the values of BILL_COLUMNS."""
    phone = e.contact_number if scope.show_phone else ''
    if not phone and scope.show_phone and scope.phone_fallback and e.patient_id:
        phone = e.patient.phone
    return {
        'date': e.entry_date, 'invoice': e.invoice_number, 'patient': e.patient_name, 'code': e.patient.patient_code if e.patient_id else '',
        'phone': phone, 'service': e.service,
        'amount': e.rate, 'received': e.amount_paid, 'due': e.amount_due, 'status': e.status_label, 'mode': e.get_payment_mode_display(),
        'carried': e.carried_over, 'billed_by': ' / '.join(x for x in (e.created_by_name, e.created_by_role) if x), 'notes': e.notes,
    }


def totals(rows):
    live = [r for r in rows if r['status'] != 'Cancelled']
    return {'count': len(rows), 'amount': sum((r['amount'] for r in live), Decimal('0')), 'received': sum((r['received'] for r in live), Decimal('0')),
            'due': sum((r['due'] for r in live), Decimal('0')), 'carried': sum((r['carried'] for r in live), Decimal('0'))}


def sheet_rows(scope, f, limit=MAX_SHEET_ROWS):
    rows = [bill_row(e, scope) for e in bills(scope, f)[:limit]]
    return rows


# ---------------------------------------------------------------- Excel / CSV
def _put(ws, row, col, value, number_format=None, bold=False):
    from openpyxl.styles import Font
    cell = ws.cell(row=row, column=col)
    cell.value = value
    if isinstance(value, str):
        cell.data_type = 's'  # always text, never a formula, whatever the text starts with
    if number_format:
        cell.number_format = number_format
    if bold:
        cell.font = Font(bold=True)
    return cell


def _header(ws, headers, widths):
    from openpyxl.styles import Alignment, Font, PatternFill
    for i, (head, width) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=i, value=head)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='116B43')
        cell.alignment = Alignment(vertical='center', wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{ws.cell(row=1, column=len(headers)).column_letter}1'


MONEY = '#,##0.00'
DAY = 'yyyy-mm-dd'


def build_workbook(scope, f):
    """The Excel file: Bills (filtered), Payments received, Advances, Packages and a Summary. Returns bytes."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Bills'
    _header(ws, [h for h, _, _ in BILL_COLUMNS], [w for _, w, _ in BILL_COLUMNS])
    rows = [bill_row(e, scope) for e in bills(scope, f)[:MAX_EXPORT_ROWS]]
    for r, row in enumerate(rows, 2):
        for c, (_, _, key) in enumerate(BILL_COLUMNS, 1):
            _put(ws, r, c, row[key], MONEY if key in NUMERIC else DAY if key == 'date' else None)
    last = len(rows) + 1
    if rows:  # SUBTOTAL follows the filter the reader applies inside Excel
        _put(ws, last + 1, 6, 'Total (shown rows)', bold=True)
        for c, (_, _, key) in enumerate(BILL_COLUMNS, 1):
            if key in NUMERIC:
                letter = ws.cell(row=1, column=c).column_letter
                _put(ws, last + 1, c, f'=SUBTOTAL(109,{letter}2:{letter}{last})', MONEY, bold=True)

    pay = wb.create_sheet('Payments received')
    _header(pay, ['Date received', 'Invoice', 'Patient', 'Amount (NPR)', 'Mode', 'Notes'], [14, 16, 26, 14, 16, 30])
    payments = (scope.payments.filter(paid_on__gte=f.start, paid_on__lte=f.end, entry__cancelled_at__isnull=True).select_related('entry').order_by('paid_on', 'id')[:MAX_EXPORT_ROWS])
    pr = 2
    for p in payments:
        for c, (value, fmt) in enumerate(((p.paid_on, DAY), (p.entry.invoice_number, None), (p.entry.patient_name, None), (p.amount, MONEY),
                                           ('From advance (not new money)' if p.payment_mode == ADVANCE else p.get_payment_mode_display(), None), (p.notes, None)), 1):
            _put(pay, pr, c, value, fmt)
        pr += 1

    adv = wb.create_sheet('Advances')
    _header(adv, ['Date', 'Patient', 'Patient ID', 'Activity', 'Amount (NPR)', 'Invoice / mode', 'Notes'], [12, 26, 20, 22, 14, 20, 30])
    moves = scope.advances.filter(paid_on__gte=f.start, paid_on__lte=f.end).select_related('patient', 'entry').order_by('paid_on', 'created_at', 'id')[:MAX_EXPORT_ROWS]
    ar = 2
    for m in moves:
        for c, (value, fmt) in enumerate(((m.paid_on, DAY), (m.patient.name, None), (m.patient.patient_code or '', None), (m.get_kind_display(), None), (m.amount, MONEY),
                                           (m.entry.invoice_number if m.entry_id else m.get_payment_mode_display() if m.payment_mode else '', None), (m.notes, None)), 1):
            _put(adv, ar, c, value, fmt)
        ar += 1

    pk = wb.create_sheet('Packages')
    _header(pk, ['Started', 'Patient', 'Patient ID', 'Length', 'Sessions used', 'Sessions total', 'Price (NPR)', 'Paid (NPR)', 'Due (NPR)', 'Status'], [12, 26, 20, 12, 13, 13, 13, 13, 13, 12])
    for r, p in enumerate(scope.packages.select_related('patient').order_by('-start_date', '-id')[:MAX_EXPORT_ROWS], 2):
        for c, (value, fmt) in enumerate(((p.start_date, DAY), (p.patient.name, None), (p.patient.patient_code or '', None), (p.get_duration_display(), None), (p.sessions_used, None),
                                           (p.total_sessions, None), (p.total_amount, MONEY), (p.amount_paid, MONEY), (p.amount_due, MONEY), (p.effective_status_display, None)), 1):
            _put(pk, r, c, value, fmt)

    summary = wb.create_sheet('Summary', 0)
    t = totals(rows)
    _put(summary, 1, 1, scope.title, bold=True)
    _put(summary, 2, 1, f'Billing from {f.start:%d %b %Y} to {f.end:%d %b %Y}' + (f' - status: {dict(STATUSES)[f.status]}' if f.status else '') + (f' - mode: {dict(MODES)[f.mode]}' if f.mode else '') + (f' - search: {f.q}' if f.q else ''))
    for r, (label, value) in enumerate((('Bills', t['count']), ('Billed (NPR)', t['amount']), ('Received on these bills (NPR)', t['received']), ('Still due on these bills (NPR)', t['due']),
                                         ('Extra kept as advance (NPR)', t['carried'])), 4):
        _put(summary, r, 1, label, bold=True)
        _put(summary, r, 2, value, MONEY if r > 4 else None)
    received = scope.payments.filter(paid_on__gte=f.start, paid_on__lte=f.end, entry__cancelled_at__isnull=True).exclude(payment_mode=ADVANCE)
    by_mode = {}
    for mode, amount in received.values_list('payment_mode', 'amount'):
        by_mode[mode] = by_mode.get(mode, Decimal('0')) + amount
    for mode, amount in scope.advances.filter(paid_on__gte=f.start, paid_on__lte=f.end, kind__in=[PatientAdvance.DEPOSIT, PatientAdvance.REFUND]).values_list('payment_mode', 'amount'):
        by_mode[mode or 'cash'] = by_mode.get(mode or 'cash', Decimal('0')) + amount
    _put(summary, 10, 1, 'Money received in the period, by mode (bills and advances, refunds taken off)', bold=True)
    names = dict(MODES)
    for r, (mode, amount) in enumerate(sorted(by_mode.items()), 11):
        _put(summary, r, 1, names.get(mode, mode))
        _put(summary, r, 2, amount, MONEY)
    _put(summary, 11 + len(by_mode), 1, 'Total received', bold=True)
    _put(summary, 11 + len(by_mode), 2, sum(by_mode.values(), Decimal('0')), MONEY, bold=True)
    summary.column_dimensions['A'].width = 62
    summary.column_dimensions['B'].width = 18

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build_csv(scope, f):
    """The bills as CSV (UTF-8 with a byte-order mark so Excel shows Nepali text correctly)."""
    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out)
    writer.writerow([h for h, _, _ in BILL_COLUMNS])
    for e in bills(scope, f)[:MAX_EXPORT_ROWS]:
        row = bill_row(e, scope)
        writer.writerow([_csv_safe(row[key]) for _, _, key in BILL_COLUMNS])
    return out.getvalue().encode('utf-8')


def _csv_safe(value):
    """A CSV cell starting with = + - @ is run as a formula by Excel: prefix an apostrophe so it stays text."""
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value
