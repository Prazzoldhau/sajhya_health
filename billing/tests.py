import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Appointment, Visit
from accounts.tests.helpers import make_patient, make_professional

from .models import PatientAllowance, SlotOrder, BillingEntry, PackagePayment, PatientPackage, Plan, use_package_session
from .views import revenue_for


class BillingBase(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.today = timezone.localdate()

    def entry(self, **extra):
        data = {'entry_date': self.today.isoformat(), 'patient_name': 'Walk In', 'service': 'Consult', 'rate': '500', 'payment_mode': 'cash', **extra}
        return self.client.post(reverse('billing:entry-create'), data)

    def package(self, **extra):
        data = {'patient': self.patient.pk, 'duration': '2_week', 'total_sessions': 3, 'total_amount': '3000', 'amount_paid_now': '1000', 'start_date': self.today.isoformat(), **extra}
        return self.client.post(reverse('billing:package-create'), data)


class BillingEntryTests(BillingBase):
    def test_pages_render(self):
        for params in ({}, {'date': '2026-01-01'}, {'date': 'junk'}, {'new': 1}):
            self.assertEqual(self.client.get(reverse('billing:billing'), params).status_code, 200)

    def test_create_edit_delete_and_totals(self):
        self.entry()
        self.entry(patient_name='Second', rate='1500.50', payment_mode='online')
        page = self.client.get(reverse('billing:billing'))
        self.assertEqual(page.context['total'], Decimal('2000.50'))
        self.assertEqual(dict(page.context['by_mode'])['Online'], Decimal('1500.50'))
        first = BillingEntry.objects.get(patient_name='Walk In')
        self.assertTrue(first.invoice_number.startswith('BILL-'))
        self.client.post(reverse('billing:entry-edit', args=[first.pk]), {'entry_date': self.today.isoformat(), 'patient_name': 'Walk In', 'service': 'Consult', 'rate': '700', 'payment_mode': 'card'})
        first.refresh_from_db()
        self.assertEqual((first.rate, first.payment_mode), (700, 'card'))
        self.client.post(reverse('billing:entry-delete', args=[first.pk]))
        self.assertEqual(BillingEntry.objects.count(), 1)

    def test_validation(self):
        self.entry(rate='-5')
        self.entry(patient_name='X')
        self.entry(rate='')
        self.assertEqual(BillingEntry.objects.count(), 0)

    def test_linked_patient_fills_in_blank_details(self):
        self.entry(patient=self.patient.pk, patient_name=self.patient.name)
        e = BillingEntry.objects.get()
        self.assertEqual((e.patient, e.sex, e.contact_number, e.age), (self.patient, 'F', '9841000000', self.patient.age))
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'billing'}), e.invoice_number)

    def test_cannot_link_another_professionals_patient(self):
        _, other_profile = make_professional('other')
        theirs = make_patient(other_profile, 'Theirs')
        self.entry(patient=theirs.pk, patient_name='Theirs')
        self.assertEqual(BillingEntry.objects.count(), 0)

    def test_entries_are_private_and_need_login(self):
        self.entry()
        entry = BillingEntry.objects.get()
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertNotContains(other.get(reverse('billing:billing')), 'Walk In')
        self.assertEqual(other.post(reverse('billing:entry-delete', args=[entry.pk])).status_code, 404)
        self.assertEqual(other.post(reverse('billing:entry-edit', args=[entry.pk]), {}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('billing:billing')).status_code, 302)


class PlanContentTests(TestCase):
    def test_four_plans_are_seeded_with_the_published_content(self):
        plans = {p.code: p for p in Plan.objects.all()}
        self.assertEqual(set(plans), {'client', 'professional', 'clinic', 'enterprise'})
        self.assertTrue(plans['client'].is_free)
        self.assertEqual((plans['professional'].price_monthly, plans['professional'].patient_limit), (0, None))  # free for the first 10 patients
        self.assertIn('200', plans['professional'].price_note)
        self.assertTrue(plans['clinic'].is_custom and plans['enterprise'].is_custom)

    def test_package_page_and_landing_show_the_database_plans(self):
        self.assertContains(self.client.get(reverse('accounts:package')), 'First 10 patients free')
        Plan.objects.filter(code='professional').update(price_monthly=Decimal('1500'))
        self.assertContains(self.client.get(reverse('accounts:package')), '<span class="amount">1,500</span>')
        self.assertContains(self.client.get('/'), '1500')


