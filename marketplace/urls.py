from django.urls import path

from . import views

app_name = 'marketplace'

# Each route takes the storefront's key as an extra argument, so one view serves both storefronts.
MARKETPLACE = {'catalog': 'marketplace'}
PHARMACY = {'catalog': 'pharmacy'}

urlpatterns = [
    # Marketplace
    path('', views.store_list, MARKETPLACE, name='marketplace'),
    path('product/<int:product_id>/', views.product_detail, MARKETPLACE, name='product-detail'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, MARKETPLACE, name='add-to-cart'),
    path('remove-from-cart/<int:product_id>/', views.remove_from_cart, MARKETPLACE, name='remove-from-cart'),
    path('update-cart/<int:product_id>/', views.update_cart, MARKETPLACE, name='update-cart'),
    path('cart/', views.view_cart, MARKETPLACE, name='view-cart'),
    path('checkout/', views.checkout, MARKETPLACE, name='checkout'),
    path('order-success/<str:order_number>/', views.order_success, MARKETPLACE, name='order-success'),
    # Pharmacy
    path('pharmacy/', views.store_list, PHARMACY, name='pharmacy'),
    path('pharmacy/product/<int:product_id>/', views.product_detail, PHARMACY, name='pharmacy-product-detail'),
    path('pharmacy/add-to-cart/<int:product_id>/', views.add_to_cart, PHARMACY, name='pharmacy-add-to-cart'),
    path('pharmacy/remove-from-cart/<int:product_id>/', views.remove_from_cart, PHARMACY, name='pharmacy-remove-from-cart'),
    path('pharmacy/update-cart/<int:product_id>/', views.update_cart, PHARMACY, name='pharmacy-update-cart'),
    path('pharmacy/cart/', views.view_cart, PHARMACY, name='pharmacy-view-cart'),
    path('pharmacy/checkout/', views.checkout, PHARMACY, name='pharmacy-checkout'),
    path('pharmacy/order-success/<str:order_number>/', views.order_success, PHARMACY, name='pharmacy-order-success'),
]
