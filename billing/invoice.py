"""A bill as a document: the printable invoice page, the PDF file, and the links used to send it (WhatsApp, e-mail, share)."""
import io
import re
from urllib.parse import quote

from django.conf import settings
from django.core import signing

SALT = 'billing.invoice'
LINK_DAYS = 90  # how long the link sent to a patient keeps working


def invoice_token(entry):
    return signing.dumps(entry.pk, salt=SALT)


def entry_from_token(token):
    """The bill a shared link points to, or None when the link is wrong or has expired."""
    from .models import BillingEntry
    try:
        pk = signing.loads(token, salt=SALT, max_age=LINK_DAYS * 86400)
    except signing.BadSignature:
        return None
    return BillingEntry.objects.select_related('professional', 'patient').filter(pk=pk).first()


def normalize_phone(raw):
    """Digits only with the country code, ready for wa.me. A local 10-digit number gets DEFAULT_COUNTRY_CODE; '' when unusable."""
    digits = re.sub(r'\D', '', raw or '')
    code = settings.DEFAULT_COUNTRY_CODE
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = code + digits[1:]
    elif len(digits) == 10:
        digits = code + digits
    return digits if 8 <= len(digits) <= 15 else ''


def practice_of(entry):
    p = entry.professional
    return {'name': p.practice_name or p.full_name, 'address': p.practice_address, 'phone': p.practice_phone or p.mobile,
            'person': p.full_name, 'code': p.facility_code}


def share_message(entry, url):
    practice = practice_of(entry)['name']
    owing = f' NPR {entry.amount_due:g} is still due.' if entry.amount_due > 0 and not entry.is_cancelled else ''
    extra = entry.carried_over
    remaining = f' Your extra NPR {extra:g} is kept as advance for your next session.' if extra > 0 and not entry.is_cancelled else ''
    return (f'Hello {entry.patient_name}, your bill {entry.invoice_number} from {practice} dated {entry.entry_date:%d %b %Y}: '
            f'NPR {entry.rate:g}.{owing}{remaining} Invoice: {url}')


def whatsapp_link(entry, phone, url):
    """wa.me opens WhatsApp with the message ready; with no usable number it opens the contact picker instead."""
    number = normalize_phone(phone)
    return f"https://wa.me/{number}?text={quote(share_message(entry, url))}" if number else f"https://wa.me/?text={quote(share_message(entry, url))}"


# ---------------------------------------------------------------- the PDF
def _latin(text, fallback):
    """The built-in PDF fonts cover Latin text only. Anything in another script (for example Devanagari) is kept off the PDF so no
    garbled boxes are printed; the online invoice shows it in full."""
    text = (text or '').strip()
    try:
        text.encode('latin-1')
        return text
    except UnicodeEncodeError:
        return fallback