class PatientAllowanceTests(TestCase):
    """Professional pricing: 10 patients free, then NPR 200 per extra patient, bought as slots."""

    def setUp(self):
        self.user, self.profile = make_professional('allowed')
        self.client.force_login(self.user)
        self.new = lambda name='Extra': {'name': name, 'date_of_birth': '1980-05-05', 'gender': 'M', 'phone': '9841234567'}

    def fill(self, count):
        for i in range(count):
            make_patient(self.profile, f'Patient {i}')

    def test_defaults_are_ten_free_at_two_hundred(self):
        allowance = PatientAllowance.for_profile(self.profile)
        self.assertEqual((allowance.free_limit, allowance.paid_slots, allowance.rate, allowance.allowed, allowance.remaining), (10, 0, 200, 10, 10))

    def test_the_eleventh_patient_needs_a_slot(self):
        self.fill(9)
        self.assertEqual(self.client.post(reverse('accounts:patient-add'), self.new('Tenth')).status_code, 302)
        self.assertEqual(self.profile.patients.count(), 10)  # the 10th is still free
        r = self.client.post(reverse('accounts:patient-add'), self.new('Eleventh'))
        self.assertRedirects(r, reverse('accounts:settings') + '?tab=plan', fetch_redirect_response=False)
        self.assertEqual(self.profile.patients.count(), 10)
        self.assertRedirects(self.client.get(reverse('accounts:patient-add')), reverse('accounts:settings') + '?tab=plan', fetch_redirect_response=False)

    def test_buying_slots_unlocks_exactly_that_many(self):
        self.fill(10)
        self.client.post(reverse('accounts:settings'), {'tab': 'plan', 'quantity': '2'})
        order = SlotOrder.objects.get()
        self.assertEqual((order.quantity, order.amount, order.status), (2, 400, 'requested'))
        self.client.post(reverse('accounts:patient-add'), self.new('Waiting'))
        self.assertEqual(self.profile.patients.count(), 10)  # unpaid orders do not unlock anything
        self.assertTrue(order.mark_paid(self.user))
        self.assertFalse(order.mark_paid(self.user))  # cannot add the slots twice
        allowance = PatientAllowance.for_profile(self.profile)
        self.assertEqual((allowance.paid_slots, allowance.allowed), (2, 12))
        for name in ('Eleven', 'Twelve', 'Thirteen'):
            self.client.post(reverse('accounts:patient-add'), self.new(name))
        self.assertEqual(self.profile.patients.count(), 12)

    def test_bad_quantities_are_rejected(self):
        for bad in ('0', '-3', 'abc', '501', ''):
            self.client.post(reverse('accounts:settings'), {'tab': 'plan', 'quantity': bad})
        self.assertFalse(SlotOrder.objects.exists())

    def test_clinic_patients_are_not_counted_here(self):
        from clinics.models import Clinic, ClinicSubscription
        clinic = Clinic.objects.create(owner=self.profile, name='C', phone='015550001')
        ClinicSubscription.objects.create(professional=self.profile, status='active')
        self.fill(10)
        for i in range(3):
            make_patient(self.profile, f'Clinic {i}', clinic=clinic)
        self.assertEqual(PatientAllowance.for_profile(self.profile).used, 10)
        self.client.post(reverse('accounts:patient-add') + f'?clinic={clinic.pk}', {**self.new('At Clinic'), 'clinic': clinic.pk})
        self.assertEqual(self.profile.patients.filter(clinic=clinic).count(), 4)  # the clinic plan covers it

    def test_plan_tab_and_patient_page_show_usage(self):
        self.fill(8)
        page = self.client.get(reverse('accounts:settings'), {'tab': 'plan'})
        self.assertContains(page, '8</span> of 10 slots used')
        self.assertContains(page, 'NPR 200')
        self.assertContains(self.client.get(reverse('accounts:patients')), '8 of 10')  # near the limit: a heads-up on the list

    def test_legacy_professionals_with_many_patients_keep_working(self):
        self.fill(15)
        allowance = PatientAllowance.objects.create(professional=self.profile, paid_slots=5)  # what the migration records for them
        self.assertTrue(allowance.allowed == 15 and not allowance.can_add)

    def test_slot_orders_are_private_and_staff_mark_them_paid_in_the_admin(self):
        self.fill(1)
        other_user, other = make_professional('rival')
        order = SlotOrder.objects.create(professional=other, quantity=5, rate=200, amount=1000)
        self.assertNotContains(self.client.get(reverse('accounts:settings'), {'tab': 'plan'}), 'NPR 1000')
        staff = make_professional('staffer', staff=True)[0]
        staff.is_superuser = True
        staff.save()
        self.client.force_login(staff)
        r = self.client.post(reverse('admin:billing_slotorder_changelist'), {'action': 'mark_paid', '_selected_action': [order.pk]})
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')
        self.assertEqual(PatientAllowance.for_profile(other).paid_slots, 5)

    def test_the_numbers_come_from_settings(self):
        from django.test import override_settings
        with override_settings(FREE_PATIENT_LIMIT=3, PATIENT_SLOT_RATE=250):
            fresh_user, fresh = make_professional('fresh')
            allowance = PatientAllowance.for_profile(fresh)
            self.assertEqual((allowance.free_limit, allowance.rate), (3, 250))


