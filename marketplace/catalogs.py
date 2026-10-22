"""The two storefronts - Marketplace (products) and Pharmacy (medicines) - share one set of views and templates.

A `Catalog` says which model, which session cart and which URL names a storefront uses. The URL names are
passed to the templates as `catalog.urls.<key>` so a template never hard-codes "marketplace" or "pharmacy".
To add a third storefront, add a Catalog here, a model, and a block of routes in urls.py that pass its name.
"""
from dataclasses import dataclass, field

from .models import PharmacyProduct, Product


@dataclass(frozen=True)
class Catalog:
    key: str  # 'marketplace' | 'pharmacy'; also the Order.order_type
    label: str
    model: type
    session_cart: str
    session_shuffle: str
    has_categories: bool
    search_hint: str
    tagline: str
    urls: dict = field(default_factory=dict)

    def category_label(self, product):
        return product.category_name


MARKETPLACE = Catalog(
    key='marketplace', label='Marketplace', model=Product, session_cart='marketplace_cart', session_shuffle='marketplace_shuffle',
    has_categories=True, search_hint='Search for products...',
    tagline='Braces, supports, therapy equipment and rehab supplies.',
    urls={'list': 'marketplace:marketplace', 'detail': 'marketplace:product-detail', 'add': 'marketplace:add-to-cart',
          'remove': 'marketplace:remove-from-cart', 'update': 'marketplace:update-cart', 'cart': 'marketplace:view-cart',
          'checkout': 'marketplace:checkout', 'success': 'marketplace:order-success'},
)

PHARMACY = Catalog(
    key='pharmacy', label='Pharmacy', model=PharmacyProduct, session_cart='pharmacy_cart', session_shuffle='pharmacy_shuffle',
    has_categories=False, search_hint='Search medicines...',
    tagline='Medicines and healthcare products, delivered across Nepal.',
    urls={'list': 'marketplace:pharmacy', 'detail': 'marketplace:pharmacy-product-detail', 'add': 'marketplace:pharmacy-add-to-cart',
          'remove': 'marketplace:pharmacy-remove-from-cart', 'update': 'marketplace:pharmacy-update-cart', 'cart': 'marketplace:pharmacy-view-cart',
          'checkout': 'marketplace:pharmacy-checkout', 'success': 'marketplace:pharmacy-order-success'},
)

CATALOGS = {c.key: c for c in (MARKETPLACE, PHARMACY)}
