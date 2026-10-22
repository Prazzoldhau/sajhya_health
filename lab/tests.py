from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import LabTest, LabTestPanel, LabTestRequest


class LabStorefrontTests(TestCase):
    def setUp(self):
        self.cbc = LabTest.objects.create(name='CBC', category='hematology', price=Decimal('400'), turnaround_time='Same day')
        self.fbs = LabTest.objects.create(name='Fasting Blood Sugar', category='biochemistry', price=Decimal('200'))
        self.hidden = LabTest.objects.create(name='Retired Test', category='other', price=Decimal('50'), is_active=False)
        self.panel = LabTestPanel.objects.create(name='Diabetes Panel', price=Decimal('500'), is_featured=True)
        self.panel.tests.set([self.cbc, self.fbs])

    def book(self, items, **extra):
        data = {'items': items, 'customer_name': 'Ram', 'customer_email': 'r@example.com', 'customer_phone': '9800', 'delivery_address': 'Kathmandu', **extra}
        return self.client.post(reverse('lab:tests'), data)

    def test_public_page_groups_tests_and_lists_panels(self):
        page = self.client.get(reverse('lab:tests'))
        self.assertEqual(page.status_code, 200)
        self.assertEqual([c for c, _ in page.context['categorized_tests']], ['Biochemistry', 'Hematology'])
        self.assertNotContains(page, 'Retired Test')
        self.assertContains(page, 'Diabetes Panel')

    def test_search(self):
        page = self.client.get(reverse('lab:tests'), {'search': 'sugar'})
        self.assertEqual([t.name for _, tests in page.context['categorized_tests'] for t in tests], ['Fasting Blood Sugar'])
        self.assertEqual(len(self.client.get(reverse('lab:tests'), {'search': 'zzz'}).context['panels']), 0)

    def test_panel_savings(self):
        self.assertEqual((self.panel.a_la_carte_total, self.panel.savings), (Decimal('600'), Decimal('100')))

    def test_booking_creates_a_request_with_snapshot_prices(self):
        r = self.book([f'test-{self.cbc.pk}', f'panel-{self.panel.pk}'])
        booking = LabTestRequest.objects.get()
        self.assertRedirects(r, reverse('lab:order-success', args=[booking.request_number]))
        self.assertEqual((booking.total_amount, booking.items.count(), booking.status), (Decimal('900'), 2, 'pending'))
        self.assertTrue(booking.request_number.startswith('LAB-'))
        self.cbc.price = Decimal('999')
        self.cbc.save()
        self.assertEqual(booking.items.get(lab_test=self.cbc).price, Decimal('400'))  # history is not rewritten

    def test_booking_validation(self):
        self.book([])
        self.book([f'test-{self.cbc.pk}'], customer_phone='')
        self.book([f'test-{self.hidden.pk}', 'test-abc', 'bogus-1'])
        self.assertEqual(LabTestRequest.objects.count(), 0)

    def test_confirmation_is_private_to_the_booker(self):
        self.book([f'test-{self.cbc.pk}'])
        booking = LabTestRequest.objects.get()
        url = reverse('lab:order-success', args=[booking.request_number])
        self.assertContains(self.client.get(url), 'Kathmandu')
        stranger = self.client_class()
        self.assertEqual(stranger.get(url).status_code, 404)
        stranger.force_login(User.objects.create_user('staffer', password='x', is_staff=True))
        self.assertEqual(stranger.get(url).status_code, 200)

    def test_detail_pages(self):
        self.assertEqual(self.client.get(reverse('lab:test-detail', args=[self.cbc.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('lab:test-detail', args=[self.hidden.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('lab:panel-detail', args=[self.panel.pk])).status_code, 200)

    def test_seeded_catalogue_loads(self):
        from django.core.management import call_command
        LabTest.objects.all().delete()
        call_command('load_lab_catalog')
        self.assertEqual((LabTest.objects.count(), LabTestPanel.objects.count()), (33, 10))
        self.assertTrue(LabTestPanel.objects.get(name='Diabetes Panel').tests.count() >= 3)

    def test_catalogue_search_endpoint_needs_login(self):
        url = reverse('lab:search')
        self.assertEqual(self.client.get(url, {'q': 'cbc'}).status_code, 401)
        from accounts.tests.helpers import make_professional
        self.client.force_login(make_professional('labpro')[0])
        names = [r['name'] for r in self.client.get(url, {'q': 'dia'}).json()['results']]
        self.assertEqual(names, ['Diabetes Panel'])
        self.assertEqual(self.client.get(url, {'q': 'c'}).json()['results'], [])
