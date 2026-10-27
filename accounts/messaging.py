"""The WhatsApp messages the workspace prepares for patients (appointment booked / reminder / rescheduled / cancelled, follow-up, bill, and
any notice the professional writes). Each message is a template with {placeholders}: the built-in wording can be changed per professional,
and custom notices can be added. Messages are opened in WhatsApp with wa.me links; the professional presses send."""
import re
from urllib.parse import quote

from django.utils import timezone

DEFAULTS = {
    'appointment_booked': {
        'label': 'Appointment booked (confirmation)',
        'help': 'Sent right after you book an appointment.',
        'body': ('Hello {patient},\nYour appointment at {practice} is booked for {day}, {date} at {time}.\nPlease arrive 10 minutes early.\n'
                 'To change it, contact us: {contact}\nThank you.'),
    },
    'appointment_reminder': {
        'label': 'Appointment reminder',
        'help': 'A reminder before the appointment, from the calendar or the notices page.',
        'body': 'Hello {patient},\nA reminder of your appointment at {practice} on {day}, {date} at {time}.\nIf you cannot come, please tell us: {contact}\nThank you.',
    },
    'appointment_rescheduled': {
        'label': 'Appointment rescheduled',
        'help': 'Sent after you move an appointment to another day or time.',
        'body': 'Hello {patient},\nYour appointment at {practice} has been rescheduled to {day}, {date} at {time}.\nTo change it again, contact us: {contact}\nThank you.',
    },
    'appointment_cancelled': {
        'label': 'Appointment cancelled',
        'help': 'Sent after you cancel an appointment.',
        'body': 'Hello {patient},\nYour appointment at {practice} on {date} at {time} has been cancelled.\nTo book another time, contact us: {contact}',
    },
    'followup': {
        'label': 'Follow-up check-in',
        'help': 'For patients who have not visited for a while.',
        'body': 'Hello {patient},\nIt has been a while since your last visit to {practice}. How are you feeling?\nTo book your next session, contact us: {contact}',
    },
    'bill': {
        'label': 'Bill / invoice message',
        'help': 'The text that goes with an invoice sent by WhatsApp or e-mail.',
        'body': ('Hello {patient},\nYour bill {invoice} from {practice} dated {date}: NPR {amount}.\n{due_line}\n{extra_line}\nInvoice: {link}'),
    },
}
BUILT_IN_ORDER = list(DEFAULTS)

PLACEHOLDERS = [
    ('patient', "The patient's name"), ('practice', 'Your practice (or clinic) name'), ('therapist', 'Your name'),
    ('day', 'Weekday, e.g. Tuesday'), ('date', 'Date, e.g. 27 Oct 2026'), ('time', 'Time, e.g. 3:00 PM'),
    ('contact', 'Your WhatsApp number and phone'), ('address', 'Your practice address'),
    ('invoice', 'Invoice number (bill message)'), ('amount', 'Bill amount (bill message)'),
]
SAMPLE = {
    'patient': 'Sita Gurung', 'practice': 'Your Practice', 'therapist': 'Your Name', 'day': 'Tuesday', 'date': '27 Oct 2026', 'time': '3:00 PM',
    'contact': 'WhatsApp +977 98xxxxxxx', 'address': 'Your address', 'invoice': 'BILL-1A2B3C4D', 'amount': '700', 'due_line': '', 'extra_line': '', 'link': 'https://...',
}
_TOKEN = re.compile(r'\{(\w+)\}')


def render(body, values):
    """Fill {placeholders}. A line whose placeholders are all empty is dropped, so a missing phone number or an unused line never leaves
    a hole like "contact us: ". Unknown placeholders are left as typed."""
    out = []
    for line in (body or '').replace('\r\n', '\n').split('\n'):
        tokens = _TOKEN.findall(line)
        if tokens and all(t in values and not str(values[t]).strip() for t in tokens):
            continue
        out.append(_TOKEN.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), line))
    text = '\n'.join(out)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def body_for(profile, key):
    """The professional's own wording for this message, else the built-in one. A custom notice is looked up by its key."""
    from .models import MessageTemplate
    row = MessageTemplate.objects.filter(professional=profile, key=key).first()
    if row is not None:
        return row.body
    return DEFAULTS[key]['body'] if key in DEFAULTS else ''


