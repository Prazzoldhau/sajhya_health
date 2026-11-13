"""Where a page may send the browser next. A "next" or "back" address comes from the address bar or a form, so anyone can put anything in it:
only a path on this same site is followed (never another host, a `//host` or `/\\host` address that browsers read as another host, or a `javascript:` link)."""
from django.utils.http import url_has_allowed_host_and_scheme


def local_path(request, value, default=''):
    """`value` when it is a plain path on this site (for example '/billing/?date=2026-11-01'), else `default`."""
    value = (value or '').strip()
    if (value.startswith('/') and not value.startswith('//') and '\\' not in value and '\n' not in value and '\r' not in value
            and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure())):
        return value
    return default


def same_site_url(request, value, default=''):
    """Like local_path, but also accepts a full address on this same host (a Referer header is one)."""
    value = (value or '').strip()
    if value and '\\' not in value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return default
