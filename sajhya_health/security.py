"""Browser-side protections and session hygiene.

- SecurityHeadersMiddleware: a Content-Security-Policy. The part that cannot break a page (no framing by other sites, no plugins, no <base> tricks, forms
  post only to this site) is enforced. The strict part (only this site's scripts, styles and images, plus Google Fonts and YouTube) is sent as
  Report-Only, so a browser says in its console and at /csp-report/ what it would block before it is switched on: the pages still use inline
  scripts and styles, which the strict policy must allow for now.
- IdleLogoutMiddleware: a signed-in person who has done nothing for IDLE_LOGOUT_MINUTES is signed out (clinic computers are shared and left open).
"""
import json
import time
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, resolve_url
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import logging

log = logging.getLogger('sajhya.csp')

ENFORCED = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"
STRICT = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; "
          "img-src 'self' data: blob: https:; media-src 'self' https: blob:; frame-src https://www.youtube.com https://www.youtube-nocookie.com; connect-src 'self'; "
          "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; report-uri /csp-report/")


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not getattr(settings, 'CSP_ENABLED', True):
            return response
        response.setdefault('Content-Security-Policy', ENFORCED)
        response.setdefault('Content-Security-Policy-Report-Only', STRICT)
        response.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()')
        return response


@csrf_exempt
@require_POST
def csp_report(request):
    """Browsers post here what the strict policy would have blocked. Small, counted per hour, and only written to the log."""
    if len(request.body) > 4096:
        return HttpResponse(status=413)
    count = cache.get('csp-reports', 0)
    if count < 200:
        cache.set('csp-reports', count + 1, 3600)
        try:
            body = json.loads(request.body or b'{}')
            detail = body.get('csp-report', body) if isinstance(body, dict) else {}
            log.warning('CSP would block: %s on %s', str(detail.get('blocked-uri', ''))[:200], str(detail.get('document-uri', ''))[:200])
        except ValueError:
            pass
    return HttpResponse(status=204)


class IdleLogoutMiddleware:
    """Signs a person out after IDLE_LOGOUT_MINUTES without a request. The time is kept in the session and refreshed at most once a minute."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        minutes = getattr(settings, 'IDLE_LOGOUT_MINUTES', 0)
        user = getattr(request, 'user', None)
        if minutes and user is not None and user.is_authenticated:
            now = int(time.time())
            last = request.session.get('last_seen')
            if last and now - last > minutes * 60:
                logout(request)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
                    return JsonResponse({'ok': False, 'error': 'You were signed out after a period of no activity. Sign in again.'}, status=401)
                messages.info(request, f'You were signed out after {minutes} minutes without activity, to protect patient records. Sign in again.')
                target = resolve_url(settings.LOGIN_URL)
                if request.method == 'GET':
                    target += f'?next={quote(request.get_full_path())}'
                return redirect(target)
            if not last or now - last >= 60:
                request.session['last_seen'] = now
        return self.get_response(request)