def build_pdf(entry, online_url=''):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    practice = practice_of(entry)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f'Invoice {entry.invoice_number}')
    c.setAuthor(_latin(practice['name'], 'Sajhya Health'))
    width, height = A4
    left, right = 20 * mm, width - 20 * mm
    green, ink, muted = colors.HexColor('#116b43'), colors.HexColor('#18352b'), colors.HexColor('#6c8178')

    c.setFillColor(green)
    c.rect(0, height - 34 * mm, width, 34 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 18)
    c.drawString(left, height - 16 * mm, _latin(practice['name'], 'Physiotherapy practice'))
    c.setFont('Helvetica', 9.5)
    c.drawString(left, height - 23 * mm, _latin(', '.join(x for x in (practice['address'], practice['phone']) if x), ''))
    c.setFont('Helvetica-Bold', 22)
    c.drawRightString(right, height - 17 * mm, 'INVOICE')
    c.setFont('Helvetica', 9.5)
    c.drawRightString(right, height - 24 * mm, entry.invoice_number)

    y = height - 48 * mm
    c.setFillColor(muted)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(left, y, 'BILLED TO')
    c.drawString(width / 2 + 10 * mm, y, 'INVOICE DETAILS')
    c.setFillColor(ink)
    c.setFont('Helvetica-Bold', 12)
    patient_code = entry.patient.patient_code if entry.patient_id else ''
    c.drawString(left, y - 6 * mm, _latin(entry.patient_name, patient_code or 'Patient'))
    c.setFont('Helvetica', 9.5)
    line = y - 12 * mm
    for text in (' / '.join(x for x in (f'{entry.age} yrs' if entry.age else '', entry.get_sex_display() if entry.sex else '') if x), patient_code, entry.contact_number):
        if text:
            c.drawString(left, line, _latin(text, ''))
            line -= 5 * mm
    c.drawString(width / 2 + 10 * mm, y - 6 * mm, f'Date: {entry.entry_date:%d %b %Y}')
    c.drawString(width / 2 + 10 * mm, y - 11 * mm, f'Status: {entry.status_label}')
    c.drawString(width / 2 + 10 * mm, y - 16 * mm, f'Payment mode: {entry.get_payment_mode_display()}')
    if practice['person']:
        c.drawString(width / 2 + 10 * mm, y - 21 * mm, f"Therapist: {_latin(practice['person'], '')}")

    top = y - 38 * mm
    c.setFillColor(colors.HexColor('#e9f7ef'))
    c.rect(left, top, right - left, 9 * mm, stroke=0, fill=1)
    c.setFillColor(green)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(left + 3 * mm, top + 3 * mm, 'SERVICE')
    c.drawRightString(right - 3 * mm, top + 3 * mm, 'AMOUNT (NPR)')
    c.setFillColor(ink)
    c.setFont('Helvetica', 11)
    c.drawString(left + 3 * mm, top - 6 * mm, _latin(entry.service, 'Service'))
    c.drawRightString(right - 3 * mm, top - 6 * mm, f'{entry.rate:,.2f}')
    if entry.notes and _latin(entry.notes, ''):
        c.setFont('Helvetica', 8.5)
        c.setFillColor(muted)
        c.drawString(left + 3 * mm, top - 11 * mm, _latin(entry.notes, '')[:110])
    c.setStrokeColor(colors.HexColor('#e1ebe5'))
    c.line(left, top - 14 * mm, right, top - 14 * mm)

    ty = top - 24 * mm
    c.setFillColor(ink)
    for label, value, bold in (('Total', entry.rate, True), ('Received', entry.amount_paid, False), ('Balance due', entry.amount_due, True)):
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', 11)
        c.drawString(width / 2 + 10 * mm, ty, label)
        c.drawRightString(right - 3 * mm, ty, f'NPR {value:,.2f}')
        ty -= 7 * mm

    extra = entry.carried_over
    if extra > 0 and not entry.is_cancelled:
        from .models import advance_balance
        c.setFillColor(colors.HexColor('#e7f7ed'))
        c.rect(width / 2 + 7 * mm, ty - 16 * mm, right - width / 2 - 7 * mm, 20 * mm, stroke=0, fill=1)
        c.setFillColor(green)
        c.setFont('Helvetica-Bold', 10)
        c.drawString(width / 2 + 10 * mm, ty - 2 * mm, 'Extra kept as advance')
        c.drawRightString(right - 3 * mm, ty - 2 * mm, f'NPR {extra:,.2f}')
        c.setFont('Helvetica', 8.5)
        c.setFillColor(ink)
        c.drawString(width / 2 + 10 * mm, ty - 8 * mm, f'Cash handed over NPR {entry.cash_handed_over:,.2f}; the extra stays with us')
        c.drawString(width / 2 + 10 * mm, ty - 12.5 * mm, f'for your next session. Advance balance now: NPR {advance_balance(entry.patient_id):,.2f}.')
        ty -= 24 * mm
    payments = list(entry.payments.all())
    if payments:
        py = ty - 4 * mm
        c.setFillColor(muted)
        c.setFont('Helvetica-Bold', 8.5)
        c.drawString(left, py, 'PAYMENTS RECEIVED')
        c.setFillColor(ink)
        c.setFont('Helvetica', 9.5)
        for p in payments[:8]:
            py -= 5.5 * mm
            c.drawString(left, py, f'{p.paid_on:%d %b %Y}  -  {p.get_payment_mode_display()}')
            c.drawRightString(left + 80 * mm, py, f'NPR {p.amount:,.2f}')

    if entry.is_cancelled:
        c.saveState()
        c.setFillColor(colors.HexColor('#b83b3b'))
        c.setFont('Helvetica-Bold', 60)
        c.translate(width / 2, height / 2)
        c.rotate(30)
        c.setFillAlpha(0.18)
        c.drawCentredString(0, 0, 'CANCELLED')
        c.restoreState()

    c.setFillColor(muted)
    c.setFont('Helvetica', 8.5)
    c.drawString(left, 22 * mm, 'Thank you. Please keep this invoice for your records.')
    if online_url:
        c.drawString(left, 17 * mm, f'Online copy: {online_url}')
    c.drawRightString(right, 17 * mm, 'Sajhya Health')
    c.showPage()
    c.save()
    return buf.getvalue()
