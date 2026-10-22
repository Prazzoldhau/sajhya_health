"""Small helpers that tie shop orders and lab bookings to the signed-in account (imports are lazy: marketplace and lab use this too)."""


def checkout_prefill(user):
    """Name / phone / email / address to pre-fill a checkout or lab booking form for a signed-in patient.
    Taken from their latest order or booking (they typed it themselves), else their linked record's name and account email."""
    if not user.is_authenticated:
        return {}
    from lab.models import LabTestRequest
    from marketplace.models import Order

    last_order = Order.objects.filter(user=user).first()
    last_lab = LabTestRequest.objects.filter(user=user).first()
    latest = max((x for x in (last_order, last_lab) if x), key=lambda x: x.created_at, default=None)
    link = user.patient_links.select_related('patient').first()
    name = (latest.customer_name if latest else '') or user.get_full_name() or (link.patient.name if link else '')
    return {
        'name': name, 'email': user.email or (latest.customer_email if latest else ''),
        'phone': latest.customer_phone if latest else '',
        'address': (getattr(latest, 'delivery_address', None) or getattr(latest, 'collection_address', '')) if latest else '',
    }


def attach_session_orders(request, user):
    """Orders and lab bookings this browser made as a guest become the user's once they sign in or sign up in the same browser
    (the browser already proved it made them). Only rows nobody owns are touched. Returns how many were attached."""
    from lab.models import LabTestRequest
    from marketplace.models import Order

    count = 0
    numbers = request.session.get('my_orders', [])
    if numbers:
        count += Order.objects.filter(order_number__in=numbers, user__isnull=True).update(user=user)
    numbers = request.session.get('my_lab_requests', [])
    if numbers:
        count += LabTestRequest.objects.filter(request_number__in=numbers, user__isnull=True).update(user=user)
    return count
