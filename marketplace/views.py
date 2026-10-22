"""Storefront views for the Marketplace and the Pharmacy.

Every view takes a `catalog` key (set in urls.py) so the same code serves both storefronts - see catalogs.py.
"""
import random
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string

from sajhya_health.throttle import too_many

from .catalogs import CATALOGS
from .models import Category, Order, OrderItem


def _catalog(key):
    return CATALOGS[key]


# ---- session cart ---------------------------------------------------------

def _get_cart(request, catalog):
    return request.session.get(catalog.session_cart, {})


def _save_cart(request, catalog, cart):
    request.session[catalog.session_cart] = cart
    request.session.modified = True


def cart_count(request, catalog):
    return sum(item['quantity'] for item in _get_cart(request, catalog).values())


def _build_cart_lines(cart):
    lines = []
    total = Decimal('0.00')
    for pid, item in cart.items():
        item_total = Decimal(str(item['price'])) * item['quantity']
        total += item_total
        lines.append({
            'product_id': int(pid), 'name': item['name'], 'price': Decimal(str(item['price'])),
            'quantity': item['quantity'], 'unit': item.get('unit', ''), 'category': item.get('category', ''),
            'image': item.get('image', ''), 'item_total': item_total,
        })
    return lines, total


def _get_shuffled_products(request, products, filter_key, session_key, reshuffle):
    """Random grid order, re-rolled on each fresh page load but held stable
    across the infinite-scroll batches of that same visit."""
    stored = request.session.get(session_key)
    if reshuffle or not stored or stored.get('key') != filter_key:
        ids = list(products.values_list('id', flat=True))
        random.shuffle(ids)
        stored = {'key': filter_key, 'ids': ids}
        request.session[session_key] = stored
        request.session.modified = True
    by_id = {p.id: p for p in products}
    return [by_id[pid] for pid in stored['ids'] if pid in by_id]


def _context(request, catalog, **extra):
    return {'catalog': catalog, 'cart_count': cart_count(request, catalog), **extra}


# ---- browsing --------------------------------------------------------------

def store_list(request, catalog):
    catalog = _catalog(catalog)
    model = catalog.model
    products = model.objects.filter(in_stock=True)
    if catalog.has_categories:
        products = products.select_related('category')

    category_id = request.GET.get('category', '').strip() if catalog.has_categories else ''
    if category_id:
        products = products.filter(category_id=category_id)
    search = request.GET.get('search', '').strip()
    if search:
        products = products.filter(name__icontains=search)

    featured = model.objects.filter(is_featured=True, in_stock=True)[:4]

    page_param = request.GET.get('page')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    ordered = _get_shuffled_products(
        request, products, filter_key=f'{category_id}|{search}', session_key=catalog.session_shuffle,
        reshuffle=not is_ajax and page_param in (None, '', '1'))
    page_obj = Paginator(ordered, 24).get_page(page_param)

    if is_ajax:
        html = render_to_string('marketplace/_product_cards.html', {'products': page_obj, 'catalog': catalog}, request=request)
        return JsonResponse({'html': html, 'has_next': page_obj.has_next(),
                             'next_page': page_obj.next_page_number() if page_obj.has_next() else None})

    return render(request, 'marketplace/marketplace.html', _context(
        request, catalog, categories=Category.objects.all() if catalog.has_categories else [],
        products=page_obj, page_obj=page_obj, featured=featured, selected_category=category_id, search=search))


def product_detail(request, product_id, catalog):
    catalog = _catalog(catalog)
    product = get_object_or_404(catalog.model, id=product_id)
    related = catalog.model.objects.filter(in_stock=True).exclude(id=product_id)
    if catalog.has_categories and product.category_id:
        related = related.filter(category=product.category).select_related('category')
    return render(request, 'marketplace/product_detail.html', _context(request, catalog, product=product, related=related[:4]))


# ---- cart --------------------------------------------------------------------

