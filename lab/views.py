from decimal import Decimal

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from sajhya_health.throttle import too_many

from .models import LabTest, LabTestPanel, LabTestRequest, LabTestRequestItem

# No cart: multi-select happens with checkboxes on the browse page, and one POST books everything checked as a
# single LabTestRequest with one item per test/panel.


def lab_tests(request):
    if request.method == 'POST':
        return _book(request)

    search = request.GET.get('search', '').strip()
    panels = LabTestPanel.objects.filter(is_active=True).prefetch_related('tests').order_by('-is_featured', 'name')
    tests = LabTest.objects.filter(is_active=True)
    if search:
        panels = panels.filter(name__icontains=search)
        tests = tests.filter(name__icontains=search)

    labels = dict(LabTest.CATEGORY_CHOICES)
    grouped = {}
    for t in tests.order_by('category', 'name'):
        grouped.setdefault(t.category, []).append(t)
    from portal.prefill import checkout_prefill
    return render(request, 'lab/lab_tests.html', {
        'prefill': checkout_prefill(request.user), 'panels': panels, 'categorized_tests': [(labels.get(cat, cat), items) for cat, items in grouped.items()], 'search': search})


def _book(request):
    if too_many(request, 'lab-booking', 15):
        messages.error(request, 'Too many bookings from this connection in the last hour. Please try again later or call us.')
        return redirect('lab:tests')
    keys = request.POST.getlist('items')
    if not keys:
        messages.error(request, 'Select at least one test or panel first.')
        return redirect('lab:tests')
    fields = {k: request.POST.get(k, '').strip() for k in ('customer_name', 'customer_email', 'customer_phone', 'delivery_address')}
    if not all(fields.values()):
        messages.error(request, 'Please fill in all required fields.')
        return redirect('lab:tests')

    items = []  # (test, panel, name, price)
    for key in keys:
        kind, _, item_id = key.partition('-')
        if not item_id.isdigit():
            continue
        if kind == 'test':
            obj = LabTest.objects.filter(id=item_id, is_active=True).first()
            if obj:
                items.append((obj, None, obj.name, obj.price))
        elif kind == 'panel':
            obj = LabTestPanel.objects.filter(id=item_id, is_active=True).first()
            if obj:
                items.append((None, obj, obj.name, obj.price))
    if not items:
        messages.error(request, 'Your selected tests are no longer available - please pick again.')
        return redirect('lab:tests')

    booking = LabTestRequest.objects.create(
        user=request.user if request.user.is_authenticated else None,
        customer_name=fields['customer_name'], customer_email=fields['customer_email'], customer_phone=fields['customer_phone'],
        collection_address=fields['delivery_address'], notes=request.POST.get('notes', '').strip(),
        total_amount=sum((price for *_, price in items), Decimal('0.00')))
    for test, panel, name, price in items:
        LabTestRequestItem.objects.create(request=booking, lab_test=test, lab_panel=panel, test_name=name, price=price)
    # remember which requests this browser made: the confirmation shows personal details
    request.session['my_lab_requests'] = (request.session.get('my_lab_requests', []) + [booking.request_number])[-20:]
    return redirect('lab:order-success', request_number=booking.request_number)


def lab_test_detail(request, test_id):
    return render(request, 'lab/lab_test_detail.html', {'test': get_object_or_404(LabTest, id=test_id, is_active=True)})


def lab_panel_detail(request, panel_id):
    return render(request, 'lab/lab_panel_detail.html', {'panel': get_object_or_404(LabTestPanel, id=panel_id, is_active=True)})


def lab_order_success(request, request_number):
    booking = get_object_or_404(LabTestRequest, request_number=request_number)
    mine = request_number in request.session.get('my_lab_requests', []) or (request.user.is_authenticated and booking.user_id == request.user.pk)
    if not mine and not request.user.is_staff:
        raise Http404  # request numbers are guessable; only the person who booked (or staff) may see the details
    return render(request, 'lab/lab_order_success.html', {'lab_request': booking})


def lab_search(request):
    """Type-ahead used by the patient profile's lab-test section: tests and panels matching the text."""
    if not request.user.is_authenticated:
        return JsonResponse({'results': []}, status=401)
    from accounts.access import require_workspace
    require_workspace(request)  # clinical catalogue lookups belong to verified professionals
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    tests = LabTest.objects.filter(is_active=True, name__icontains=q)[:8]
    panels = LabTestPanel.objects.filter(is_active=True, name__icontains=q)[:4]
    return JsonResponse({'results': (
        [{'kind': 'test', 'id': t.pk, 'name': t.name, 'detail': t.get_category_display()} for t in tests]
        + [{'kind': 'panel', 'id': p.pk, 'name': p.name, 'detail': 'Panel'} for p in panels])})
