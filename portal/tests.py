import datetime

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account, Appointment, PlanGoal, PlanItem, PlanMeasure, PlanPhase, TreatmentPlan
from accounts.tests.helpers import PASSWORD, make_patient, make_professional
from exercises.models import ExerciseFeedback, Prescription, PrescriptionExercise
from soapnotes.models import SoapNote

from .models import MAX_ATTEMPTS_PER_INVITE, PatientLink, PortalInvite

DOB = datetime.date(1990, 1, 2)


def make_client(username='patient1'):
    user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
    Account.objects.create(user=user, account_type=Account.CLIENT)
    return user


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user, self.profile = make_professional('physio')
        self.patient = make_patient(self.profile, 'Sita Gurung', date_of_birth=DOB, phone='9841999999')
        self.client.login(username='physio', password=PASSWORD)

    def code(self, patient=None):
        patient = patient or self.patient
        response = self.client.post(reverse('portal:invite', args=[patient.pk]))
        self.assertEqual(response.status_code, 200, response.content[:200])
        return response.context['code']

    def as_user(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)

    def link(self, code, dob='1990-01-02'):
        return self.client.post(reverse('portal:link'), {'code': code, 'dob': dob}, follow=True)

    def linked_patient_user(self):
        code = self.code()
        make_client()
        self.as_user('patient1')
        self.link(code)
        return PatientLink.objects.get()

    def publish(self):
        plan = TreatmentPlan.objects.create(patient=self.patient, professional=self.profile, title='Knee rehab', diagnosis='ACL repair', status='active',
                                            precautions='No running or twisting for 6 weeks', education='Ice 15 minutes after exercise')
        phase = PlanPhase.objects.create(plan=plan, name='Phase 1', week_start=1, week_end=4, frequency_per_week=3, status='current')
        PlanItem.objects.create(phase=phase, kind='clinic', text='Joint mobilisation')
        PlanItem.objects.create(phase=phase, kind='hep', text='Quad sets', dosage='3 x 10')
        PlanGoal.objects.create(plan=plan, text='Walk 1 km pain free', term='short')
        PlanMeasure.objects.create(plan=plan, name='Knee flexion', unit='°', baseline=60, target=120)
        rx = Prescription.objects.create(patient=self.patient, professional=self.profile, condition_label='Post-op knee')
        item = PrescriptionExercise.objects.create(prescription=rx, exercise_name='Heel Slides', sets=3, reps=10)
        return plan, rx, item


class InviteTests(Base):
    def test_code_is_shown_once_and_stored_hashed(self):
        response = self.client.post(reverse('portal:invite', args=[self.patient.pk]))
        code = response.context['code']
        self.assertContains(response, code)
        self.assertIn('no-store', response['Cache-Control'])
        invite = PortalInvite.objects.get()
        self.assertNotIn(code.replace('-', ''), invite.code_hash)
        self.assertEqual(len(code), 9)
        self.assertEqual(self.client.get(reverse('portal:invite', args=[self.patient.pk])).status_code, 405)  # cannot be fetched again
        second = self.code()
        self.assertNotEqual(code, second)
        self.assertEqual(PortalInvite.objects.count(), 1)  # a new code replaces the old one

    def test_needs_a_birth_date_and_is_for_my_patients_only(self):
        undated = make_patient(self.profile, 'No Birth Date')
        undated.date_of_birth = None
        undated.save()
        r = self.client.post(reverse('portal:invite', args=[undated.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PortalInvite.objects.exists())
        make_professional('stranger')
        self.as_user('stranger')
        self.assertEqual(self.client.post(reverse('portal:invite', args=[self.patient.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('portal:revoke', args=[self.patient.pk])).status_code, 404)

    def test_unapproved_professional_cannot_create_codes(self):
        make_professional('waiting', status='submitted')
        self.as_user('waiting')
        self.assertEqual(self.client.post(reverse('portal:invite', args=[self.patient.pk])).status_code, 403)

    def test_patient_page_shows_the_portal_card(self):
        page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]))
        self.assertContains(page, 'Create patient portal code')
        self.code()
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk])), 'A code is open until')