def add_to_cart(request, product_id, catalog):
    catalog = _catalog(catalog)
    product = get_object_or_404(catalog.model, id=product_id)
    cart = _get_cart(request, catalog)
    pid = str(product_id)
    if pid in cart:
        cart[pid]['quantity'] += 1
    else:
        cart[pid] = {'name': product.name, 'price': str(product.price), 'quantity': 1, 'unit': product.unit,
                     'category': product.category_name, 'image': product.image_url_path}
    _save_cart(request, catalog, cart)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'cart_count': cart_count(request, catalog)})
    messages.success(request, f'"{product.name}" added to cart!')
    return redirect(request.GET.get('next') or request.META.get('HTTP_REFERER') or catalog.urls['list'])


def remove_from_cart(request, product_id, catalog):
    catalog = _catalog(catalog)
    cart = _get_cart(request, catalog)
    if str(product_id) in cart:
        del cart[str(product_id)]
        _save_cart(request, catalog, cart)
        messages.success(request, 'Item removed from cart.')
    return redirect(catalog.urls['cart'])


def update_cart(request, product_id, catalog):
    catalog = _catalog(catalog)
    if request.method != 'POST':
        return redirect(catalog.urls['cart'])
    cart = _get_cart(request, catalog)
    pid = str(product_id)
    try:
        quantity = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        quantity = 1
    if pid in cart:
        if quantity <= 0:
            del cart[pid]
        else:
            cart[pid]['quantity'] = min(quantity, 99)
    _save_cart(request, catalog, cart)
    return redirect(catalog.urls['cart'])


def view_cart(request, catalog):
    catalog = _catalog(catalog)
    cart_items, total = _build_cart_lines(_get_cart(request, catalog))
    return render(request, 'marketplace/cart.html', _context(request, catalog, cart_items=cart_items, total=total))


def checkout(request, catalog):
    catalog = _catalog(catalog)
    cart = _get_cart(request, catalog)
    if not cart:
        messages.warning(request, 'Your cart is empty.')
        return redirect(catalog.urls['list'])

    cart_items, total = _build_cart_lines(cart)

    if request.method == 'POST' and too_many(request, 'checkout', 15):
        messages.error(request, 'Too many orders from this connection in the last hour. Please try again later or call us.')
        return redirect(request.path)
    if request.method == 'POST':
        fields = {k: request.POST.get(k, '').strip() for k in ('customer_name', 'customer_email', 'customer_phone', 'delivery_address', 'notes')}
        if not all(fields[k] for k in ('customer_name', 'customer_email', 'customer_phone', 'delivery_address')):
            messages.error(request, 'Please fill in all required fields.')
        else:
            order = Order.objects.create(order_type=catalog.key, user=request.user if request.user.is_authenticated else None,
                                         total_amount=total, **fields)
            link = 'pharmacy_product' if catalog.key == 'pharmacy' else 'product'
            for item in cart_items:
                OrderItem.objects.create(
                    order=order, product_name=item['name'], quantity=item['quantity'], unit_price=item['price'],
                    **{link: catalog.model.objects.filter(id=item['product_id']).first()})
            _save_cart(request, catalog, {})
            # remember which orders this browser placed: the confirmation page shows personal details
            request.session['my_orders'] = (request.session.get('my_orders', []) + [order.order_number])[-20:]
            return redirect(catalog.urls['success'], order_number=order.order_number)

    from portal.prefill import checkout_prefill
    return render(request, 'marketplace/checkout.html', _context(request, catalog, cart_items=cart_items, total=total, cart_count=0, prefill=checkout_prefill(request.user)))


def order_success(request, order_number, catalog):
    catalog = _catalog(catalog)
    order = get_object_or_404(Order, order_number=order_number, order_type=catalog.key)
    owns = order_number in request.session.get('my_orders', []) or (request.user.is_authenticated and order.user_id == request.user.pk)
    if not (owns or request.user.is_staff):
        raise Http404  # order numbers are guessable; only the buyer (or staff) may see the details
    return render(request, 'marketplace/order_success.html', _context(request, catalog, order=order))
