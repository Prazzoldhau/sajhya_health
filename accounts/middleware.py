"""Keeps the clinical workspace closed until a professional's credentials are approved.

Two layers, so a forgotten check in a new view cannot open the door:
1. this middleware turns away any professional who is not approved from every path in settings.WORKSPACE_PATH_PREFIXES
   (pages are redirected to the verification-status page, scripts/forms get a 403 JSON answer);
2. the access helpers in accounts/access.py refuse the same people (403).

When adding a new workspace area, add its URL prefix to WORKSPACE_PATH_PREFIXES in settings.py.
"""
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import ProfessionalProfile

LOCKED_MESSAGE = 'Your credentials have not been verified yet, so the workspace is closed. We will open it as soon as they are approved.'


def wants_json(request):
    return (request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
            or request.content_type == 'application/json' or request.method != 'GET')


class VerifiedWorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and request.path.startswith(tuple(settings.WORKSPACE_PATH_PREFIXES)):
            profile = getattr(getattr(user, 'account', None), 'profile', None)
            if profile is not None and profile.status != ProfessionalProfile.APPROVED:
                if wants_json(request):
                    return JsonResponse({'ok': False, 'error': LOCKED_MESSAGE}, status=403)
                messages.info(request, LOCKED_MESSAGE)
                return redirect('accounts:welcome')
        return self.get_response(request)