class PackageTests(BillingBase):
    def test_all_four_durations_exist_with_the_right_length(self):
        self.assertEqual([label for _, label in PatientPackage.DURATION_CHOICES], ['1 Week', '2 Weeks', '3 Weeks', '4 Weeks'])
        for key, days in (('1_week', 7), ('2_week', 14), ('3_week', 21), ('4_week', 28)):
            self.package(duration=key)
            pkg = PatientPackage.objects.latest('id')
            self.assertEqual(pkg.end_date - pkg.start_date, datetime.timedelta(days=days), key)

    def test_packages_page_renders_and_filters(self):
        self.package()
        for params in ({}, {'show': 'active'}, {'show': 'due'}, {'show': 'completed'}, {'show': 'bogus'}, {'new': 1}, {'patient': self.patient.pk}):
            self.assertEqual(self.client.get(reverse('billing:packages'), params).status_code, 200, params)
        page = self.client.get(reverse('billing:packages'))
        self.assertEqual((page.context['active_count'], page.context['sessions_left'], page.context['total_due'], page.context['collected']), (1, 3, 2000, 1000))
        self.assertEqual(len(self.client.get(reverse('billing:packages'), {'show': 'completed'}).context['packages']), 0)
        self.assertEqual(len(self.client.get(reverse('billing:packages'), {'show': 'due'}).context['packages']), 1)

    def test_start_package_with_partial_payment(self):
        self.package()
        pkg = PatientPackage.objects.get()
        self.assertEqual((pkg.amount_paid, pkg.amount_due, pkg.sessions_used, pkg.effective_status), (1000, 2000, 0, 'active'))
        self.assertEqual((pkg.payments.count(), pkg.professional), (1, self.profile))
        self.assertEqual(pkg.per_session, Decimal('1000'))

    def test_package_validation(self):
        self.package(amount_paid_now='5000')  # more than the price
        self.package(total_sessions=0)
        self.package(total_amount='-1')
        self.package(duration='5_week')
        self.package(patient='')
        self.assertEqual(PatientPackage.objects.count(), 0)

    def test_cannot_sell_a_package_to_someone_elses_patient(self):
        _, other_profile = make_professional('other')
        theirs = make_patient(other_profile, 'Theirs')
        self.package(patient=theirs.pk)
        self.assertEqual(PatientPackage.objects.count(), 0)

    def test_payments_are_capped_at_the_balance_and_stop_when_paid(self):
        self.package()
        pkg = PatientPackage.objects.get()
        url = reverse('billing:package-payment', args=[pkg.pk])
        self.client.post(url, {'amount': '99999', 'payment_mode': 'cash'})
        pkg.refresh_from_db()
        self.assertEqual((pkg.amount_paid, pkg.is_fully_paid), (3000, True))
        self.assertEqual(PackagePayment.objects.get(amount=2000).amount, 2000)  # capped, not 99,999
        self.client.post(url, {'amount': '10', 'payment_mode': 'cash'})
        self.assertEqual(pkg.payments.count(), 2)
        self.assertIsNone(pkg.record_payment(Decimal('-5')))

    def test_visits_use_sessions_until_the_package_completes(self):
        self.package()
        visit_url = reverse('accounts:patient-visit-add', args=[self.patient.pk])
        for _ in range(3):
            self.client.post(visit_url, {'date': self.today.isoformat(), 'session_type': 'treatment'})
        pkg = PatientPackage.objects.get()
        self.assertEqual((pkg.sessions_used, pkg.status, pkg.effective_status), (3, 'completed', 'completed'))
        self.client.post(visit_url, {'date': self.today.isoformat(), 'session_type': 'treatment'})
        pkg.refresh_from_db()
        self.assertEqual(pkg.sessions_used, 3)  # a completed package is not charged again
        self.assertEqual(Visit.objects.count(), 4)

    def test_attending_an_appointment_uses_a_session(self):
        self.package()
        appt = Appointment.objects.create(professional=self.profile, patient=self.patient, start=timezone.now(), end=timezone.now() + datetime.timedelta(minutes=30))
        self.client.post(reverse('accounts:appointment-action', args=[appt.pk]), {'action': 'attend'})
        self.assertEqual(PatientPackage.objects.get().sessions_used, 1)

    def test_cancelled_or_expired_packages_do_not_use_sessions(self):
        self.package()
        pkg = PatientPackage.objects.get()
        self.client.post(reverse('billing:package-cancel', args=[pkg.pk]))
        self.assertFalse(use_package_session(self.patient))
        pkg.status, pkg.start_date = 'active', self.today - datetime.timedelta(days=60)
        pkg.save()
        self.assertEqual(PatientPackage.objects.get().effective_status, 'expired')
        self.assertFalse(use_package_session(self.patient))

    def test_patient_billing_tab_shows_packages_and_takes_payments(self):
        self.package()
        pkg = PatientPackage.objects.get()
        tab = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'billing'})
        self.assertContains(tab, '2 Weeks package')
        r = self.client.post(reverse('billing:package-payment', args=[pkg.pk]), {'amount': '500', 'payment_mode': 'online', 'next': 'patient'})
        self.assertRedirects(r, reverse('accounts:patient-detail', args=[self.patient.pk]) + '?tab=billing')
        pkg.refresh_from_db()
        self.assertEqual(pkg.amount_paid, 1500)

    def test_packages_are_private(self):
        self.package()
        pkg = PatientPackage.objects.get()
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertNotContains(other.get(reverse('billing:packages')), self.patient.name)
        self.assertEqual(other.post(reverse('billing:package-payment', args=[pkg.pk]), {'amount': '1', 'payment_mode': 'cash'}).status_code, 404)
        self.assertEqual(other.post(reverse('billing:package-cancel', args=[pkg.pk])).status_code, 404)

    def test_revenue_combines_entries_and_package_payments(self):
        self.entry(rate='500')
        self.package()  # NPR 1000 paid at booking
        self.assertEqual(revenue_for(self.profile, self.today), Decimal('1500'))
        self.assertEqual(revenue_for(self.profile, self.today - datetime.timedelta(days=1)), 0)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).context['stats']['revenue_today'], Decimal('1500'))
        self.assertEqual(self.client.get(reverse('billing:billing')).context['package_payments'], Decimal('1000'))


