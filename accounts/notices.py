"""The Messages page (business WhatsApp number, wording of every message, custom notices) and the page that prepares a notice for many
patients at once. Nothing is sent from here: each patient gets a wa.me link with their message ready, and the professional presses send."""
import datetime
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from . import messaging
from .access import can_see_contact, workspace_context, workspace_profile
from .models import Appointment, MessageTemplate, Patient

MAX_CUSTOM = 20
MAX_BODY = 1000


def _back(anchor=''):
    return redirect(reverse('accounts:messages') + (f'#{anchor}' if anchor else ''))


@login_required
def messages_page(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    mine = {t.key: t for t in MessageTemplate.objects.filter(professional=profile)}
    built_in = [{'key': key, 'label': d['label'], 'help': d['help'], 'default': d['body'], 'body': mine[key].body if key in mine else d['body'],
                 'changed': key in mine} for key, d in messaging.DEFAULTS.items()]
    custom = [t for t in mine.values() if t.is_custom]
    custom.sort(key=lambda t: t.updated_at, reverse=True)
    context = workspace_context(request.user, profile)
    context.update({'active': 'messages', 'built_in': built_in, 'custom': custom, 'placeholders': messaging.PLACEHOLDERS, 'sample': messaging.SAMPLE,
                    'contact_preview': messaging.contact_text(profile), 'can_add_custom': len(custom) < MAX_CUSTOM,
                    'sample_values': {**messaging.SAMPLE, **messaging.practice_values(profile)}})
    return render(request, 'accounts/messages.html', context)


@login_required
def whatsapp_number_save(request):
    """The business WhatsApp and Viber numbers printed in messages and on invoices."""
    profile = workspace_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('accounts:messages')
    try:
        whatsapp = messaging.clean_whatsapp_number(request.POST.get('whatsapp_number'))
        viber = messaging.clean_whatsapp_number(request.POST.get('viber_number'))
    except ValueError as exc:
        messages.error(request, str(exc).replace('WhatsApp number', 'number'))
        return _back('number')
    profile.whatsapp_number, profile.viber_number = whatsapp, viber
    profile.whatsapp_web = request.POST.get('whatsapp_web') == 'on'
    profile.save(update_fields=['whatsapp_number', 'viber_number', 'whatsapp_web'])
    messages.success(request, 'Business numbers saved.' if whatsapp or viber else 'Business numbers removed.')
    return _back('number')


def _clean_body(request):
    body = (request.POST.get('body') or '').replace('\r\n', '\n').strip()
    if not body:
        messages.error(request, 'The message cannot be empty.')
        return None
    if len(body) > MAX_BODY:
        messages.error(request, f'Keep the message under {MAX_BODY} characters.')
        return None
    return body


@login_required
def message_save(request, key):
    profile = workspace_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('accounts:messages')
    existing = MessageTemplate.objects.filter(professional=profile, key=key).first()
    if key not in messaging.DEFAULTS and (existing is None or not existing.is_custom):
        return _back()
    body = _clean_body(request)
    if body is None:
        return _back(key)
    if existing is None:
        MessageTemplate.objects.create(professional=profile, key=key, body=body, title=messaging.DEFAULTS[key]['label'])
    else:
        existing.body = body
        if existing.is_custom:
            existing.title = (request.POST.get('title') or existing.title).strip()[:100] or existing.title
        existing.save()
    messages.success(request, 'Message saved. It is used from now on.')
    return _back(key)


@login_required
def message_reset(request, key):
    profile = workspace_profile(request)
    if profile is None or request.method != 'POST' or key not in messaging.DEFAULTS:
        return redirect('accounts:messages')
    MessageTemplate.objects.filter(professional=profile, key=key).delete()
    messages.success(request, 'Back to the standard wording.')
    return _back(key)


@login_required
def custom_add(request):
    profile = workspace_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('accounts:messages')
    title = (request.POST.get('title') or '').strip()[:100]
    body = _clean_body(request)
    if not title:
        messages.error(request, 'Give the notice a short name, for example "Holiday closure".')
        return _back('custom')
    if body is None:
        return _back('custom')
    if MessageTemplate.objects.filter(professional=profile, is_custom=True).count() >= MAX_CUSTOM:
        messages.error(request, f'You can keep up to {MAX_CUSTOM} custom notices. Delete one first.')
        return _back('custom')
    MessageTemplate.objects.create(professional=profile, key=f'custom-{uuid.uuid4().hex[:8]}', title=title, body=body, is_custom=True)
    messages.success(request, f'Notice "{title}" saved. Use it from Send a notice.')
    return _back('custom')


@login_required
def custom_delete(request, key):
    profile = workspace_profile(request)
    if profile is None or request.method != 'POST':
        return redirect('accounts:messages')
    MessageTemplate.objects.filter(professional=profile, key=key, is_custom=True).delete()
    messages.success(request, 'Notice deleted.')
    return _back('custom')


AUDIENCES = [('followup', 'Follow-ups due (not seen for 14 days)'), ('appointments', 'Patients with an appointment on a day'),
             ('all', 'All active patients'), ('search', 'Find a patient')]


@login_required
def notice_send(request):
    """Pick a message and who gets it: each row has that patient's own wording and a WhatsApp button."""
    from .views import followups_due
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    templates = [(key, d['label']) for key, d in messaging.DEFAULTS.items() if key != 'bill']
    templates += [(t.key, t.title) for t in MessageTemplate.objects.filter(professional=profile, is_custom=True).order_by('title')]
    valid = {k for k, _ in templates}
    key = request.GET.get('t') if request.GET.get('t') in valid else 'followup'
    audience = request.GET.get('audience') if request.GET.get('audience') in dict(AUDIENCES) else 'followup'
    today = timezone.localdate()
    try:
        day = datetime.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        day = today + datetime.timedelta(days=1)
    q = request.GET.get('q', '').strip()
    body = messaging.body_for(profile, key)
    patients = profile.workspace_patients().exclude(status=Patient.DISCHARGED)
    rows = []

    def add(patient, values, when_label=''):
        text = messaging.render(body, values)
        shown = can_see_contact(profile, patient) and patient.phone
        links = messaging.channel_links(patient.phone if shown else '', text, patient.messaging_app, profile.whatsapp_web)
        rows.append({'patient': patient, 'phone': patient.phone if shown else '', 'text': text, 'when': when_label, 'links': links, 'url': links[0]['url']})

    if audience == 'appointments':
        start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
        for appt in (profile.appointments.filter(kind=Appointment.APPOINTMENT, status=Appointment.SCHEDULED, start__gte=start, start__lt=start + datetime.timedelta(days=1))
                     .select_related('patient', 'professional').order_by('start')[:150]):
            if appt.patient_id and patients.filter(pk=appt.patient_id).exists():
                add(appt.patient, messaging.appointment_values(profile, appt), messaging_time(appt))
    else:
        if audience == 'followup':
            people = followups_due(patients, today)
        elif audience == 'all':
            people = patients.filter(status=Patient.ACTIVE)
        else:
            people = patients.filter(name__icontains=q) | patients.filter(phone__icontains=q) | patients.filter(patient_code__icontains=q) if q else patients.none()
        for patient in people.distinct().order_by('name')[:150]:
            add(patient, messaging.patient_values(profile, patient, day if audience != 'followup' else None))
    context = workspace_context(request.user, profile)
    context.update({'active': 'messages', 'templates': templates, 'key': key, 'audiences': AUDIENCES, 'audience': audience, 'day': day, 'q': q, 'rows': rows,
                    'with_phone': sum(1 for r in rows if r['phone']), 'body': body})
    return render(request, 'accounts/notice_send.html', context)


def messaging_time(appt):
    from .appointments import fmt_time
    return fmt_time(appt.start)
