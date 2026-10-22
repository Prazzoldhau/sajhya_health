from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Category, Order, PharmacyProduct, Product


class MarketplaceTests(TestCase):
    def setUp(self):
        self.braces = Category.objects.create(name='Braces')
        self.bands = Category.objects.create(name='Bands')
        self.knee = Product.objects.create(name='Knee Brace', category=self.braces, price=Decimal('1200.00'), image='categorized_product/x/knee.png', is_featured=True)
        self.band = Product.objects.create(name='Resistance Band', category=self.bands, price=Decimal('300.00'))
        self.gone = Product.objects.create(name='Out Of Stock Item', category=self.braces, price=Decimal('50.00'), in_stock=False)

    def test_store_is_public_and_hides_out_of_stock(self):
        page = self.client.get(reverse('marketplace:marketplace'))
        self.assertEqual(page.status_code, 200)
        names = [p.name for p in page.context['products']]
        self.assertCountEqual(names, ['Knee Brace', 'Resistance Band'])

    def test_category_filter_and_search(self):
        by_cat = self.client.get(reverse('marketplace:marketplace'), {'category': self.bands.pk})
        self.assertEqual([p.name for p in by_cat.context['products']], ['Resistance Band'])
        found = self.client.get(reverse('marketplace:marketplace'), {'search': 'knee'})
        self.assertEqual([p.name for p in found.context['products']], ['Knee Brace'])
        self.assertEqual(len(self.client.get(reverse('marketplace:marketplace'), {'search': 'zzz'}).context['products']), 0)

    def test_infinite_scroll_batches_return_json(self):
        for i in range(30):
            Product.objects.create(name=f'Bulk {i}', price=10)
        first = self.client.get(reverse('marketplace:marketplace'))
        self.assertEqual(len(first.context['products']), 24)
        batch = self.client.get(reverse('marketplace:marketplace'), {'page': 2}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data = batch.json()
        self.assertIn('html', data)
        self.assertFalse(data['has_next'])

    def test_product_detail(self):
        self.assertEqual(self.client.get(reverse('marketplace:product-detail', args=[self.knee.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('marketplace:product-detail', args=[99999])).status_code, 404)

    def test_cart_add_update_remove(self):
        add = reverse('marketplace:add-to-cart', args=[self.knee.pk])
        self.client.get(add)
        ajax = self.client.get(add, HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
        self.assertEqual(ajax['cart_count'], 2)
        cart = self.client.get(reverse('marketplace:view-cart'))
        self.assertEqual(cart.context['total'], Decimal('2400.00'))
        self.client.post(reverse('marketplace:update-cart', args=[self.knee.pk]), {'quantity': 5})
        self.assertEqual(self.client.get(reverse('marketplace:view-cart')).context['total'], Decimal('6000.00'))
        self.client.post(reverse('marketplace:update-cart', args=[self.knee.pk]), {'quantity': 'abc'})  # bad input falls back to 1
        self.assertEqual(self.client.get(reverse('marketplace:view-cart')).context['total'], Decimal('1200.00'))
        self.client.get(reverse('marketplace:remove-from-cart', args=[self.knee.pk]))
        self.assertEqual(self.client.get(reverse('marketplace:view-cart')).context['cart_items'], [])

    def test_checkout_creates_order_and_empties_the_cart(self):
        self.assertRedirects(self.client.get(reverse('marketplace:checkout')), reverse('marketplace:marketplace'))  # empty cart
        self.client.get(reverse('marketplace:add-to-cart', args=[self.knee.pk]))
        self.client.get(reverse('marketplace:add-to-cart', args=[self.band.pk]))
        incomplete = self.client.post(reverse('marketplace:checkout'), {'customer_name': 'Ram'})
        self.assertEqual(incomplete.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        r = self.client.post(reverse('marketplace:checkout'), {'customer_name': 'Ram', 'customer_email': 'r@example.com', 'customer_phone': '9800', 'delivery_address': 'Kathmandu'})
        order = Order.objects.get()
        self.assertRedirects(r, reverse('marketplace:order-success', args=[order.order_number]))
        self.assertEqual((order.total_amount, order.items.count(), order.status), (Decimal('1500.00'), 2, 'pending'))
        self.assertTrue(order.order_number.startswith('ORD-'))
        self.assertEqual(self.client.get(reverse('marketplace:view-cart')).context['cart_items'], [])
        self.assertEqual(self.client.get(reverse('marketplace:order-success', args=[order.order_number])).status_code, 200)

    def test_cart_price_is_a_snapshot_not_trusted_from_the_form(self):
        self.client.get(reverse('marketplace:add-to-cart', args=[self.knee.pk]))
        self.client.post(reverse('marketplace:checkout'), {'customer_name': 'Ram', 'customer_email': 'r@example.com', 'customer_phone': '9', 'delivery_address': 'x', 'total_amount': '1'})
        self.assertEqual(Order.objects.get().total_amount, Decimal('1200.00'))

    def test_order_confirmation_is_only_visible_to_the_buyer(self):
        self.client.get(reverse('marketplace:add-to-cart', args=[self.knee.pk]))
        self.client.post(reverse('marketplace:checkout'), {'customer_name': 'Ram', 'customer_email': 'r@example.com', 'customer_phone': '9', 'delivery_address': 'Secret Street 1'})
        order = Order.objects.get()
        url = reverse('marketplace:order-success', args=[order.order_number])
        self.assertContains(self.client.get(url), 'Secret Street 1')
        stranger = self.client_class()
        self.assertEqual(stranger.get(url).status_code, 404)
        from django.contrib.auth.models import User
        staff = User.objects.create_user('staffer', password='x', is_staff=True)
        stranger.force_login(staff)
        self.assertEqual(stranger.get(url).status_code, 200)


class PharmacyTests(TestCase):
    def setUp(self):
        from .models import PharmacyProduct
        self.rx = PharmacyProduct.objects.create(name='Amoxicillin 500', category='Antibiotic', price=Decimal('120.00'), requires_prescription=True, image='pharmacy/x.png')
        self.quote = PharmacyProduct.objects.create(name='Gabapin NT', price=0)
        self.gone = PharmacyProduct.objects.create(name='Gone', price=5, in_stock=False)

    def test_pharmacy_is_public_and_separate_from_the_marketplace(self):
        Product.objects.create(name='Knee Brace', price=1200)
        page = self.client.get(reverse('marketplace:pharmacy'))
        self.assertEqual(page.status_code, 200)
        self.assertCountEqual([p.name for p in page.context['products']], ['Amoxicillin 500', 'Gabapin NT'])
        self.assertEqual(page.context['catalog'].key, 'pharmacy')
        self.assertContains(page, 'Search medicines')
        self.assertNotContains(page, 'Knee Brace')
        self.assertEqual(self.client.get(reverse('marketplace:pharmacy'), {'search': 'amox'}).context['products'].paginator.count, 1)

    def test_zero_priced_items_read_price_on_request(self):
        self.assertContains(self.client.get(reverse('marketplace:pharmacy')), 'Price on request')
        detail = self.client.get(reverse('marketplace:pharmacy-product-detail', args=[self.quote.pk]))
        self.assertContains(detail, 'Price on request')
        rx = self.client.get(reverse('marketplace:pharmacy-product-detail', args=[self.rx.pk]))
        self.assertContains(rx, 'Prescription required')

    def test_pharmacy_cart_is_independent_of_the_marketplace_cart(self):
        shop = Product.objects.create(name='Knee Brace', price=1200)
        self.client.get(reverse('marketplace:add-to-cart', args=[shop.pk]))
        self.client.get(reverse('marketplace:pharmacy-add-to-cart', args=[self.rx.pk]))
        self.client.get(reverse('marketplace:pharmacy-add-to-cart', args=[self.rx.pk]))
        pharmacy = self.client.get(reverse('marketplace:pharmacy-view-cart'))
        self.assertEqual((len(pharmacy.context['cart_items']), pharmacy.context['total']), (1, Decimal('240.00')))
        self.assertEqual(self.client.get(reverse('marketplace:view-cart')).context['total'], Decimal('1200.00'))
        self.client.post(reverse('marketplace:pharmacy-update-cart', args=[self.rx.pk]), {'quantity': 3})
        self.assertEqual(self.client.get(reverse('marketplace:pharmacy-view-cart')).context['total'], Decimal('360.00'))
        self.client.get(reverse('marketplace:pharmacy-remove-from-cart', args=[self.rx.pk]))
        self.assertEqual(self.client.get(reverse('marketplace:pharmacy-view-cart')).context['cart_items'], [])

    def test_pharmacy_checkout_creates_a_pharmacy_order(self):
        self.client.get(reverse('marketplace:pharmacy-add-to-cart', args=[self.rx.pk]))
        self.client.get(reverse('marketplace:pharmacy-add-to-cart', args=[self.quote.pk]))
        r = self.client.post(reverse('marketplace:pharmacy-checkout'), {'customer_name': 'Ram', 'customer_email': 'r@example.com', 'customer_phone': '9', 'delivery_address': 'KTM'})
        order = Order.objects.get()
        self.assertRedirects(r, reverse('marketplace:pharmacy-order-success', args=[order.order_number]))
        self.assertEqual((order.order_type, order.total_amount, order.items.count()), ('pharmacy', Decimal('120.00'), 2))
        self.assertEqual(order.items.get(product_name='Amoxicillin 500').pharmacy_product, self.rx)
        self.assertEqual(self.client.get(reverse('marketplace:pharmacy-order-success', args=[order.order_number])).status_code, 200)
        # an order only opens under its own storefront
        self.assertEqual(self.client.get(reverse('marketplace:order-success', args=[order.order_number])).status_code, 404)

    def test_seeded_pharmacy_catalogue_loads(self):
        from django.core.management import call_command
        from .models import PharmacyProduct
        PharmacyProduct.objects.all().delete()
        call_command('load_pharmacy')
        self.assertEqual(PharmacyProduct.objects.count(), 35)

    def test_landing_and_header_link_to_pharmacy_and_lab(self):
        home = self.client.get('/')
        self.assertContains(home, reverse('marketplace:pharmacy'))
        self.assertContains(home, reverse('lab:tests'))
        self.assertContains(self.client.get(reverse('marketplace:marketplace')), reverse('lab:tests'))