class LinkTests(Base):
    def test_a_client_links_with_code_and_birth_date(self):
        code = self.code()
        make_client()
        self.as_user('patient1')
        self.assertRedirects(self.client.get(reverse('portal:link')), reverse('portal:settings'), fetch_redirect_response=False)
        page = self.client.get(reverse('portal:settings'))
        self.assertContains(page, 'Link a treatment record')
        result = self.link(code.lower().replace('-', ' '))  # forgiving about case, hyphen and spaces
        self.assertEqual(result.redirect_chain[-1][0].split('?')[0], reverse('portal:home'))
        self.assertContains(result, 'Hello, Sita Gurung')
        self.assertEqual(PatientLink.objects.get().patient, self.patient)
        self.assertIsNotNone(PortalInvite.objects.get().used_at)
        self.assertNotContains(result, '9841999999')  # no contact details on the portal

    def test_wrong_birth_date_or_code_gets_the_same_vague_answer(self):
        code = self.code()
        make_client()
        self.as_user('patient1')
        for body in ({'code': code, 'dob': '1991-01-02'}, {'code': 'ZZZZ-ZZZZ', 'dob': '1990-01-02'}, {'code': code, 'dob': ''}):
            r = self.client.post(reverse('portal:link'), body, follow=True)
            self.assertContains(r, 'do not match, or the code has expired')
        self.assertFalse(PatientLink.objects.exists())

    def test_code_dies_after_too_many_wrong_birth_dates(self):
        code = self.code()
        make_client()
        self.as_user('patient1')
        for _ in range(MAX_ATTEMPTS_PER_INVITE):
            self.link(code, dob='1980-05-05')
        self.link(code)  # even the right answer now fails
        self.assertFalse(PatientLink.objects.exists())

    def test_account_is_paused_after_repeated_failures(self):
        make_client()
        self.as_user('patient1')
        for _ in range(6):
            self.link('AAAA-BBBB')
        code = None
        self.as_user('physio')
        code = self.code()
        self.as_user('patient1')
        r = self.link(code)
        self.assertContains(r, 'Too many wrong attempts')
        self.assertFalse(PatientLink.objects.exists())
        cache.clear()
        self.link(code)
        self.assertTrue(PatientLink.objects.exists())

    def test_expired_and_used_codes_do_not_work_and_a_patient_has_one_account(self):
        code = self.code()
        PortalInvite.objects.update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
        make_client('late')
        self.as_user('late')
        self.assertContains(self.link(code), 'do not match, or the code has expired')
        self.as_user('physio')
        fresh = self.code()
        make_client('first')
        make_client('second')
        self.as_user('first')
        self.link(fresh)
        self.assertEqual(PatientLink.objects.get().user.username, 'first')
        self.as_user('second')
        self.assertContains(self.link(fresh), 'do not match')  # a used code cannot be reused
        self.as_user('physio')
        self.client.post(reverse('portal:invite', args=[self.patient.pk]))  # already linked: no new code
        self.assertFalse(PortalInvite.objects.filter(used_at__isnull=True).exists())

    def test_login_is_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('portal:home')).status_code, 302)
        self.assertEqual(self.client.get(reverse('portal:settings')).status_code, 302)
        self.assertEqual(self.client.get(reverse('portal:services')).status_code, 302)

    def test_a_linked_client_lands_in_the_portal_after_sign_in(self):
        self.linked_patient_user()
        r = self.client.get(reverse('accounts:welcome'))
        self.assertRedirects(r, reverse('portal:home'), fetch_redirect_response=False)
        make_client('fresh')
        self.as_user('fresh')
        self.assertRedirects(self.client.get(reverse('accounts:welcome')), reverse('portal:home'), fetch_redirect_response=False)  # every client has a dashboard


