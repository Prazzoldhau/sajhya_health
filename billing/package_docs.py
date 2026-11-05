"""A package as documents: the package invoice (price, payments, balance, sessions used) and a receipt for each payment.

They are sent like the bill invoice: a PDF, a picture drawn by the browser, a message with a signed link, and e-mail. The link is signed, cannot be
guessed and expires. The built-in PDF fonts print Latin text only, so text in another script is replaced by a pointer to the picture version.
"""
import io
from decimal import Decimal
from xml.sax.saxutils import escape

from django.core import signing

LINK_DAYS = 90
SALT_INVOICE = 'billing.package.invoice'
SALT_RECEIPT = 'billing.package.receipt'


def invoice_token(package):
    return signing.dumps(package.pk, salt=SALT_INVOICE)


def receipt_token(payment):
    return signing.dumps(payment.pk, salt=SALT_RECEIPT)


def package_from_token(token):
    from .models import PatientPackage
    try:
        pk = signing.loads(token, salt=SALT_INVOICE, max_age=LINK_DAYS * 86400)
    except signing.BadSignature:
        return None
    return PatientPackage.objects.select_related('professional', 'patient').filter(pk=pk).first()


def payment_from_token(token):
    from .models import PackagePayment
    try:
        pk = signing.loads(token, salt=SALT_RECEIPT, max_age=LINK_DAYS * 86400)
    except signing.BadSignature:
        return None
    return PackagePayment.objects.select_related('package__professional', 'package__patient').filter(pk=pk).first()


def practice_of(profile):
    return {'name': profile.practice_name or profile.full_name, 'address': profile.practice_address, 'phone': profile.practice_phone or profile.mobile,
            'whatsapp': profile.whatsapp_number, 'person': profile.full_name}


def _latin(text, fallback='(see the picture version)'):
    text = str(text or '').strip()
    try:
        text.encode('cp1252')
        return text
    except UnicodeEncodeError:
        return fallback


def _p(text):
    return escape(_latin(text)).replace('\n', '<br/>')


def invoice_message(package, url):
    from accounts import messaging
    p = package.professional
    values = {**messaging.practice_values(p), 'patient': package.patient.name, 'invoice': package.invoice_number, 'date': f'{package.created_at:%d %b %Y}', 'amount': f'{package.total_amount:g}',
              'due_line': f'NPR {package.amount_due:g} is still due.' if package.amount_due > 0 else 'The package is fully paid.', 'package': f'{package.get_duration_display()} package, {package.total_sessions} sessions',
              'link': url, 'days': LINK_DAYS}
    return messaging.render(messaging.body_for(p, 'package_invoice'), values)


def receipt_message(payment, url):
    from accounts import messaging
    package = payment.package
    p = package.professional
    values = {**messaging.practice_values(p), 'patient': package.patient.name, 'invoice': payment.receipt_number, 'date': f'{payment.created_at:%d %b %Y}', 'amount': f'{payment.amount:g}',
              'due_line': f'NPR {package.amount_due:g} is still due on the package.' if package.amount_due > 0 else 'The package is now fully paid.',
              'package': f'{package.get_duration_display()} package', 'link': url, 'days': LINK_DAYS}
    return messaging.render(messaging.body_for(p, 'package_receipt'), values)


def balance_after(payment):
    """What was still due on the package right after this payment (payments are in the order they were made)."""
    package = payment.package
    paid = sum((p.amount for p in package.payments.all() if (p.created_at, p.pk) <= (payment.created_at, payment.pk)), Decimal('0'))
    return max(Decimal('0'), package.total_amount - paid), paid


def invoice_lines(package):
    """[(label, text)] facts for the package invoice."""
    return [('Package', f'{package.get_duration_display()}, {package.total_sessions} sessions'), ('Valid', f'{package.start_date:%d %b %Y} to {package.end_date:%d %b %Y}'),
            ('Sessions used', f'{package.sessions_used} of {package.total_sessions}'), ('Status', package.effective_status_display)]


