"""The access log: who opened, exported or shared patient records, who signed in, and what the platform's own staff opened.

The clinic owner reads it on the Access log page (accounts/access_log_views.py). It is written by the app on every view that matters, so a record
cannot be opened through the app without a line being left. (Someone with direct database or server access can still bypass the app: see docs/PRIVACY.md.)
"""
import logging
import re

from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger('sajhya.audit')
DEDUPE_SECONDS = 600  # the same person opening the same thing again within ten minutes is one line, not twenty


def ip_of(request):
    from django.conf import settings
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded and getattr(settings, 'AXES_IPWARE_PROXY_COUNT', 0):
        return forwarded.split(',')[0].strip()[:45]
    return request.META.get('REMOTE_ADDR', '')[:45]


def role_of(user):
    if user.is_superuser:
        return 'platform administrator'
    if user.is_staff:
        return 'platform staff'
    profile = getattr(getattr(user, 'account', None), 'profile', None)
    if profile is not None:
        return 'clinic login' if getattr(profile, 'clinic_workspace', None) is not None else 'professional'
    return 'user'


def name_of(user):
    profile = getattr(getattr(user, 'account', None), 'profile', None)
    return (getattr(profile, 'full_name', '') or user.get_full_name() or user.get_username())[:150]


def log_access(request, action, patient=None, workspace=None, clinic=None, detail='', operator=None, dedupe=True):
    """Write one access line. `patient` (an accounts.Patient) fills in whose records and the clinic. Never raises: a logging problem must not break a page."""
    try:
        from .models import AccessLog
        user = request.user if request.user.is_authenticated else None
        if user is None:
            return None
        if patient is not None:
            workspace = workspace or getattr(patient, 'professional', None)
            clinic = clinic or getattr(patient, 'clinic', None)
        if operator is None:
            operator = bool(user.is_staff or user.is_superuser)
        key = f'audit:{user.pk}:{action}:{getattr(patient, "pk", 0)}:{getattr(workspace, "pk", 0)}:{detail[:60]}'
        if dedupe and cache.get(key):
            return None
        row = AccessLog.objects.create(
            user=user, user_label=name_of(user), role=role_of(user), operator=operator, workspace=workspace, clinic=clinic,
            patient_code=(getattr(patient, 'patient_code', '') or '')[:40], action=action[:20], detail=detail[:250], path=request.path[:200], ip=ip_of(request))
        if dedupe:
            cache.set(key, 1, DEDUPE_SECONDS)
        return row
    except Exception:  # noqa: BLE001 - see the docstring
        log.exception('access log write failed')
        return None


ADMIN_TARGETS = [(re.compile(r'/accounts/professionalprofile/(\d+)/'), 'workspace'), (re.compile(r'/clinics/clinic/(\d+)/'), 'clinic')]


def operator_targets(path):
    """(workspace, clinic) a platform staff request is about, read from an admin or support address, so that clinic sees it in its own log."""
    from .models import ProfessionalProfile
    workspace = clinic = None
    for pattern, kind in ADMIN_TARGETS:
        m = pattern.search(path)
        if m and kind == 'workspace':
            workspace = ProfessionalProfile.objects.filter(pk=int(m.group(1))).first()
        elif m and kind == 'clinic':
            from clinics.models import Clinic
            clinic = Clinic.objects.filter(pk=int(m.group(1))).first()
    return workspace, clinic


def alert(subject, body):
    """E-mail the people named in SECURITY_ALERT_EMAILS (and write the log). Quiet when mail is not set up."""
    from django.conf import settings
    from django.core.mail import send_mail

    from .messaging import email_ready
    log.warning('security alert: %s', subject)
    recipients = [e for e in getattr(settings, 'SECURITY_ALERT_EMAILS', []) if e]
    if not recipients or not email_ready():
        return False
    try:
        send_mail(f'[Sajhya Health security] {subject}', body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
        return True
    except Exception:  # noqa: BLE001
        log.exception('security alert e-mail failed')
        return False


def now_text():
    return timezone.localtime().strftime('%d %b %Y %H:%M')
