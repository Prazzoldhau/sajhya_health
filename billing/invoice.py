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
    return {'name': p.practice_name or p.full_name, 'address': p.practice_address, 'phone': p.practice_phone or p.mobile, 'whatsapp': p.whatsapp_number,
            'person': p.full_name, 'code': p.facility_code}


def share_message(entry, url):
    """The text that goes with the invoice, in the professional's own wording (see Messages > Bill / invoice message)."""
    from accounts import messaging
    p = entry.professional
    live = not entry.is_cancelled
    values = {**messaging.practice_values(p), 'patient': entry.patient_name, 'invoice': entry.invoice_number, 'date': f'{entry.entry_date:%d %b %Y}',
              'amount': f'{entry.rate:g}', 'link': url,
              'due_line': f'NPR {entry.amount_due:g} is still due.' if entry.amount_due > 0 and live else '',
              'extra_line': f'Your extra NPR {entry.carried_over:g} is kept as advance for your next session.' if live and entry.carried_over > 0 else ''}
    return messaging.render(messaging.body_for(p, 'bill'), values)


def whatsapp_chat(phone):
    """The bare WhatsApp chat with this number (no message), for sending the invoice as a picture."""
    number = normalize_phone(phone)
    return f'https://wa.me/{number}' if number else 'https://web.whatsapp.com/'


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
    c.drawString(left, height - 23 * mm, _latin(', '.join(x for x in (practice['address'], practice['phone'], f"WhatsApp {practice['whatsapp']}" if practice['whatsapp'] else '') if x), ''))
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


# ---------------------------------------------------------------- the picture (server-side, used when the browser cannot draw it)
def _font(bold, size):
    import os

    import reportlab
    from PIL import ImageFont
    path = os.path.join(os.path.dirname(reportlab.__file__), 'fonts', 'VeraBd.ttf' if bold else 'Vera.ttf')
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size=size)


def build_png(entry):
    """The invoice as a PNG. Same content as the PDF (Latin text only; text in another script is left to the online invoice)."""
    from PIL import Image, ImageDraw

    from .models import advance_balance
    practice = practice_of(entry)
    W, pad = 1000, 50
    green, ink, muted, soft = (17, 107, 67), (24, 53, 43), (108, 129, 120), (233, 247, 239)
    code = entry.patient.patient_code if entry.patient_id else ''
    lines_right = [f'Date: {entry.entry_date:%d %b %Y}', f'Status: {entry.status_label}', f'Payment mode: {entry.get_payment_mode_display()}']
    extra = entry.carried_over if not entry.is_cancelled else 0
    payments = list(entry.payments.all())[:8]
    H = 660 + (110 if extra > 0 else 0) + (50 + 32 * len(payments) if payments else 0)
    img = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 120], fill=green)
    d.text((pad, 28), _latin(practice['name'], 'Physiotherapy practice'), font=_font(True, 34), fill='white')
    d.text((pad, 74), _latin(', '.join(x for x in (practice['address'], practice['phone'], f"WhatsApp {practice['whatsapp']}" if practice['whatsapp'] else '') if x), ''), font=_font(False, 20), fill='white')
    d.text((W - pad, 30), 'INVOICE', font=_font(True, 36), fill='white', anchor='ra')
    d.text((W - pad, 78), entry.invoice_number, font=_font(False, 22), fill='white', anchor='ra')
    y = 160
    d.text((pad, y), 'BILLED TO', font=_font(True, 16), fill=muted)
    d.text((W // 2 + 40, y), 'INVOICE DETAILS', font=_font(True, 16), fill=muted)
    d.text((pad, y + 28), _latin(entry.patient_name, code or 'Patient'), font=_font(True, 26), fill=ink)
    sub = ' / '.join(x for x in (f'{entry.age} yrs' if entry.age else '', entry.get_sex_display() if entry.sex else '', code) if x)
    d.text((pad, y + 66), _latin(sub, ''), font=_font(False, 20), fill=ink)
    for i, text in enumerate(lines_right):
        d.text((W // 2 + 40, y + 28 + i * 30), text, font=_font(False, 21), fill=ink)
    y += 150
    d.rectangle([pad, y, W - pad, y + 46], fill=soft)
    d.text((pad + 14, y + 12), 'SERVICE', font=_font(True, 18), fill=green)
    d.text((W - pad - 14, y + 12), 'AMOUNT (NPR)', font=_font(True, 18), fill=green, anchor='ra')
    d.text((pad + 14, y + 66), _latin(entry.service, 'Service'), font=_font(False, 24), fill=ink)
    d.text((W - pad - 14, y + 66), f'{entry.rate:,.2f}', font=_font(False, 24), fill=ink, anchor='ra')
    d.line([pad, y + 110, W - pad, y + 110], fill=(225, 235, 229), width=2)
    y += 140
    for label, value, bold in (('Total', entry.rate, True), ('Received', entry.amount_paid, False), ('Balance due', entry.amount_due, True)):
        d.text((W // 2 + 40, y), label, font=_font(bold, 24), fill=ink)
        d.text((W - pad - 14, y), f'NPR {value:,.2f}', font=_font(bold, 24), fill=ink, anchor='ra')
        y += 40
    if extra > 0:
        y += 10
        d.rectangle([W // 2 - 80, y, W - pad, y + 96], fill=(231, 247, 237))
        d.text((W // 2 - 60, y + 12), 'Extra kept as advance', font=_font(True, 22), fill=green)
        d.text((W - pad - 14, y + 12), f'NPR {extra:,.2f}', font=_font(True, 22), fill=green, anchor='ra')
        d.text((W // 2 - 60, y + 46), f'Cash handed over NPR {entry.cash_handed_over:,.2f}; the extra stays with us', font=_font(False, 16), fill=ink)
        d.text((W // 2 - 60, y + 68), f'for your next session. Advance balance: NPR {advance_balance(entry.patient_id):,.2f}.', font=_font(False, 16), fill=ink)
        y += 110
    if payments:
        y += 14
        d.text((pad, y), 'PAYMENTS RECEIVED', font=_font(True, 16), fill=muted)
        for p in payments:
            y += 32
            d.text((pad, y), f'{p.paid_on:%d %b %Y}  -  {p.get_payment_mode_display()}', font=_font(False, 20), fill=ink)
            d.text((pad + 420, y), f'NPR {p.amount:,.2f}', font=_font(False, 20), fill=ink, anchor='ra')
    d.text((pad, H - 50), 'Thank you. Please keep this invoice for your records.', font=_font(False, 18), fill=muted)
    d.text((W - pad, H - 50), 'Sajhya Health', font=_font(False, 18), fill=muted, anchor='ra')
    if entry.is_cancelled:
        d.text((W // 2, H // 2), 'CANCELLED', font=_font(True, 120), fill=(240, 205, 205), anchor='mm')
    out = io.BytesIO()
    img.save(out, 'PNG')
    return out.getvalue()
