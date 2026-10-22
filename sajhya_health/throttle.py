"""A small per-IP rate limit for public forms that anyone can submit without signing in (checkout, lab booking, sign-up).

Without it a script could flood the staff with fake orders or create thousands of accounts. Counters live in the cache
(shared by all workers through the file cache in production). Sign-in and password reset have their own protection (axes / auth_views).
"""
from axes.helpers import get_client_ip_address
from django.conf import settings
from django.core.cache import cache


def too_many(request, scope, limit, seconds=3600):
    """True when this IP has already used its `limit` submissions of `scope` in the last `seconds`; otherwise counts this one."""
    if not settings.THROTTLE_ENABLED:
        return False
    key = f'throttle:{scope}:{get_client_ip_address(request)}'
    used = cache.get(key, 0)
    if used >= limit:
        return True
    cache.set(key, used + 1, seconds)
    return False