class PatientBillTests(BillingBase):
    def test_bill_from_the_patient_tab_is_filled_from_the_record_and_returns_to_the_tab(self):
        tab = reverse('accounts:patient-detail', args=[self.patient.pk]) + '?tab=billing'
        page = self.client.get(tab)
        self.assertContains(page, reverse('billing:patient-bill', args=[self.patient.pk]))  # the small form, not a link to the whole book
        r = self.client.post(reverse('billing:patient-bill', args=[self.patient.pk]),
                             {'entry_date': self.today.isoformat(), 'service': 'Ultrasound', 'rate': '700', 'payment_mode': 'online'})
        self.assertRedirects(r, tab, fetch_redirect_response=False)
        entry = BillingEntry.objects.get()
        self.assertEqual((entry.patient, entry.patient_name, entry.professional, entry.rate, entry.age), (self.patient, self.patient.name, self.profile, Decimal('700'), self.patient.age))
        self.assertContains(self.client.get(tab), 'Ultrasound')

    def test_negative_amount_is_refused_and_other_physios_patients_are_off_limits(self):
        url = reverse('billing:patient-bill', args=[self.patient.pk])
        self.client.post(url, {'entry_date': self.today.isoformat(), 'service': 'x', 'rate': '-5', 'payment_mode': 'cash'})
        self.assertEqual(BillingEntry.objects.count(), 0)
        other_user, other = make_professional('other')
        stranger = make_patient(other, name='Not Mine')
        self.assertEqual(self.client.post(reverse('billing:patient-bill', args=[stranger.pk]), {'entry_date': self.today.isoformat(), 'service': 'x', 'rate': '5', 'payment_mode': 'cash'}).status_code, 404)


