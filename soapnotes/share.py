"""A finalised SOAP note as a document the physiotherapist can send to the patient: a PDF file, and a signed link to it that works without signing in.

Like the invoice, the link cannot be guessed and expires. The built-in PDF fonts cover Latin text only, so text in another script (for example Devanagari)
is left out of the PDF with a short pointer; the picture version, drawn by the browser, shows it in full.
"""
import io
from xml.sax.saxutils import escape

from django.core import signing

from . import presets

SALT = 'soapnotes.share'
LINK_DAYS = 30  # a clinical note: shorter than an invoice link


def note_token(note):
    return signing.dumps(note.pk, salt=SALT)


def note_from_token(token):
    """The finalised note a shared link points to, or None when the link is wrong or expired (or the note is no longer final)."""
    from .models import SoapNote
    try:
        pk = signing.loads(token, salt=SALT, max_age=LINK_DAYS * 86400)
    except signing.BadSignature:
        return None
    return SoapNote.objects.select_related('patient', 'author').filter(pk=pk, status=SoapNote.FINAL).first()


def file_name(note):
    return f'SOAP-note-{note.note_date:%Y-%m-%d}-{note.patient.patient_code or note.pk}.pdf'.replace(' ', '-')


def share_message(note, profile, url):
    from accounts import messaging
    values = {**messaging.practice_values(profile), 'patient': note.patient.name, 'date': f'{note.note_date:%d %b %Y}', 'link': url, 'days': LINK_DAYS}
    return messaging.render(messaging.body_for(profile, 'soap_note'), values)


def _latin(text):
    """The text if the PDF fonts can print it, else a pointer to the picture version."""
    text = str(text or '').strip()
    try:
        text.encode('cp1252')
        return text
    except UnicodeEncodeError:
        return '(text in another script: see the picture version)'


def _p(text):
    return escape(_latin(text)).replace('\n', '<br/>')


def _sections(note):
    """[(letter, title, [block, ...])] where a block is ('text', label, value) or ('table', label, header, rows)."""
    flags = dict(presets.RED_FLAGS)
    flag_labels = [flags[k] for k in note.red_flags if k in flags]
    pain = []
    if note.pain_now is not None:
        pain.append(f'now {note.pain_now}/10')
    if note.pain_best is not None:
        pain.append(f'best {note.pain_best}/10')
    if note.pain_worst is not None:
        pain.append(f'worst {note.pain_worst}/10')
    if note.pain_location:
        pain.append(f'location: {note.pain_location}')
    if note.pain_character:
        pain.append(f'character: {note.pain_character}')
    behaviour = ' '.join(x for x in (f'Aggravating: {note.aggravating}.' if note.aggravating else '', f'Easing: {note.easing}.' if note.easing else '',
                                     f'24-hour pattern: {note.pattern_24h}.' if note.pattern_24h else '') if x)

    def T(label, value):
        return ('text', label, value) if value else None

    subjective = [T('Chief complaint', note.chief_complaint), T('Onset / mechanism', note.mechanism), T('Pain', ', '.join(pain)), T('History of present condition', note.history),
                  T('Behaviour of symptoms', behaviour), T('Red flags present', ', '.join(flag_labels)), T('Medical history / medications', note.medical_history),
                  T('Functional limitations', note.functional_limits), T("Patient's goals", note.patient_goals)]
    objective = [T('Observation / posture', note.observation), T('Palpation', note.palpation), T('Vitals', note.vitals)]
    if note.rom:
        objective.append(('table', 'Range of motion', ['Movement', 'Side', 'Active', 'Passive', 'Pain', 'Note'],
                          [[r.get('movement', ''), r.get('side', ''), r.get('active', ''), r.get('passive', ''), 'Yes' if r.get('pain') else '', r.get('note', '')] for r in note.rom]))
    if note.strength:
        objective.append(('table', 'Muscle strength (MMT)', ['Muscle', 'Side', 'Grade'], [[r.get('muscle', ''), r.get('side', ''), r.get('grade', '')] for r in note.strength]))
    objective.append(T('Neurological screen', note.neuro))
    if note.special_tests:
        objective.append(('table', 'Special tests', ['Test', 'Result', 'Note'], [[r.get('name', ''), r.get('result', ''), r.get('note', '')] for r in note.special_tests]))
    objective.append(T('Gait, balance, function', note.gait_function))
    status = ' '.join(x for x in (f'Stage: {note.get_stage_display()}.' if note.stage else '', f'Irritability: {note.get_irritability_display()}.' if note.irritability else '',
                                  f'Prognosis: {note.get_prognosis_display()}.' if note.prognosis else '') if x)
    assessment = [T('Clinical impression', note.impression + (f' [{note.icd10_code}]' if note.icd10_code else '')), T('Status', status), T('Problem list', note.problem_list),
                  T('Contributing factors', note.contributing)]
    freq = ', '.join(x for x in (f'{note.frequency_per_week} session(s) a week' if note.frequency_per_week else '', f'for {note.duration_weeks} weeks' if note.duration_weeks else '',
                                 f'next review {note.next_review:%d %b %Y}' if note.next_review else '') if x)
    plan = [T('Treatment given today', note.treatment_today)]
    if note.measures:
        plan.append(('table', 'Baseline metrics', ['Measure', 'Baseline / now', 'Target'],
                     [[m.get('name', ''), f"{m.get('baseline') or '-'} {m.get('unit', '')}".strip(), f"{m.get('target') or '-'} {m.get('unit', '')}".strip()] for m in note.measures]))
    if note.goals:
        plan.append(('table', 'Clinical goals', ['Goal', 'Term', 'Target date'],
                     [[g.get('text', ''), 'Long-term' if g.get('term') == 'long' else 'Short-term', g.get('target_date') or '-'] for g in note.goals]))
    plan += [T('Frequency and review', freq), T('Home exercise programme', note.hep), T('Education and advice', note.education), T('Precautions', note.precautions), T('Referral', note.referral)]
    out = []
    for letter, title, blocks in (('S', 'Subjective', subjective), ('O', 'Objective', objective), ('A', 'Assessment', assessment), ('P', 'Plan', plan)):
        out.append((letter, title, [b for b in blocks if b]))
    return out