class PortalContentTests(Base):
    def test_empty_portal_is_friendly(self):
        self.linked_patient_user()
        for name in ('home', 'plan', 'exercises', 'advice', 'services', 'settings'):
            self.assertEqual(self.client.get(reverse('portal:' + name)).status_code, 200, name)
        self.assertContains(self.client.get(reverse('portal:plan')), 'has not shared a treatment plan')

    def test_patient_sees_the_published_plan_exercises_and_advice(self):
        plan, rx, item = self.publish()
        Appointment.objects.create(professional=self.profile, patient=self.patient, start=timezone.now() + datetime.timedelta(days=2), end=timezone.now() + datetime.timedelta(days=2, hours=1))
        self.linked_patient_user()
        self.assertContains(self.client.get(reverse('portal:home')), 'Next appointment')
        plan_page = self.client.get(reverse('portal:plan'))
        for text in ('Knee rehab', 'Walk 1 km pain free', 'Knee flexion', 'Joint mobilisation', 'Quad sets', '3 x 10'):
            self.assertContains(plan_page, text)
        ex_page = self.client.get(reverse('portal:exercises'))
        self.assertContains(ex_page, 'Heel Slides')
        self.assertContains(ex_page, 'Mark as done')
        advice = self.client.get(reverse('portal:advice'))
        self.assertContains(advice, 'Ice 15 minutes after exercise')
        self.assertContains(advice, 'No running or twisting for 6 weeks')

    def test_drafts_and_old_prescriptions_are_not_shown(self):
        plan, rx, item = self.publish()
        plan.status = 'draft'
        plan.save()
        rx.status = 'cancelled'
        rx.save()
        self.linked_patient_user()
        self.assertNotContains(self.client.get(reverse('portal:plan')), 'Knee rehab')
        self.assertNotContains(self.client.get(reverse('portal:exercises')), 'Heel Slides')
        self.assertNotContains(self.client.get(reverse('portal:advice')), 'Ice 15 minutes')

    def test_clinical_notes_and_billing_never_reach_the_patient(self):
        self.publish()
        SoapNote.objects.create(patient=self.patient, author=self.profile, author_name='x', chief_complaint='CONFIDENTIAL COMPLAINT', impression='SECRET IMPRESSION', status='final')
        self.patient.notes = 'PRIVATE CLINICIAN NOTE'
        self.patient.save()
        self.linked_patient_user()
        for name in ('home', 'plan', 'exercises', 'advice', 'settings'):
            body = self.client.get(reverse('portal:' + name)).content.decode()
            for secret in ('CONFIDENTIAL COMPLAINT', 'SECRET IMPRESSION', 'PRIVATE CLINICIAN NOTE', '9841999999'):
                self.assertNotIn(secret, body)

    def test_ticking_an_exercise_and_sending_feedback(self):
        plan, rx, item = self.publish()
        self.linked_patient_user()
        self.client.post(reverse('portal:exercise-done', args=[self.patient.pk, item.pk]))
        item.refresh_from_db()
        self.assertTrue(item.is_completed)
        self.client.post(reverse('portal:exercise-done', args=[self.patient.pk, item.pk]))
        item.refresh_from_db()
        self.assertFalse(item.is_completed)
        self.client.post(reverse('portal:exercise-feedback', args=[self.patient.pk, item.pk]), {'feedback_type': 'painful', 'note': 'knee clicks'})
        self.assertEqual(ExerciseFeedback.objects.get().feedback_type, 'painful')
        self.client.post(reverse('portal:exercise-feedback', args=[self.patient.pk, item.pk]), {'feedback_type': 'nonsense'})
        self.assertEqual(ExerciseFeedback.objects.count(), 1)
        # the physio sees it on the patient's exercises tab
        self.as_user('physio')
        page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'exercises'})
        self.assertContains(page, 'Patient: Painful')
        self.assertContains(page, 'knee clicks')

    def test_one_patient_cannot_reach_another_patients_data(self):
        plan, rx, item = self.publish()
        other = make_patient(self.profile, 'Other Person', date_of_birth=DOB)
        self.linked_patient_user()
        self.assertEqual(self.client.get(reverse('portal:home'), {'p': other.pk}).context['patient'], self.patient)  # falls back to their own record
        make_client('intruder')
        self.as_user('intruder')
        self.assertEqual(self.client.get(reverse('portal:home')).context['patient'], None)
        for url in (reverse('portal:exercise-done', args=[self.patient.pk, item.pk]), reverse('portal:exercise-feedback', args=[self.patient.pk, item.pk]), reverse('portal:unlink', args=[self.patient.pk])):
            self.assertEqual(self.client.post(url, {'feedback_type': 'normal'}).status_code, 404, url)
        item.refresh_from_db()
        self.assertFalse(item.is_completed)

    def test_unlinking_and_revoking(self):
        self.linked_patient_user()
        self.client.post(reverse('portal:unlink', args=[self.patient.pk]))
        self.assertFalse(PatientLink.objects.exists())
        self.as_user('physio')
        code = self.code()
        self.as_user('patient1')
        self.link(code)
        self.assertTrue(PatientLink.objects.exists())
        self.as_user('physio')
        self.client.post(reverse('portal:revoke', args=[self.patient.pk]))
        self.assertFalse(PatientLink.objects.exists())
        self.as_user('patient1')
        self.assertEqual(self.client.get(reverse('portal:home')).context['patient'], None)

    def test_a_parent_can_link_two_children(self):
        child = make_patient(self.profile, 'Child Gurung', date_of_birth=datetime.date(2015, 5, 5))
        code_one = self.code()
        code_two = self.code(child)
        make_client('parent')
        self.as_user('parent')
        self.link(code_one)
        self.link(code_two, dob='2015-05-05')
        self.assertEqual(PatientLink.objects.filter(user__username='parent').count(), 2)
        page = self.client.get(reverse('portal:home'), {'p': child.pk})
        self.assertContains(page, 'Hello, Child Gurung')
        self.assertContains(page, 'Sita Gurung')  # the switcher


