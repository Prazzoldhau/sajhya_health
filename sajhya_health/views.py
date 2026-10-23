import logging

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from billing.models import Plan
from marketplace.models import Product

logger = logging.getLogger(__name__)


def landing_page(request):
    # Homepage marketplace teaser: in-stock, real photo, non-zero price, random 8 per request.
    marketplace_preview = (
        Product.objects.filter(in_stock=True)
        .exclude(image='').exclude(price=0)
        .select_related('category')
        .order_by('?')[:8]
    )
    plans = {p.code: p for p in Plan.objects.all()}
    return render(request, 'landing.html', {'marketplace_preview': marketplace_preview, 'plans': plans})


def healthz(request):
    """Liveness/readiness probe for the host or load balancer: confirms the app can reach the database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        logger.exception('Health check: the database is not reachable')  # the traceback lands in logs/sajhya.log
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})


def page_not_found(request, exception=None):
    return render(request, '404.html', status=404)


def permission_denied(request, exception=None):
    return render(request, '403.html', status=403)


def server_error(request):
    return render(request, '500.html', status=500)
