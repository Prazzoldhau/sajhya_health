from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def patient_avatar(patient, size=''):
    """The round patient avatar: their picture when they have one, otherwise initials.
    Use everywhere a patient is listed so photo handling lives in one place."""
    css = f'patient-avatar {size}'.strip()
    if patient is not None and getattr(patient, 'photo', None):
        return format_html('<span class="{} has-photo"><img src="{}" alt="" loading="lazy"></span>', css, patient.photo_url)
    initials = getattr(patient, 'initials', '') or '?'
    return format_html('<span class="{}">{}</span>', css, initials)


@register.simple_tag
def patient_cell(patient, sub='code', link=True):
    """Avatar + name + a small second line (the patient code or the diagnosis). One look for every patient list."""
    from django.urls import reverse
    name = format_html('<a href="{}" style="color:inherit;text-decoration:none">{}</a>', reverse('accounts:patient-detail', args=[patient.pk]), patient.name) if link else patient.name
    second = {'code': patient.patient_code, 'diagnosis': patient.diagnosis or patient.condition}.get(sub, '')
    return format_html('<div class="patient-cell">{}<div>{}{}</div></div>', patient_avatar(patient), name,
                       format_html('<div class="patient-id">{}</div>', second) if second else '')