def contact_text(profile):
    phone = profile.practice_phone or profile.mobile
    apps = []
    if profile.whatsapp_number:
        apps.append(f'WhatsApp {profile.whatsapp_number}')
    if profile.viber_number:
        apps.append(f'Viber {profile.viber_number}')
    if apps and phone and phone not in (profile.whatsapp_number, profile.viber_number):
        return ', '.join(apps) + f' or call {phone}'
    return ', '.join(apps) if apps else phone


def practice_values(profile):
    return {'practice': profile.practice_name or profile.full_name, 'therapist': profile.full_name, 'contact': contact_text(profile), 'address': profile.practice_address}


def appointment_values(profile, appt):
    from .appointments import fmt_time  # lazy: appointments imports this module
    when = timezone.localtime(appt.start)
    return {**practice_values(profile), 'patient': appt.patient.name if appt.patient else '', 'day': f'{when:%A}', 'date': f'{when:%d %b %Y}', 'time': fmt_time(appt.start)}


def patient_values(profile, patient, when=None):
    from .appointments import fmt_time
    values = {**practice_values(profile), 'patient': patient.name, 'day': '', 'date': '', 'time': ''}
    if when is not None:
        values.update({'day': f'{when:%A}', 'date': f'{when:%d %b %Y}', 'time': fmt_time(when) if hasattr(when, 'hour') else ''})
    return values


def whatsapp_url(phone, text):
    """wa.me link with the message ready. It opens the patient's own chat when the number is usable, else WhatsApp's contact picker."""
    from billing.invoice import normalize_phone
    number = normalize_phone(phone)
    return f"https://wa.me/{number}?text={quote(text)}" if number else f"https://wa.me/?text={quote(text)}"


CHANNELS = [('whatsapp', 'WhatsApp'), ('viber', 'Viber'), ('sms', 'SMS')]


def channel_links(phone, text, preferred='whatsapp'):
    """The ways to send this text to one patient, the patient's own app first. WhatsApp and SMS open the chat with the text ready. Viber
    cannot be given a text together with a chat, so its link opens the patient's chat (or the contact picker with no number) and the
    text is put on the clipboard for you to paste: the link carries a `copy` text that the page copies when it is clicked."""
    from billing.invoice import normalize_phone
    number = normalize_phone(phone)
    links = []
    for key, label in CHANNELS:
        copy = ''
        if key == 'whatsapp':
            url = whatsapp_url(phone, text)
        elif key == 'viber':
            url, copy = (f'viber://chat?number=%2B{number}', text) if number else (f'viber://forward?text={quote(text)}', '')
        else:
            url = f'sms:+{number}?body={quote(text)}' if number else f'sms:?body={quote(text)}'
        links.append({'key': key, 'label': label, 'url': url, 'copy': copy, 'preferred': key == preferred})
        if key == 'viber' and number:  # the other way Viber can do it: the text typed, then you choose the contact
            links.append({'key': 'viber_text', 'label': 'Viber (text typed, choose contact)', 'url': f'viber://forward?text={quote(text)}', 'copy': '', 'preferred': False})
    links.sort(key=lambda link: 0 if link['preferred'] else (0.5 if link['key'] == 'viber_text' and preferred == 'viber' else 1))  # the patient's app first, Viber's typed-text option right after it
    return links


def clean_whatsapp_number(value):
    """The business WhatsApp number as typed (spaces, dashes and a leading + are fine); at least 8 digits."""
    value = (value or '').strip()
    if not value:
        return ''
    if re.search(r'[^\d+\-\s()]', value) or len(re.sub(r'\D', '', value)) < 8:
        raise ValueError('Enter a WhatsApp number with the country code, for example +977 970-2235789.')
    return value[:20]
