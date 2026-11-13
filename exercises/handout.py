"""A prescribed home exercise programme as a patient handout: a PDF with the pictures of every exercise, the instructions in English and Nepali as stored
in the exercise library, the dose and the times of day, and a signed link that works without signing in (it cannot be guessed and it expires).

The handout follows the PEMAT-A/V principles for patient material, so it reads the same way for every patient:
purpose stated first, plain everyday words, one exercise per page with a clear header, short steps in a logical order, pictures that match the steps,
the action addressed to "you", a summary of the plan at the start and a tick chart and contact details at the end.

Nepali needs text shaping (letters join and reorder), which the built-in PDF fonts cannot do: the PDF is written with fpdf2 and uharfbuzz and the
Noto Sans Devanagari font in static/fonts (SIL Open Font License).
"""
import io
import re
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.utils import timezone

SALT = 'exercises.handout'
LINK_DAYS = 90
FONTS = Path(settings.BASE_DIR) / 'static' / 'fonts'
STATIC = Path(settings.BASE_DIR) / 'static'

GREEN, DARK, MUTED, SOFT, AMBER_SOFT = (22, 134, 83), (15, 92, 57), (93, 117, 104), (244, 250, 246), (255, 246, 222)

# ---- the fixed wording, English and Nepali (drafted for plain reading; have a Nepali-speaking clinician check it before wide use)
TITLE = ('Your home exercise programme', 'तपाईंको घरमा गर्ने व्यायाम कार्यक्रम')
PURPOSE = ('These exercises were chosen for you. Doing them regularly helps you move more easily and eases pain and stiffness.',
           'यी व्यायामहरू तपाईंका लागि छानिएका हुन्। नियमित गर्नाले चलफल सजिलो हुन्छ र दुखाइ र कडापन कम हुन्छ।')
FOR = ('This programme is for:', 'यो कार्यक्रम यसका लागि हो:')
SAFETY_HEAD = ('Before you start', 'सुरु गर्नु अघि')
SAFETY = [
    ('Go slowly. A gentle stretch or mild effort is normal.', 'बिस्तारै गर्नुहोस्। हल्का तानिने वा हल्का मेहनत महसुस हुनु सामान्य हो।'),
    ('Stop and tell your therapist if you feel sharp pain, numbness, dizziness, or pain that gets worse.', 'तीव्र दुखाइ, सुन्न हुनु, चक्कर लाग्नु वा दुखाइ बढ्यो भने रोक्नुहोस् र आफ्नो थेरापिस्टलाई भन्नुहोस्।'),
    ('Do not hold your breath. Breathe normally while you exercise.', 'सास नरोकी सामान्य रूपमा सास फेर्दै व्यायाम गर्नुहोस्।'),
]
GLANCE_HEAD = ('Your plan at a glance', 'तपाईंको योजना एक नजरमा')
COLS = (('Exercise', 'व्यायाम'), ('How many', 'कति गर्ने'), ('When', 'कहिले'))
WHEN = {'Morning': 'बिहान', 'Day': 'दिउँसो', 'Evening': 'साँझ', 'Any time': 'जुनसुकै बेला'}
DO_THIS = ('Do this', 'यसरी गर्नुहोस्')
PICTURES = ('Pictures', 'तस्बिरहरू')
HOW = ('How to do it', 'कसरी गर्ने')
IN_NEPALI = ('In Nepali', 'नेपालीमा')
VIDEO = ('Watch a video', 'भिडियो हेर्नुहोस्')
NO_TEXT = ('Your therapist will show you how to do this exercise.', 'यो व्यायाम कसरी गर्ने भनेर तपाईंको थेरापिस्टले देखाउनुहुनेछ।')
REMEMBER_HEAD = ('Remember', 'याद राख्नुहोस्')
REMEMBER = [
    ('Do your exercises at the times shown on page 1.', 'आफ्नो व्यायाम पहिलो पानामा देखाइएको समयमा गर्नुहोस्।'),
    ('Tick each exercise below every day you do it.', 'हरेक दिन गरेको व्यायामको तल चिन्ह लगाउनुहोस्।'),
    ('If you have a question or feel worse, contact us.', 'प्रश्न भए वा दुखाइ बढे हामीलाई सम्पर्क गर्नुहोस्।'),
]
TICK_HEAD = ('Weekly tick chart', 'साप्ताहिक चिन्ह तालिका')
DAYS = (('Sun', 'आइत'), ('Mon', 'सोम'), ('Tue', 'मङ्गल'), ('Wed', 'बुध'), ('Thu', 'बिही'), ('Fri', 'शुक्र'), ('Sat', 'शनि'))
CONTACT = ('Contact us', 'सम्पर्क')
SECTION_HEADS = {'starting position', 'steps', 'सुरुको अवस्था', 'चरणहरू'}