class DashboardTests(Base):
    """The patient dashboard for any Client account: services first, treatment once a record is linked."""

    def test_an_unlinked_client_gets_a_dashboard_with_services_and_a_pointer_to_settings(self):
        make_client('browser')
        self.as_user('browser')
        page = self.client.get(reverse('portal:home'))
        self.assertContains(page, 'Hello, browser')
        for url in (reverse('marketplace:pharmacy'), reverse('marketplace:marketplace'), reverse('lab:tests')):
            self.assertContains(page, f'href="{url}"')
        self.assertContains(page, 'Have a treatment record')
        self.assertContains(page, reverse('portal:settings'))
        for name in ('plan', 'exercises', 'advice'):  # treatment pages explain how to link instead of failing
            self.assertContains(self.client.get(reverse('portal:' + name)), 'No treatment record linked yet')

    def test_vertical_navigation_is_on_every_page(self):
        make_client('nav')
        self.as_user('nav')
        for name in ('home', 'services', 'settings'):
            page = self.client.get(reverse('portal:' + name))
            for label in ('Home', 'Treatment plan', 'My exercises', "Do's &amp; don't", 'Pharmacy', 'Marketplace', 'Lab investigations', 'Settings'):
                self.assertContains(page, label, msg_prefix=f'{name}: ')
            self.assertContains(page, 'class="side"')

    def test_services_page_lists_all_three(self):
        make_client('shopper')
        self.as_user('shopper')
        page = self.client.get(reverse('portal:services'))
        for title in ('Pharmacy', 'Marketplace', 'Lab investigations'):
            self.assertContains(page, title)

    def test_linking_happens_in_settings_and_lands_on_the_treatment_dashboard(self):
        code = self.code()
        make_client('patient2')
        self.as_user('patient2')
        settings_page = self.client.get(reverse('portal:settings'))
        self.assertContains(settings_page, f'action="{reverse("portal:link")}"')
        result = self.link(code)
        self.assertEqual(result.redirect_chain[-1][0], f"{reverse('portal:home')}?p={self.patient.pk}")
        self.assertContains(result, 'Next appointment')
        self.assertContains(result, 'Viewing')
        self.assertNotContains(result, 'Have a treatment record')

    def test_settings_changes_email_and_rejects_a_taken_one(self):
        User.objects.create_user('taken', 'taken@example.com', 'x')
        user = make_client('mailer')
        self.as_user('mailer')
        self.client.post(reverse('portal:settings'), {'form': 'email', 'email': 'TAKEN@example.com'})
        user.refresh_from_db()
        self.assertEqual(user.email, 'mailer@example.com')
        self.client.post(reverse('portal:settings'), {'form': 'email', 'email': 'new@example.com'})
        user.refresh_from_db()
        self.assertEqual(user.email, 'new@example.com')

    def test_storefront_pages_offer_a_way_back_for_clients_only(self):
        make_client('shopper2')
        self.as_user('shopper2')
        self.assertContains(self.client.get(reverse('marketplace:pharmacy')), 'My dashboard')
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('marketplace:pharmacy')), 'My dashboard')

    def test_old_tab_links_still_work(self):
        self.linked_patient_user()
        self.assertRedirects(self.client.get(reverse('portal:home'), {'tab': 'exercises'}), reverse('portal:exercises'), fetch_redirect_response=False)


