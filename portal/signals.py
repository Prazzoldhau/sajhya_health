from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .prefill import attach_session_orders


@receiver(user_logged_in)
def claim_guest_orders(sender, request, user, **kwargs):
    """Signing in (or signing up) in the browser that placed guest orders / lab bookings attaches them to the account."""
    if request is not None and hasattr(request, 'session'):
        attach_session_orders(request, user)
