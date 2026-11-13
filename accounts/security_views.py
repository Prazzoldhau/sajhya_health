"""Two-step sign-in (authenticator app code), and the Access log page the clinic owner reads."""
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils import timezone

from sajhya_health.safe import local_path

from . import audit, totp
from .access import workspace_context, workspace_profile
from .models import AccessLog, Patient, TwoFactor

PENDING_MINUTES = 10
MAX_TRIES = 5


class MfaLoginView(LoginView):
    """The ordinary sign-in. A person who has turned on two-step sign-in is not signed in yet after the password: they are sent on to enter the code."""

    def form_valid(self, form):
        user = form.get_user()
        if TwoFactor.objects.filter(user=user, confirmed_at__isnull=False).exists():
            self.request.session['mfa_pending'] = {'user_id': user.pk, 'backend': getattr(user, 'backend', 'django.contrib.auth.backends.ModelBackend'),
                                                   'next': self.get_success_url(), 'at': time.time(), 'tries': 0}
            return redirect('accounts:login-verify')
        response = super().form_valid(form)
        self.request.session['mfa_verified'] = False
        return response


def _locked(user_id):
    return cache.get(f'mfa-fail:{user_id}', 0) >= 10  # ten wrong codes in 15 minutes lock the second step for that person, whichever device they use


def _count_failure(user_id):
    cache.set(f'mfa-fail:{user_id}', cache.get(f'mfa-fail:{user_id}', 0) + 1, 900)


def login_verify(request):
    pending = request.session.get('mfa_pending')
    if not pending or time.time() - pending.get('at', 0) > PENDING_MINUTES * 60:
        request.session.pop('mfa_pending', None)
        messages.info(request, 'Sign in again.')
        return redirect('accounts:login')
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.filter(pk=pending['user_id'], is_active=True).first()
    two = TwoFactor.objects.filter(user=user, confirmed_at__isnull=False).first() if user else None
    if user is None or two is None:
        request.session.pop('mfa_pending', None)
        return redirect('accounts:login')
    error = ''
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if _locked(user.pk):
            error = 'Too many wrong codes. Wait 15 minutes, then sign in again.'
        else:
            step = totp.verify(two.secret, code, two.last_step)
            used_recovery = False
            if step is None:
                hashed = totp.hash_recovery(code)
                if hashed in (two.recovery_hashes or []):
                    two.recovery_hashes = [h for h in two.recovery_hashes if h != hashed]
                    two.save(update_fields=['recovery_hashes'])
                    used_recovery = True
            if step is not None or used_recovery:
                if step is not None:
                    two.last_step = step
                    two.save(update_fields=['last_step'])
                nxt = pending.get('next', '')
                backend = pending.get('backend')
                request.session.pop('mfa_pending', None)
                login(request, user, backend=backend)
                request.session['mfa_verified'] = True
                if used_recovery:
                    messages.warning(request, f'You signed in with a recovery code. {len(two.recovery_hashes)} left. Make new ones in Settings, Two-step sign-in.')
                return redirect(local_path(request, nxt, '') or 'accounts:welcome')
            _count_failure(user.pk)
            pending['tries'] = pending.get('tries', 0) + 1
            request.session['mfa_pending'] = pending
            if pending['tries'] >= MAX_TRIES:
                request.session.pop('mfa_pending', None)
                messages.error(request, 'Too many wrong codes. Sign in again.')
                return redirect('accounts:login')
            error = 'That code is not right. Check the time on your phone and try the newest code.'
    return render(request, 'accounts/login_verify.html', {'error': error, 'username': user.get_username()})


@login_required
def security_page(request):
    """Turn two-step sign-in on or off, and make new recovery codes."""
    user = request.user
    two = TwoFactor.objects.filter(user=user).first()
    on = bool(two and two.is_on)
    context = {'on': on, 'recovery_left': len(two.recovery_hashes or []) if on else 0, 'forced': user.is_staff, 'error': ''}
    if request.method == 'POST':
        action = request.POST.get('action')
        code = request.POST.get('code', '').strip()
        if action == 'confirm' and not on:
            secret = request.session.get('mfa_setup_secret', '')
            step = totp.verify(secret, code, 0) if secret else None
            if step is None:
                context['error'] = 'That code is not right. Check the time on your phone and enter the newest code.'
            else:
                codes = totp.new_recovery_codes()
                TwoFactor.objects.update_or_create(user=user, defaults={'secret': secret, 'confirmed_at': timezone.now(), 'last_step': step, 'recovery_hashes': [totp.hash_recovery(c) for c in codes]})
                request.session.pop('mfa_setup_secret', None)
                request.session['mfa_verified'] = True
                audit.log_access(request, 'mfa', detail='turned two-step sign-in on', operator=False, dedupe=False)
                return render(request, 'accounts/security.html', {'on': True, 'new_codes': codes, 'recovery_left': len(codes), 'forced': user.is_staff, 'error': ''})
        elif action in ('disable', 'regenerate') and on:
            step = totp.verify(two.secret, code, two.last_step)
            if step is None or (action == 'disable' and not authenticate(request, username=user.get_username(), password=request.POST.get('password', ''))):
                context['error'] = 'The code, or the password, is not right.'
            elif action == 'disable' and user.is_staff and settings.REQUIRE_STAFF_MFA:
                context['error'] = 'Platform staff accounts must keep two-step sign-in on.'
            elif action == 'disable':
                two.delete()
                request.session['mfa_verified'] = False
                audit.log_access(request, 'mfa', detail='turned two-step sign-in off', operator=False, dedupe=False)
                messages.success(request, 'Two-step sign-in is off.')
                return redirect('accounts:security')
            else:
                codes = totp.new_recovery_codes()
                two.recovery_hashes = [totp.hash_recovery(c) for c in codes]
                two.last_step = step
                two.save(update_fields=['recovery_hashes', 'last_step'])
                return render(request, 'accounts/security.html', {'on': True, 'new_codes': codes, 'recovery_left': len(codes), 'forced': user.is_staff, 'error': ''})
    if not on:
        secret = request.session.get('mfa_setup_secret') or totp.new_secret()
        request.session['mfa_setup_secret'] = secret
        context.update({'secret': totp.grouped(secret), 'uri': totp.provisioning_uri(user.get_username() or user.email or 'account', secret)})
    return render(request, 'accounts/security.html', context)


@login_required
def access_log(request):
    """Every opening, export and sharing of this workspace's patient records, who did it and when, including the platform's own staff."""
    from clinics.access import managed_clinics
    from django.db.models import Q
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    rows = AccessLog.objects.filter(Q(workspace=profile) | Q(clinic__in=managed_clinics(profile)))
    only_operator = request.GET.get('who') == 'support'
    if only_operator:
        rows = rows.filter(operator=True)
    kind = request.GET.get('what', '')
    if kind in ('view', 'export', 'share', 'download', 'login', 'support', 'operator', 'mfa'):
        rows = rows.filter(action=kind)
    rows = list(rows.select_related('user')[:300])
    from .access import accessible_patients
    names = dict(accessible_patients(profile).filter(patient_code__in={r.patient_code for r in rows if r.patient_code}).values_list('patient_code', 'name'))
    context = workspace_context(request.user, profile)
    context.update({'active': 'settings', 'rows': [{'row': r, 'patient': names.get(r.patient_code, '')} for r in rows], 'only_operator': only_operator, 'what': kind,
                    'support_count': sum(1 for r in rows if r.operator)})
    return render(request, 'accounts/access_log.html', context)