class OrdersLinkedToAccountTests(TestCase):
    """Orders and lab bookings belong to the signed-in account, so they follow the patient across devices."""

    def setUp(self):
        cache.clear()
        from lab.models import LabTest
        from marketplace.models import PharmacyProduct
        self.test = LabTest.objects.create(name='CBC', price=400, category='blood')
        self.medicine = PharmacyProduct.objects.create(name='Paracetamol 500', price=30)
        self.user = make_client('buyer')

    def book_lab(self, client):
        return client.post(reverse('lab:tests'), {'items': [f'test-{self.test.pk}'], 'customer_name': 'Ram Shah', 'customer_email': 'ram@example.com',
                                                  'customer_phone': '9800000000', 'delivery_address': 'Lalitpur'})

    def place_order(self, client):
        client.post(reverse('marketplace:pharmacy-add-to-cart', args=[self.medicine.pk]), {'quantity': 2})
        return client.post(reverse('marketplace:pharmacy-checkout'), {'customer_name': 'Ram Shah', 'customer_email': 'ram@example.com',
                                                                      'customer_phone': '9800000000', 'delivery_address': 'Lalitpur'})

    def test_bookings_and_orders_placed_signed_in_belong_to_the_account(self):
        from lab.models import LabTestRequest
        from marketplace.models import Order
        self.client.login(username='buyer', password=PASSWORD)
        self.book_lab(self.client)
        self.place_order(self.client)
        self.assertEqual(LabTestRequest.objects.get().user, self.user)
        self.assertEqual(Order.objects.get().user, self.user)
        lab_page = self.client.get(reverse('portal:lab'))
        self.assertContains(lab_page, 'CBC')
        self.assertContains(lab_page, 'Pending')
        orders_page = self.client.get(reverse('portal:orders'))
        self.assertContains(orders_page, 'Paracetamol 500')
        self.assertContains(orders_page, 'Pharmacy')
        home = self.client.get(reverse('portal:home'))
        self.assertContains(home, 'Latest order')
        self.assertContains(home, 'Latest lab booking')

    def test_it_follows_the_account_to_another_device(self):
        from lab.models import LabTestRequest
        self.client.login(username='buyer', password=PASSWORD)
        self.book_lab(self.client)
        booking_url = reverse('lab:order-success', args=[LabTestRequest.objects.get().request_number])
        phone = self.client_class()
        phone.login(username='buyer', password=PASSWORD)  # a fresh session: no browser list of numbers
        self.assertContains(phone.get(reverse('portal:lab')), 'CBC')
        self.assertEqual(phone.get(booking_url).status_code, 200)  # the owner may open the confirmation anywhere
        make_client('other')
        stranger = self.client_class()
        stranger.login(username='other', password=PASSWORD)
        self.assertEqual(stranger.get(booking_url).status_code, 404)
        self.assertNotContains(stranger.get(reverse('portal:lab')), 'CBC')

    def test_accounts_only_ever_see_their_own_orders(self):
        from marketplace.models import Order
        other = make_client('someone')
        Order.objects.create(order_type='pharmacy', user=other, customer_name='Else', customer_email='e@example.com', customer_phone='1', delivery_address='x', total_amount=10)
        self.client.login(username='buyer', password=PASSWORD)
        self.assertContains(self.client.get(reverse('portal:orders')), 'No orders yet')

    def test_guest_orders_in_this_browser_attach_when_the_guest_signs_in_or_up(self):
        from lab.models import LabTestRequest
        from marketplace.models import Order
        guest = self.client_class()
        self.book_lab(guest)
        self.place_order(guest)
        self.assertEqual((LabTestRequest.objects.get().user, Order.objects.get().user), (None, None))
        self.assertContains(guest.get(reverse('lab:order-success', args=[LabTestRequest.objects.get().request_number])), 'Want to track this booking')
        guest.post(reverse('accounts:login'), {'username': 'buyer', 'password': PASSWORD})
        self.assertEqual((LabTestRequest.objects.get().user, Order.objects.get().user), (self.user, self.user))
        # signing UP in the same browser works the same way
        fresh = self.client_class()
        self.book_lab(fresh)
        fresh.post(reverse('accounts:signup-client'), {'username': 'newbie', 'email': 'newbie@example.com', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertEqual(LabTestRequest.objects.filter(user__username='newbie').count(), 1)

    def test_a_different_browser_cannot_claim_other_peoples_guest_orders_by_signing_in(self):
        from marketplace.models import Order
        guest = self.client_class()
        self.place_order(guest)
        other = self.client_class()
        other.post(reverse('accounts:login'), {'username': 'buyer', 'password': PASSWORD})
        self.assertIsNone(Order.objects.get().user)

    def test_claiming_an_earlier_order_needs_the_number_and_the_email(self):
        from lab.models import LabTestRequest
        from marketplace.models import Order
        guest = self.client_class()
        self.place_order(guest)
        self.book_lab(guest)
        order, booking = Order.objects.get(), LabTestRequest.objects.get()
        self.client.login(username='buyer', password=PASSWORD)
        for body in ({'kind': 'order', 'number': order.order_number, 'email': 'wrong@example.com'}, {'kind': 'order', 'number': 'NOPE', 'email': 'ram@example.com'}):
            self.client.post(reverse('portal:claim'), body)
        self.assertIsNone(Order.objects.get().user)
        self.client.post(reverse('portal:claim'), {'kind': 'order', 'number': '#' + order.order_number, 'email': 'RAM@example.com'})
        self.client.post(reverse('portal:claim'), {'kind': 'lab', 'number': booking.request_number, 'email': 'ram@example.com'})
        self.assertEqual((Order.objects.get().user, LabTestRequest.objects.get().user), (self.user, self.user))
        # an already-owned order cannot be taken over by someone else
        make_client('thief')
        thief = self.client_class()
        thief.login(username='thief', password=PASSWORD)
        thief.post(reverse('portal:claim'), {'kind': 'order', 'number': order.order_number, 'email': 'ram@example.com'})
        self.assertEqual(Order.objects.get().user, self.user)

    def test_claim_attempts_are_throttled(self):
        from marketplace.models import Order
        guest = self.client_class()
        self.place_order(guest)
        order = Order.objects.get()
        self.client.login(username='buyer', password=PASSWORD)
        for _ in range(6):
            self.client.post(reverse('portal:claim'), {'kind': 'order', 'number': order.order_number, 'email': 'guess@example.com'})
        self.client.post(reverse('portal:claim'), {'kind': 'order', 'number': order.order_number, 'email': 'ram@example.com'})
        self.assertIsNone(Order.objects.get().user)  # paused

    def test_checkout_forms_are_prefilled_from_the_account(self):
        self.client.login(username='buyer', password=PASSWORD)
        self.book_lab(self.client)
        page = self.client.get(reverse('lab:tests'))
        self.assertContains(page, 'value="Ram Shah"')
        self.assertContains(page, 'value="9800000000"')
        self.assertContains(page, 'value="buyer@example.com"')
        self.assertContains(page, 'Lalitpur')
        self.client.post(reverse('marketplace:pharmacy-add-to-cart', args=[self.medicine.pk]), {'quantity': 1})
        self.assertContains(self.client.get(reverse('marketplace:pharmacy-checkout')), 'value="Ram Shah"')

    def test_menu_has_orders_and_lab_bookings_and_login_is_required(self):
        self.client.login(username='buyer', password=PASSWORD)
        self.assertContains(self.client.get(reverse('portal:home')), 'My lab bookings')
        self.client.logout()
        for name in ('orders', 'lab'):
            self.assertEqual(self.client.get(reverse('portal:' + name)).status_code, 302)