# ---------------------------------------------------------------- the link
def token(prescription):
    return signing.dumps(prescription.pk, salt=SALT)


def prescription_from_token(value):
    """The prescription a shared link points to, or None when the link is wrong or expired."""
    from .models import Prescription
    try:
        pk = signing.loads(value, salt=SALT, max_age=LINK_DAYS * 86400)
    except signing.BadSignature:
        return None
    return Prescription.objects.select_related('patient', 'professional').filter(pk=pk).first()


def file_name(prescription):
    return f'Home-exercises-{prescription.patient.patient_code or prescription.pk}-{(prescription.created_at or timezone.now()):%Y-%m-%d}.pdf'.replace(' ', '-')


def share_message(prescription, profile, url):
    from accounts import messaging
    values = {**messaging.practice_values(profile), 'patient': prescription.patient.name, 'date': f'{(prescription.created_at or timezone.now()):%d %b %Y}', 'link': url, 'days': LINK_DAYS}
    return messaging.render(messaging.body_for(profile, 'exercise_program'), values)


def email_html(prescription, profile, url, message):
    from html import escape
    practice = escape(profile.practice_name or profile.full_name)
    body = escape(message).replace('\n', '<br>')
    return (f'<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;border:1px solid #cfe6d8;border-radius:10px;overflow:hidden">'
            f'<div style="background:#116b43;color:#fff;padding:14px 18px"><b style="font-size:17px">{practice}</b><br><span style="font-size:12px">Your home exercise programme</span></div>'
            f'<div style="padding:18px;font-size:14px;line-height:1.5;color:#1d2b24">{body}'
            f'<p><a href="{escape(url)}" style="background:#168653;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;display:inline-block">Open the programme</a></p>'
            f'<p style="font-size:12px;color:#5d7568">The programme is attached as a PDF, with pictures and instructions in English and Nepali.</p></div></div>')