# ---------------------------------------------------------------- PDF
def _build(title, number, practice, patient_block, rows, totals, payments_title, payments, note, online_url, label='INVOICE', stamp=''):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    green, ink, muted = colors.HexColor('#116b43'), colors.HexColor('#18352b'), colors.HexColor('#6c8178')
    body = ParagraphStyle('b', fontName='Helvetica', fontSize=10, leading=14, textColor=ink)
    small = ParagraphStyle('s', parent=body, fontSize=8.5, leading=11, textColor=muted)
    bold = ParagraphStyle('bb', parent=body, fontName='Helvetica-Bold')
    head = ParagraphStyle('h', parent=body, fontName='Helvetica-Bold', fontSize=8.5, textColor=muted)
    name = _latin(practice['name'], 'Physiotherapy practice')

    def page(canvas, doc):
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(green)
        canvas.rect(0, height - 32 * mm, width, 32 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 17)
        canvas.drawString(20 * mm, height - 15 * mm, name)
        canvas.setFont('Helvetica', 9.5)
        contact = ', '.join(x for x in (practice['address'], practice['phone'], f"WhatsApp {practice['whatsapp']}" if practice['whatsapp'] else '') if x)
        canvas.drawString(20 * mm, height - 22 * mm, contact if _latin(contact, '') == contact else '')
        canvas.setFont('Helvetica-Bold', 20)
        canvas.drawRightString(width - 20 * mm, height - 16 * mm, label)
        canvas.setFont('Helvetica', 9.5)
        canvas.drawRightString(width - 20 * mm, height - 23 * mm, number)
        canvas.setFillColor(muted)
        canvas.setFont('Helvetica', 8.5)
        canvas.drawString(20 * mm, 14 * mm, 'Thank you. Please keep this for your records.' + (f'   Online copy: {online_url}' if online_url else ''))
        canvas.drawRightString(width - 20 * mm, 14 * mm, 'Sajhya Health')
        if stamp:
            canvas.setFillColor(colors.HexColor('#b83b3b'))
            canvas.setFillAlpha(0.15)
            canvas.setFont('Helvetica-Bold', 60)
            canvas.translate(width / 2, height / 2)
            canvas.rotate(30)
            canvas.drawCentredString(0, 0, stamp)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=40 * mm, bottomMargin=22 * mm, title=title, author=name[:80])
    story = []
    meta = Table([[Paragraph(patient_block, body), Paragraph('<br/>'.join(f'{escape(k)}: <b>{_p(v)}</b>' for k, v in rows), body)]], colWidths=[85 * mm, 85 * mm])
    meta.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    story += [meta, Spacer(1, 6 * mm)]
    tt = Table([[Paragraph(f'<b>{escape(k)}</b>', body), Paragraph(_p(v), ParagraphStyle('r', parent=body, alignment=2, fontName='Helvetica-Bold'))] for k, v in totals], colWidths=[110 * mm, 60 * mm])
    tt.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9f7ef')), ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor('#dfe9e2')),
                            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    story += [tt]
    if payments:
        story += [Spacer(1, 6 * mm), Paragraph(escape(payments_title.upper()), head)]
        pt = Table([[Paragraph(_p(a), body), Paragraph(_p(b), body), Paragraph(_p(c), ParagraphStyle('pr', parent=body, alignment=2))] for a, b, c in payments], colWidths=[40 * mm, 80 * mm, 50 * mm])
        pt.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#e1ebe5')), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
        story += [pt]
    if note:
        story += [Spacer(1, 6 * mm), Paragraph(_p(note), small)]
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()


def build_invoice_pdf(package, online_url=''):
    practice = practice_of(package.professional)
    patient = package.patient
    block = f'<font color="#6c8178" size="8"><b>BILLED TO</b></font><br/><b>{_p(patient.name)}</b><br/>Patient ID {_p(patient.patient_code)}'
    rows = [('Date', f'{package.created_at:%d %b %Y}')] + invoice_lines(package)[:3]
    payments = [(f'{p.created_at:%d %b %Y}', f'{p.get_payment_mode_display()}' + (f' - {p.notes}' if p.notes else '') + f'  ({p.receipt_number})', f'NPR {p.amount:,.2f}') for p in sorted(package.payments.all(), key=lambda x: (x.created_at, x.pk))]
    totals = [('Package price', f'NPR {package.total_amount:,.2f}'), ('Received', f'NPR {package.amount_paid:,.2f}'),
              ('Balance due', f'NPR {package.amount_due:,.2f}' if package.amount_due > 0 else 'Fully paid')]
    note = package.notes
    return _build(f'Package invoice {package.invoice_number}', package.invoice_number, practice, block, rows, totals, 'Payments received', payments, note, online_url,
                  stamp='CANCELLED' if package.status == package.CANCELLED else '')


def build_receipt_pdf(payment, online_url=''):
    package = payment.package
    practice = practice_of(package.professional)
    patient = package.patient
    due, paid = balance_after(payment)
    block = f'<font color="#6c8178" size="8"><b>RECEIVED FROM</b></font><br/><b>{_p(patient.name)}</b><br/>Patient ID {_p(patient.patient_code)}'
    rows = [('Date', f'{payment.created_at:%d %b %Y}'), ('Paid by', payment.get_payment_mode_display()), ('Package', f'{package.get_duration_display()}, {package.total_sessions} sessions'),
            ('Package invoice', package.invoice_number)]
    totals = [('Amount received', f'NPR {payment.amount:,.2f}'), ('Total paid on this package so far', f'NPR {paid:,.2f}'),
              ('Balance due after this payment', f'NPR {due:,.2f}' if due > 0 else 'Fully paid')]
    return _build(f'Payment receipt {payment.receipt_number}', payment.receipt_number, practice, block, rows, totals, '', [], payment.notes, online_url, label='RECEIPT')