def build_pdf(note, online_url=''):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    green, ink, muted = colors.HexColor('#116b43'), colors.HexColor('#18352b'), colors.HexColor('#6c8178')
    body = ParagraphStyle('b', fontName='Helvetica', fontSize=9.5, leading=13, textColor=ink)
    label = ParagraphStyle('l', parent=body, fontName='Helvetica-Bold', fontSize=8.5, textColor=muted, spaceBefore=5, spaceAfter=1, keepWithNext=1)
    cell = ParagraphStyle('c', parent=body, fontSize=8.8, leading=11.5)
    cellh = ParagraphStyle('ch', parent=cell, fontName='Helvetica-Bold', textColor=colors.white)
    sect = ParagraphStyle('s', parent=body, fontName='Helvetica-Bold', fontSize=12, textColor=green, spaceBefore=10, spaceAfter=3)
    owner = note.author or note.patient.professional  # whose practice details head the document
    practice = {'name': owner.practice_name or owner.full_name, 'address': owner.practice_address, 'phone': owner.practice_phone or owner.mobile, 'person': owner.full_name}
    author = note.author_name or practice['person']

    def page(canvas, doc):
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(green)
        canvas.rect(0, height - 24 * mm, width, 24 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 15)
        canvas.drawString(18 * mm, height - 12 * mm, _latin(practice['name']) if _latin(practice['name']) != '(text in another script: see the picture version)' else 'Physiotherapy practice')
        canvas.setFont('Helvetica', 9)
        contact = ', '.join(x for x in (practice['address'], practice['phone']) if x)
        canvas.drawString(18 * mm, height - 18 * mm, contact if _latin(contact) == contact else '')
        canvas.setFont('Helvetica-Bold', 13)
        canvas.drawRightString(width - 18 * mm, height - 12 * mm, 'SOAP NOTE')
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(width - 18 * mm, height - 18 * mm, note.get_note_type_display())
        canvas.setFillColor(muted)
        canvas.setFont('Helvetica', 7.5)
        canvas.drawString(18 * mm, 10 * mm, f'{note.patient.name if _latin(note.patient.name) == note.patient.name else note.patient.patient_code} - finalised {note.finalized_at:%d %b %Y}' if note.finalized_at else 'Sajhya Health')
        canvas.drawRightString(width - 18 * mm, 10 * mm, f'Page {doc.page}')
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=30 * mm, bottomMargin=16 * mm, title=f'SOAP note {note.note_date:%d %b %Y}',
                            author=_latin(author)[:80])
    story = []
    patient = note.patient
    meta = [[Paragraph(f'<b>Patient</b><br/>{_p(patient.name)}<br/>ID {_p(patient.patient_code)}', body),
             Paragraph(f'<b>Date</b><br/>{note.note_date:%d %b %Y}<br/>{_p(note.get_note_type_display())}', body),
             Paragraph(f'<b>Physiotherapist</b><br/>{_p(author)}', body)]]
    mt = Table(meta, colWidths=[62 * mm, 55 * mm, 55 * mm])
    mt.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f3f9f5')), ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cfe0d6')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6), ('LEFTPADDING', (0, 0), (-1, -1), 8)]))
    story += [mt]
    for letter, title, blocks in _sections(note):
        if not blocks:
            continue
        story.append(Paragraph(f'{letter} - {title}', sect))
        for block in blocks:
            if block[0] == 'text':
                story += [Paragraph(escape(block[1].upper()), label), Paragraph(_p(block[2]), body)]
            else:
                _, name, head, rows = block
                data = [[Paragraph(escape(h), cellh) for h in head]] + [[Paragraph(_p(c), cell) for c in row] for row in rows]
                t = Table(data, colWidths=[(174 * mm) / len(head)] * len(head), repeatRows=1)
                t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), green), ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cfe0d6')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                       ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
                story += [Paragraph(escape(name.upper()), label), t, Spacer(1, 3)]
    addenda = list(note.addenda.all())
    if addenda:
        story.append(Paragraph('Addenda', sect))
        for a in addenda:
            story += [Paragraph(_p(a.text), body), Paragraph(f'{_p(a.author_name)} - {a.created_at:%d %b %Y %H:%M}', ParagraphStyle('ad', parent=body, fontSize=8, textColor=muted)), Spacer(1, 3)]
    story.append(Spacer(1, 8))
    story.append(Paragraph('This note is confidential and was prepared for the patient named above. ' + (f'Online copy: {escape(online_url)}' if online_url else ''), ParagraphStyle('f', parent=body, fontSize=8, textColor=muted)))
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()