# ---------------------------------------------------------------- pictures
def _image_file(url):
    """The file of a library picture ('/static/exercises/knee/1.png'), only if it really is inside the project's static folder."""
    rel = (url or '').split('?')[0].lstrip('/')
    if rel.startswith('static/'):
        rel = rel[len('static/'):]
    path = (STATIC / rel).resolve()
    try:
        path.relative_to(STATIC.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _prepare(url):
    """A library picture as (JPEG bytes, width, height) shrunk for a light PDF, or None when it cannot be read."""
    from PIL import Image
    path = _image_file(url)
    if path is None:
        return None
    try:
        with Image.open(path) as img:
            img = img.convert('RGBA')
            flat = Image.new('RGB', img.size, (255, 255, 255))
            flat.paste(img, mask=img.split()[3])
            flat.thumbnail((900, 900))
            out = io.BytesIO()
            flat.save(out, 'JPEG', quality=84, optimize=True)
            return out.getvalue(), flat.width, flat.height
    except Exception:  # a damaged file must not stop the whole handout
        return None


def _exercise_images(exercise):
    if exercise is None:
        return []
    urls = [s.image_url for s in exercise.step_images.all()] or ([exercise.exercise_url] if exercise.exercise_url else [])
    return [(u, p) for u in urls for p in [_prepare(u)] if p]


# ---------------------------------------------------------------- the PDF
def _when(item):
    names = [name for name, on in (('Morning', item.schedule_morning), ('Day', item.schedule_day), ('Evening', item.schedule_evening)) if on] or ['Any time']
    return names


def _dose(item):
    en = f'{item.sets} sets of {item.reps}' if item.reps else f'{item.sets} sets'
    ne = f'{item.sets} सेट, प्रत्येकमा {item.reps} पटक' if item.reps else f'{item.sets} सेट'
    if item.hold_time_sec:
        en += f', hold {item.hold_time_sec} seconds'
        ne += f', {item.hold_time_sec} सेकेन्ड रोक्नुहोस्'
    if item.rest_time_sec:
        en += f', rest {item.rest_time_sec} seconds between sets'
        ne += f', सेटबीच {item.rest_time_sec} सेकेन्ड आराम'
    return en, ne


def build_pdf(prescription, profile, online_url=''):
    from fpdf import FPDF

    practice = profile.practice_name or profile.full_name
    contact = ' · '.join(x for x in (profile.practice_phone or profile.mobile, getattr(profile, 'whatsapp_number', '') and f'WhatsApp {profile.whatsapp_number}', profile.practice_address) if x)

    class Sheet(FPDF):
        def footer(self):
            self.set_y(-13)
            self.set_font('Sans', '', 8)
            self.set_text_color(*MUTED)
            self.cell(0, 6, f'{practice}  -  {prescription.patient.name}  -  Page {self.page_no()} of {{nb}}', align='C')

    pdf = Sheet(format='A4')
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(True, margin=18)
    pdf.alias_nb_pages()
    pdf.add_font('Sans', '', str(FONTS / 'NotoSans-Regular.ttf'))
    pdf.add_font('Sans', 'B', str(FONTS / 'NotoSans-Bold.ttf'))
    pdf.add_font('Dev', '', str(FONTS / 'NotoSansDevanagari-Regular.ttf'))
    pdf.add_font('Dev', 'B', str(FONTS / 'NotoSansDevanagari-Bold.ttf'))
    pdf.set_text_shaping(True)
    pdf.set_fallback_fonts(['Sans', 'Dev'])
    pdf.set_title(f'{TITLE[0]} - {prescription.patient.name}')
    pdf.set_author(practice)
    pdf.set_creator('Sajhya Health')
    W = pdf.epw

    def text(value, size=11, bold=False, ne=False, color=(29, 43, 36), lh=None, fill=None, indent=0, link=None):
        pdf.set_font('Dev' if ne else 'Sans', 'B' if bold else '', size)
        pdf.set_text_color(*color)
        if fill:
            pdf.set_fill_color(*fill)
        if indent:
            pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(W - indent, lh or size * 0.52, value, new_x='LMARGIN', new_y='NEXT', fill=bool(fill), link=link)

    def heading(pair, size=15):
        pdf.ln(2)
        text(pair[0], size, True, color=DARK)
        text(pair[1], size - 2, True, ne=True, color=DARK)
        pdf.set_draw_color(*GREEN)
        pdf.set_line_width(0.5)
        pdf.line(pdf.l_margin, pdf.get_y() + 0.5, pdf.l_margin + 38, pdf.get_y() + 0.5)
        pdf.ln(2.5)

    def pair(en, ne, size=11, **kw):
        text(en, size, **kw)
        text(ne, size - 0.5, ne=True, **{k: v for k, v in kw.items() if k != 'bold'} | {'bold': kw.get('bold', False)})

    items = list(prescription.exercises.select_related('exercise').prefetch_related('exercise__step_images'))
    made = prescription.created_at or timezone.now()

    # ---------- page 1: purpose, who, safety, the plan at a glance
    pdf.add_page()
    pdf.set_fill_color(*GREEN)
    pdf.rect(0, 0, 210, 30, 'F')
    pdf.set_xy(16, 8)
    pdf.set_font('Sans', 'B', 15)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 7, practice, new_x='LMARGIN', new_y='NEXT')
    pdf.set_x(16)
    pdf.set_font('Sans', '', 9)
    pdf.cell(0, 5, contact, new_x='LMARGIN', new_y='NEXT')
    pdf.set_y(36)
    text(TITLE[0], 21, True, color=DARK)
    text(TITLE[1], 15, True, ne=True, color=DARK)
    pdf.ln(2)
    info = [('Patient', 'रोगी', prescription.patient.name), ('Date', 'मिति', f'{made:%d %b %Y}'), ('Prescribed by', 'तोक्ने', prescription.professional.full_name)]
    for en, ne, value in info:
        pdf.set_font('Sans', 'B', 10.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(42, 6, en, new_x='RIGHT', new_y='TOP')
        pdf.set_font('Dev', '', 9.5)
        pdf.cell(18, 6, ne, new_x='RIGHT', new_y='TOP')
        pdf.set_font('Sans', 'B', 11)
        pdf.set_text_color(29, 43, 36)
        pdf.cell(0, 6, value, new_x='LMARGIN', new_y='NEXT')
    heading(('What this is for', 'यसको उद्देश्य'))
    pair(*PURPOSE, 11)
    if prescription.condition_label:
        pdf.ln(1)
        text(f'{FOR[0]} {prescription.condition_label}', 11, True)
        text(f'{FOR[1]} {prescription.condition_label}', 10.5, True, ne=True)
    heading(SAFETY_HEAD)
    for en, ne in SAFETY:
        pdf.set_x(pdf.l_margin)
        text(f'-  {en}', 10.5, lh=5.4)
        text(f'-  {ne}', 10, ne=True, lh=5.4, color=MUTED)
        pdf.ln(0.8)
    heading(GLANCE_HEAD)
    c1, c2 = W * 0.46, W * 0.30
    pdf.set_fill_color(*GREEN)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Sans', 'B', 9.5)
    for k, (en, ne) in enumerate(COLS):
        w = (c1, c2, W - c1 - c2)[k]
        pdf.cell(w, 8, f'{en} / {ne}', border=0, fill=True, new_x='RIGHT', new_y='TOP')
    pdf.ln(8)
    for n, item in enumerate(items):
        en, ne = _dose(item)
        when = _when(item)
        y0 = pdf.get_y()
        if pdf.will_page_break(16):
            pdf.add_page()
            y0 = pdf.get_y()
        pdf.set_fill_color(*SOFT) if n % 2 else pdf.set_fill_color(255, 255, 255)
        pdf.rect(pdf.l_margin, y0, W, 14, 'F')
        pdf.set_xy(pdf.l_margin + 1.5, y0 + 1)
        pdf.set_font('Sans', 'B', 10)
        pdf.set_text_color(29, 43, 36)
        pdf.multi_cell(c1 - 3, 5, f'{n + 1}. {item.exercise_name}', new_x='RIGHT', new_y='TOP', max_line_height=5)
        pdf.set_xy(pdf.l_margin + c1, y0 + 1)
        pdf.set_font('Sans', '', 9)
        pdf.multi_cell(c2 - 2, 4.4, f'{item.sets} x {item.reps}' + (f', hold {item.hold_time_sec}s' if item.hold_time_sec else ''), new_x='RIGHT', new_y='TOP', max_line_height=4.4)
        pdf.set_xy(pdf.l_margin + c1 + c2, y0 + 1)
        pdf.multi_cell(W - c1 - c2 - 1.5, 4.4, ' / '.join(when) + '\n' + ' / '.join(WHEN[x] for x in when), new_x='LMARGIN', new_y='NEXT', max_line_height=4.4)
        pdf.set_y(y0 + 14)
    if not items:
        text('No exercises have been added yet.', 10.5, color=MUTED)

    # ---------- one page per exercise
    total = len(items)
    for n, item in enumerate(items, 1):
        ex = item.exercise
        pdf.add_page()
        text(f'Exercise {n} of {total}', 10, True, color=MUTED)
        text(f'व्यायाम {n} / {total}', 9.5, True, ne=True, color=MUTED)
        text(item.exercise_name, 19, True, color=DARK, lh=8.5)
        pdf.ln(1)
        # the dose, in a box
        en, ne = _dose(item)
        when = _when(item)
        y = pdf.get_y()
        pdf.set_fill_color(*SOFT)
        pdf.set_draw_color(*GREEN)
        pdf.set_line_width(0.3)
        pdf.rect(pdf.l_margin, y, W, 25, 'DF')
        pdf.set_xy(pdf.l_margin + 3, y + 2)
        pdf.set_font('Sans', 'B', 9)
        pdf.set_text_color(*GREEN)
        pdf.cell(40, 5, DO_THIS[0].upper(), new_x='RIGHT', new_y='TOP')
        pdf.set_font('Dev', 'B', 9)
        pdf.cell(40, 5, DO_THIS[1], new_x='LMARGIN', new_y='NEXT')
        pdf.set_x(pdf.l_margin + 3)
        text(f'{en}.  {" , ".join(when)}.'.replace(' ,', ','), 10.5, True, indent=3, lh=5.2)
        text(f'{ne}।  {" , ".join(WHEN[x] for x in when)}।'.replace(' ,', ','), 10, ne=True, indent=3, lh=5.2, color=MUTED)
        pdf.set_y(y + 26)
        # the pictures, in order, each with its step number
        images = _exercise_images(ex)
        if images:
            heading(PICTURES, 12)
            per_row = min(len(images), 3)
            gap = 4
            w = (W - gap * (per_row - 1)) / per_row
            for start in range(0, len(images), per_row):
                row = images[start:start + per_row]
                fitted = []
                for _, (data, iw, ih) in row:
                    scale = min(w / iw, 44 / ih)
                    fitted.append((data, iw * scale, ih * scale))
                rowh = max(h for _, _, h in fitted) + 5.5
                if pdf.get_y() + rowh > pdf.page_break_trigger:
                    pdf.add_page()
                y = pdf.get_y()
                for k, (data, fw, fh) in enumerate(fitted):
                    x = pdf.l_margin + k * (w + gap) + (w - fw) / 2
                    pdf.image(io.BytesIO(data), x=x, y=y, w=fw, h=fh)
                    pdf.set_xy(pdf.l_margin + k * (w + gap), y + fh + 0.5)
                    pdf.set_font('Sans', '', 8.5)
                    pdf.set_text_color(*MUTED)
                    pdf.cell(w, 4.5, f'Picture {start + k + 1}', align='C', new_x='LEFT', new_y='TOP')
                pdf.set_y(y + rowh + 1)
        # the words
        heading(HOW, 12)
        english = (ex.exercise_description if ex else '').strip()
        nepali = (ex.exercise_description_nepali if ex else '').strip()
        if not english and not nepali:
            pair(*NO_TEXT, 10.5)
        for body, is_nepali in ((english, False), (nepali, True)):
            if not body:
                continue
            if is_nepali:
                pdf.ln(1.5)
                text(IN_NEPALI[1], 10.5, True, ne=True, color=GREEN)
            for raw in body.replace('\r\n', '\n').split('\n'):
                line = raw.strip()
                if not line:
                    pdf.ln(1.2)
                    continue
                if line.lower() in SECTION_HEADS:
                    pdf.ln(0.8)
                    text(line, 11, True, ne=is_nepali, color=DARK)
                elif re.match(r'^(remember|याद राख्नुहोस्)', line, re.I):
                    pdf.ln(1)
                    text(line, 10.2, True, ne=is_nepali, fill=AMBER_SOFT, color=(122, 90, 16), lh=5.1)
                elif re.match(r'^\d+[.)]\s', line):
                    text(line, 10.5, ne=is_nepali, indent=2, lh=5.1)
                else:
                    text(line, 10.5, ne=is_nepali, lh=5.1)
        link = (ex.hosted_video_url or ex.youtube_url) if ex else ''
        if link:
            pdf.ln(2)
            text(f'{VIDEO[0]} / {VIDEO[1]}:  {link}', 9.5, color=(17, 107, 67), link=link)

    # ---------- the last page: remember, tick chart, contact
    pdf.add_page()
    heading(REMEMBER_HEAD)
    for en, ne in REMEMBER:
        text(f'-  {en}', 10.8, lh=5.6)
        text(f'-  {ne}', 10.3, ne=True, lh=5.6, color=MUTED)
        pdf.ln(0.8)
    heading(TICK_HEAD)
    label_w = W * 0.34
    cell_w = (W - label_w) / 7
    pdf.set_fill_color(*GREEN)
    pdf.set_text_color(255, 255, 255)
    y0 = pdf.get_y()
    pdf.rect(pdf.l_margin, y0, W, 11, 'F')
    pdf.set_xy(pdf.l_margin + 1.5, y0 + 3)
    pdf.set_font('Sans', 'B', 8.5)
    pdf.cell(label_w - 3, 5, 'Exercise / व्यायाम', new_x='LEFT', new_y='TOP')
    for d, (en, ne) in enumerate(DAYS):
        x = pdf.l_margin + label_w + d * cell_w
        pdf.set_xy(x, y0 + 0.8)
        pdf.set_font('Sans', 'B', 8)
        pdf.cell(cell_w, 4.5, en, align='C', new_x='LEFT', new_y='TOP')
        pdf.set_xy(x, y0 + 5.3)
        pdf.set_font('Dev', 'B', 7.5)
        pdf.cell(cell_w, 4.5, ne, align='C', new_x='LEFT', new_y='TOP')
    pdf.set_y(y0)
    pdf.ln(11)
    pdf.set_draw_color(*GREEN)
    pdf.set_line_width(0.25)
    for n, item in enumerate(items):
        y = pdf.get_y()
        pdf.set_text_color(29, 43, 36)
        pdf.set_font('Sans', '', 9)
        pdf.set_xy(pdf.l_margin, y)
        pdf.multi_cell(label_w, 5, f'{n + 1}. {item.exercise_name}', border=0, new_x='RIGHT', new_y='TOP', max_line_height=5)
        rowh = 10.5
        for d in range(7):
            pdf.rect(pdf.l_margin + label_w + d * cell_w, y, cell_w, rowh)
        pdf.rect(pdf.l_margin, y, label_w, rowh)
        pdf.set_y(y + rowh)
    pdf.ln(5)
    heading(CONTACT)
    text(practice, 11.5, True)
    if contact:
        text(contact, 10.5, color=MUTED)
    if online_url:
        pdf.ln(2)
        text('Open this programme online:', 9.5, color=MUTED)
        text(online_url, 9, color=(17, 107, 67), link=online_url)
    return bytes(pdf.output())
