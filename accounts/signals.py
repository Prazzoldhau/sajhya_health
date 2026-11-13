"""Sign-in events: every successful sign-in is written to the access log; sign-ins and failures of the platform's own staff accounts, and lockouts,
are also e-mailed to SECURITY_ALERT_EMAILS."""
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from . import audit


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    if request is None:
        return
    from .models import AccessLog
    profile = getattr(getattr(user, 'account', None), 'profile', None)
    operator = bool(user.is_staff or user.is_superuser)
    try:
        AccessLog.objects.create(user=user, user_label=audit.name_of(user), role=audit.role_of(user), operator=operator, workspace=profile, action='login',
                                 detail='signed in', path=request.path[:200], ip=audit.ip_of(request))
    except Exception:  # noqa: BLE001 - a log problem must never stop a sign-in
        pass
    if operator:
        audit.alert(f'Staff sign-in: {user.get_username()}', f'The platform account "{user.get_username()}" signed in at {audit.now_text()} from {audit.ip_of(request)}.\n\nIf this was not you, change the password and tell the clinics.')


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get('username', '')
    if not username or request is None:
        return
    User = get_user_model()
    if User.objects.filter(username=username).filter(is_staff=True).exists():
        audit.alert(f'Failed staff sign-in: {username}', f'A sign-in to the platform account "{username}" failed at {audit.now_text()} from {audit.ip_of(request)}.')


def connect_axes():
    try:
        from axes.signals import user_locked_out
    except Exception:  # noqa: BLE001
        return

    @receiver(user_locked_out)
    def on_locked_out(sender, request=None, username=None, ip_address=None, **kwargs):
        audit.alert(f'Sign-in locked out: {username or "unknown"}', f'Too many failed sign-ins for "{username}" from {ip_address} at {audit.now_text()}. The account is locked for a short time.')