def email_html(note, profile, url, message):
    """The e-mail body as a designed page: a header band with the practice, a greeting, a button to the PDF, and the confidentiality note.
    Inline styles only, because mail programs ignore style sheets. The plain-text message is sent alongside as the fallback."""
    name = escape(profile.practice_name or profile.full_name)
    sub = escape(' · '.join(x for x in (profile.practice_address, profile.practice_phone or profile.mobile) if x))
    body = escape(message).replace('\n', '<br>')
    link = escape(url, {'"': '&quot;'})
    return (
        '<div style="background:#f3f7f4;padding:24px 12px;font-family:Arial,Helvetica,sans-serif;color:#18352b">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #d7e6dc">'
        f'<tr><td style="background:#116b43;padding:20px 24px;color:#ffffff"><div style="font-size:19px;font-weight:bold">{name}</div>'
        f'<div style="font-size:12px;opacity:.9;margin-top:3px">{sub}</div></td></tr>'
        '<tr><td style="padding:22px 24px 6px">'
        '<div style="font-size:11px;letter-spacing:.06em;color:#6c8178;font-weight:bold;text-transform:uppercase">Your physiotherapy note</div>'
        f'<div style="font-size:16px;font-weight:bold;margin:4px 0 12px">{escape(note.patient.name)} &middot; {note.note_date:%d %b %Y}</div>'
        f'<div style="font-size:14px;line-height:1.6">{body}</div></td></tr>'
        f'<tr><td style="padding:12px 24px 8px"><a href="{link}" style="display:inline-block;background:#116b43;color:#ffffff;text-decoration:none;font-weight:bold;font-size:14px;padding:11px 20px;border-radius:8px">Open the note (PDF)</a></td></tr>'
        f'<tr><td style="padding:6px 24px 20px;font-size:12px;color:#6c8178;line-height:1.5">The note is also attached to this e-mail as a PDF. The link works for {LINK_DAYS} days.<br>'
        'This e-mail is confidential and was prepared for the patient named above. If it reached you by mistake, please delete it.</td></tr>'
        '</table></div>')
