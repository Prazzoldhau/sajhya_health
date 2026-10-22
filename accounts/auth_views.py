"""Password reset (forgot password) and password change.

Design notes, so this is easy to troubleshoot later:
- Uses Django's token mechanism: the emailed link carries a one-time token that stops working once the
  password changes or after PASSWORD_RESET_TIMEOUT seconds (1 hour, see settings).
- The "done" page is shown whether or not the email belongs to an account, so the form cannot be used
  to discover which addresses are registered.
- A failure to send the email (bad SMTP settings, mail server down) is logged by Django and not shown to the
  visitor, for the same reason; look for "Failed to send password reset email" (logger django.contrib.auth).
- Requests are throttled per IP address (and per email) to stop the form being used to flood inboxes.
- A successful reset also clears any sign-in lockout for that user.
"""
import logging

from axes.utils import reset as reset_lockout
from django.contrib.auth.views import PasswordChangeView, PasswordResetConfirmView, PasswordResetView
from django.core.cache import cache
from django.shortcuts import render
from django.urls import reverse_lazy

from .forms import StyledPasswordResetForm, StyledSetPasswordForm

logger = logging.getLogger(__name__)

RESET_REQUESTS_PER_HOUR = 5


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    from django.conf import settings
    if forwarded and getattr(settings, 'AXES_IPWARE_PROXY_COUNT', 0):  # only trusted when BEHIND_PROXY is on
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


class ThrottledPasswordResetView(PasswordResetView):
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/emails/password_reset_email.txt'
    html_email_template_name = 'accounts/emails/password_reset_email.html'
    subject_template_name = 'accounts/emails/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password-reset-done')
    form_class = StyledPasswordResetForm

    def post(self, request, *args, **kwargs):
        key = f'pwreset:ip:{client_ip(request)}'
        attempts = cache.get(key, 0)
        if attempts >= RESET_REQUESTS_PER_HOUR:
            logger.warning('Password reset throttled for %s', client_ip(request))
            return render(request, 'accounts/password_reset_throttled.html', status=429)
        cache.set(key, attempts + 1, 3600)
        return super().post(request, *args, **kwargs)


class ResetConfirmView(PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password-reset-complete')
    form_class = StyledSetPasswordForm
    post_reset_login = False

    def form_valid(self, form):
        response = super().form_valid(form)
        reset_lockout(username=form.user.get_username())  # a locked-out user who resets can sign in straight away
        return response


class ChangePasswordView(PasswordChangeView):
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('accounts:password-change-done')