class CreditBillTests(BillingBase):
    """Many patients pay at the end of the week, so a bill can be left on credit and settled later (in full or in parts)."""

    def test_a_bill_can_be_paid_in_full_part_paid_or_left_due(self):
        self.entry(patient_name='Full')
        self.entry(patient_name='Part', payment_status='partial', amount_received='200')
        self.entry(patient_name='Credit', payment_status='due', payment_mode='cash')
        full, part, due = (BillingEntry.objects.get(patient_name=n) for n in ('Full', 'Part', 'Credit'))
        self.assertEqual((full.status_key, full.amount_due), ('paid', 0))
        self.assertEqual((part.status_key, part.amount_paid, part.amount_due), ('partial', 200, 300))
        self.assertEqual((due.status_key, due.amount_paid, due.amount_due), ('due', 0, 500))
        page = self.client.get(reverse('billing:billing'))
        self.assertEqual(page.context['bills_due'], Decimal('800'))
        self.assertEqual(page.context['collected'], Decimal('700'))  # only what was received counts as money taken
        self.assertContains(page, 'Payments due')
        self.assertEqual(revenue_for(self.profile, self.today), Decimal('700'))

    def test_partial_needs_a_sensible_amount(self):
        self.entry(patient_name='Zero', payment_status='partial', amount_received='0')
        self.entry(patient_name='All', payment_status='partial', amount_received='500')
        self.assertEqual(BillingEntry.objects.count(), 0)

    def test_receiving_the_credit_later_counts_as_money_taken_on_that_day(self):
        yesterday = self.today - datetime.timedelta(days=3)
        self.entry(entry_date=yesterday.isoformat(), payment_status='due')
        entry = BillingEntry.objects.get()
        self.assertEqual(revenue_for(self.profile, yesterday), 0)
        r = self.client.post(reverse('billing:entry-payment', args=[entry.pk]), {'amount': '300', 'payment_mode': 'online', 'next': '/billing/'})
        self.assertRedirects(r, '/billing/', fetch_redirect_response=False)
        entry.refresh_from_db()
        self.assertEqual((entry.amount_paid, entry.status_key), (300, 'partial'))
        self.client.post(reverse('billing:entry-payment', args=[entry.pk]), {'amount': '900', 'payment_mode': 'cash'})  # more than owed: capped
        entry.refresh_from_db()
        self.assertEqual((entry.amount_paid, entry.status_key, entry.payments.count()), (500, 'paid', 2))
        self.assertEqual(revenue_for(self.profile, self.today), Decimal('500'))
        self.assertEqual(revenue_for(self.profile, yesterday), 0)
        self.assertEqual(self.client.post(reverse('billing:entry-payment', args=[entry.pk]), {'amount': '10', 'payment_mode': 'cash'}).status_code, 302)
        self.assertEqual(entry.payments.count(), 2)  # already paid: nothing more recorded

    def test_credit_from_the_patient_tab_and_receive_there(self):
        tab = reverse('accounts:patient-detail', args=[self.patient.pk]) + '?tab=billing'
        self.client.post(reverse('billing:patient-bill', args=[self.patient.pk]),
                         {'entry_date': self.today.isoformat(), 'service': 'Therapy', 'rate': '900', 'payment_mode': 'cash', 'payment_status': 'due'})
        entry = BillingEntry.objects.get()
        self.assertEqual(entry.amount_due, 900)
        self.assertContains(self.client.get(tab), 'NPR 900.00 due')
        self.client.post(reverse('billing:entry-payment', args=[entry.pk]), {'amount': '900', 'payment_mode': 'cash', 'next': tab})
        entry.refresh_from_db()
        self.assertEqual(entry.status_key, 'paid')

    def test_editing_cannot_drop_the_amount_below_what_was_received_and_strangers_are_refused(self):
        self.entry(payment_status='partial', amount_received='300')
        entry = BillingEntry.objects.get()
        self.client.post(reverse('billing:entry-edit', args=[entry.pk]), {'entry_date': self.today.isoformat(), 'patient_name': 'Walk In', 'service': 'Consult', 'rate': '100', 'payment_mode': 'cash'})
        entry.refresh_from_db()
        self.assertEqual(entry.rate, 500)
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertEqual(other.post(reverse('billing:entry-payment', args=[entry.pk]), {'amount': '10', 'payment_mode': 'cash'}).status_code, 404)

    def test_existing_bills_were_all_paid(self):
        from importlib import import_module
        from django.apps import apps
        legacy = BillingEntry.objects.create(professional=self.profile, patient_name='Old', rate=400, payment_mode='card', entry_date=self.today)
        import_module('billing.migrations.0008_existing_bills_are_paid').mark_existing_paid(apps, None)
        legacy.refresh_from_db()
        self.assertEqual((legacy.amount_paid, legacy.payments.get().payment_mode), (400, 'card'))
