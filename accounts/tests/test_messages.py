import datetime
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import messaging
from accounts.appointments import aware, appointment_message
from accounts.models import Appointment, MessageTemplate

from .helpers import PASSWORD, make_patient, make_professional


class RenderTests(TestCase):
    def test_placeholders_are_filled_and_empty_lines_dropped(self):
        body = 'Hello {patient},\nContact: {contact}\nBye {unknown}'
        self.assertEqual(messaging.render(body, {'patient': 'Sita', 'contact': ''}), 'Hello Sita,\nBye {unknown}')
        self.assertEqual(messaging.render('A {x}\n\n\n\nB', {'x': '1'}), 'A 1\n\nB')
        self.assertEqual(messaging.render('{patient.__class__}', {'patient': 'x'}), '{patient.__class__}')  # no attribute access, just names

    def test_whatsapp_number_cleaning(self):
        self.assertEqual(messaging.clean_whatsapp_number(' +977 970-2235789 '), '+977 970-2235789')
        self.assertEqual(messaging.clean_whatsapp_number(''), '')
        for bad in ('abc', '12345', '+977 <script>'):
            with self.assertRaises(ValueError):
                messaging.clean_whatsapp_number(bad)


class MessagesPageTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    def book(self):
        start = aware(self.tomorrow, datetime.time(15, 0))
        return Appointment.objects.create(professional=self.profile, patient=self.patient, start=start, end=start + datetime.timedelta(minutes=30))

    def test_the_page_lists_every_message_and_the_business_number_can_be_set(self):
        page = self.client.get(reverse('accounts:messages'))
        self.assertEqual(page.status_code, 200)
        for label in ('Appointment booked (confirmation)', 'Appointment reminder', 'Appointment cancelled', 'Follow-up check-in', 'Business WhatsApp and Viber numbers'):
            self.assertContains(page, label)
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789'})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.whatsapp_number, '+977 970-2235789')
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': 'not a number'})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.whatsapp_number, '+977 970-2235789')  # a bad value is refused
        # the number is used in the appointment message and on the invoice
        appt = self.book()
        self.assertIn('WhatsApp +977 970-2235789', appointment_message(appt, 'booked'))
        self.assertContains(self.client.get(reverse('accounts:messages')), 'wa.me/9779702235789')

    def test_a_message_can_be_reworded_and_reset_and_the_new_wording_is_used(self):
        appt = self.book()
        self.client.post(reverse('accounts:message-save', args=['appointment_booked']), {'body': 'Namaste {patient}! See you on {date} at {time}.'})
        self.assertEqual(appointment_message(appt, 'booked'), f'Namaste Sita Gurung! See you on {self.tomorrow:%d %b %Y} at 3:00 PM.')
        self.assertContains(self.client.get(reverse('accounts:messages')), 'edited')
        r = self.client.post(reverse('accounts:message-save', args=['appointment_booked']), {'body': '   '})  # empty is refused, the old wording stays
        self.assertIn('Namaste', MessageTemplate.objects.get(key='appointment_booked').body)
        self.client.post(reverse('accounts:message-reset', args=['appointment_booked']))
        self.assertFalse(MessageTemplate.objects.exists())
        self.assertIn('is booked for', appointment_message(appt, 'booked'))
        self.assertEqual(self.client.post(reverse('accounts:message-save', args=['made-up-key']), {'body': 'x'}).status_code, 302)
        self.assertFalse(MessageTemplate.objects.exists())  # only real messages can be saved

    def test_the_calendar_offers_confirmation_reminder_and_rescheduled_and_cancelling_offers_a_cancelled_message(self):
        appt = self.book()
        page = self.client.get(reverse('accounts:appointments'), {'date': self.tomorrow.isoformat(), 'days': 1})
        event = [e for col in page.context['columns'] for e in col['events']][0]
        self.assertEqual(set(event['wa']), {'booked', 'reminder', 'rescheduled'})
        self.assertIn('reminder', unquote(event['wa']['reminder']))
        self.assertContains(page, 'id="dWaKind"')
        r = self.client.post(reverse('accounts:appointment-action', args=[appt.pk]), {'action': 'cancel'})
        self.assertIn('kind=cancelled', r['Location'])
        banner = self.client.get(r['Location'])
        self.assertEqual(banner.context['prompt']['kind'], 'cancelled')
        self.assertIn('has been cancelled', unquote(banner.context['prompt']['url']))
        self.assertContains(banner, 'Cancelled: Sita Gurung')

    def test_custom_notices_can_be_added_edited_deleted_and_are_private(self):
        self.client.post(reverse('accounts:custom-add'), {'title': 'Holiday closure', 'body': 'Hello {patient}, {practice} is closed on {date}.'})
        notice = MessageTemplate.objects.get(is_custom=True)
        self.assertTrue(notice.key.startswith('custom-'))
        self.client.post(reverse('accounts:message-save', args=[notice.key]), {'title': 'Holiday', 'body': 'Closed on {date}. Contact: {contact}'})
        notice.refresh_from_db()
        self.assertEqual((notice.title, notice.body), ('Holiday', 'Closed on {date}. Contact: {contact}'))
        self.client.post(reverse('accounts:custom-add'), {'title': '', 'body': 'no title'})
        self.assertEqual(MessageTemplate.objects.count(), 1)
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        other.post(reverse('accounts:custom-delete', args=[notice.key]))
        other.post(reverse('accounts:message-save', args=[notice.key]), {'body': 'hijack'})
        notice.refresh_from_db()
        self.assertEqual(notice.body, 'Closed on {date}. Contact: {contact}')
        self.client.post(reverse('accounts:custom-delete', args=[notice.key]))
        self.assertFalse(MessageTemplate.objects.exists())

    def test_notice_page_prepares_a_message_for_each_patient_in_the_chosen_group(self):
        stale = make_patient(self.profile, 'Old Patient', phone='9841000555')
        stale.last_visit = timezone.localdate() - datetime.timedelta(days=40)
        stale.save()
        fresh = make_patient(self.profile, 'Fresh Patient')
        fresh.last_visit = timezone.localdate()
        fresh.save()
        page = self.client.get(reverse('accounts:notice-send'), {'t': 'followup', 'audience': 'followup'})
        names = [r['patient'].name for r in page.context['rows']]
        self.assertIn('Old Patient', names)
        self.assertNotIn('Fresh Patient', names)
        row = [r for r in page.context['rows'] if r['patient'].name == 'Old Patient'][0]
        self.assertTrue(row['url'].startswith('https://wa.me/9779841000555?text='))
        self.assertIn('Hello Old Patient', row['text'])
        self.assertContains(page, 'WhatsApp')
        self.client.post(reverse('accounts:custom-add'), {'title': 'Camp', 'body': 'Hi {patient}, free camp on {date} at {practice}.'})
        key = MessageTemplate.objects.get(is_custom=True).key
        self.book()
        page = self.client.get(reverse('accounts:notice-send'), {'t': key, 'audience': 'appointments', 'date': self.tomorrow.isoformat()})
        self.assertEqual([r['patient'].name for r in page.context['rows']], ['Sita Gurung'])
        self.assertIn(f'free camp on {self.tomorrow:%d %b %Y}', page.context['rows'][0]['text'])
        found = self.client.get(reverse('accounts:notice-send'), {'audience': 'search', 'q': 'old'})
        self.assertEqual([r['patient'].name for r in found.context['rows']], ['Old Patient'])
        self.assertEqual(len(self.client.get(reverse('accounts:notice-send'), {'audience': 'search'}).context['rows']), 0)
        everyone = self.client.get(reverse('accounts:notice-send'), {'audience': 'all', 't': 'not-a-template'})
        self.assertEqual(everyone.status_code, 200)
        self.assertEqual(len(everyone.context['rows']), 3)

    def test_the_bill_message_follows_the_professionals_wording(self):
        from billing.models import BillingEntry
        self.client.post(reverse('billing:patient-bill', args=[self.patient.pk]), {'entry_date': timezone.localdate().isoformat(), 'service': 'S', 'rate': '500', 'payment_mode': 'cash', 'payment_status': 'due'})
        entry = BillingEntry.objects.get()
        self.client.post(reverse('accounts:message-save', args=['bill']), {'body': 'Dear {patient}: {invoice} NPR {amount}\n{due_line}\nPay: {link}'})
        page = self.client.get(reverse('billing:invoice', args=[entry.pk]))
        self.assertIn('Dear Sita Gurung: ' + entry.invoice_number, page.context['message'])
        self.assertIn('is still due', page.context['message'])
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789'})
        self.assertContains(self.client.get(reverse('billing:invoice', args=[entry.pk])), 'WhatsApp +977 970-2235789')

    def test_only_approved_workspaces_reach_the_messages_pages(self):
        make_professional('waiting', status='submitted')
        self.client.logout()
        self.client.login(username='waiting', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('accounts:messages')).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:notice-send')).status_code, 302)


class ViberTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    def book(self):
        start = aware(self.tomorrow, datetime.time(15, 0))
        return Appointment.objects.create(professional=self.profile, patient=self.patient, start=start, end=start + datetime.timedelta(minutes=30))

    def test_channel_links_put_the_patients_app_first_and_viber_copies_the_text(self):
        links = messaging.channel_links('9841234567', 'Hello there', 'viber')
        self.assertEqual([l['key'] for l in links], ['viber', 'whatsapp', 'sms'])
        viber = links[0]
        self.assertEqual((viber['url'], viber['copy'], viber['preferred']), ('viber://chat?number=%2B9779841234567', 'Hello there', True))
        self.assertTrue(links[1]['url'].startswith('https://wa.me/9779841234567?text='))
        self.assertTrue(links[2]['url'].startswith('sms:+9779841234567?body='))
        blank = messaging.channel_links('', 'Hello there', 'whatsapp')  # no number: the app's contact picker
        by_key = {l['key']: l for l in blank}
        self.assertTrue(by_key['viber']['url'].startswith('viber://forward?text='))
        self.assertEqual(by_key['viber']['copy'], '')
        self.assertEqual(by_key['sms']['url'], 'sms:?body=Hello%20there')
        self.assertEqual([l['key'] for l in messaging.channel_links('9841234567', 'x')], ['whatsapp', 'viber', 'sms'])

    def test_the_patients_app_is_chosen_on_the_form_and_comes_first_on_the_booking_message(self):
        self.client.post(reverse('accounts:patient-add'), {'name': 'Viber User', 'phone': '9800000777', 'gender': 'F', 'age': '30', 'messaging_app': 'viber'})
        viber_patient = self.profile.patients.get(name='Viber User')
        self.assertEqual(viber_patient.messaging_app, 'viber')
        self.client.post(reverse('accounts:patient-add'), {'name': 'Default User', 'phone': '9800000778', 'gender': 'F', 'age': '30'})  # not chosen: WhatsApp
        self.assertEqual(self.profile.patients.get(name='Default User').messaging_app, 'whatsapp')
        self.client.post(reverse('accounts:patient-edit', args=[viber_patient.pk]), {'name': 'Viber User', 'phone': '9800000777', 'gender': 'F', 'age': '30', 'messaging_app': 'sms', 'status': 'active'})
        viber_patient.refresh_from_db()
        self.assertEqual(viber_patient.messaging_app, 'sms')
        self.assertContains(self.client.get(reverse('accounts:patient-add')), 'name="messaging_app"')
        # the booking banner leads with the patient's own app and still offers the others
        self.patient.messaging_app = 'viber'
        self.patient.save()
        appt = self.book()
        page = self.client.get(reverse('accounts:appointments'), {'booked': appt.pk})
        links = page.context['prompt']['links']
        self.assertEqual([l['key'] for l in links], ['viber', 'whatsapp', 'sms'])
        self.assertContains(page, 'Send by Viber')
        self.assertContains(page, 'data-copy=')
        self.assertContains(page, 'viber://chat?number=%2B9779841000000')
        event = [e for col in self.client.get(reverse('accounts:appointments'), {'date': self.tomorrow.isoformat(), 'days': 1}).context['columns'] for e in col['events']][0]
        self.assertEqual([l['key'] for l in event['links']['booked']], ['viber', 'whatsapp', 'sms'])
        self.assertEqual(set(event['links']), {'booked', 'reminder', 'rescheduled'})

    def test_notices_offer_every_app_and_the_business_viber_number_appears_in_messages(self):
        self.patient.messaging_app = 'viber'
        self.patient.last_visit = timezone.localdate() - datetime.timedelta(days=40)
        self.patient.save()
        page = self.client.get(reverse('accounts:notice-send'), {'audience': 'followup'})
        row = page.context['rows'][0]
        self.assertEqual([l['key'] for l in row['links']], ['viber', 'whatsapp', 'sms'])
        self.assertContains(page, 'data-copy=')
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789', 'viber_number': '+977 980-1111111'})
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.whatsapp_number, self.profile.viber_number), ('+977 970-2235789', '+977 980-1111111'))
        self.assertIn('WhatsApp +977 970-2235789, Viber +977 980-1111111', messaging.contact_text(self.profile))
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789', 'viber_number': 'x'})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.viber_number, '+977 980-1111111')  # a bad number changes nothing

    def test_invoice_and_front_desk_offer_the_patients_app(self):
        from billing.models import BillingEntry
        self.patient.messaging_app = 'viber'
        self.patient.save()
        self.client.post(reverse('billing:patient-bill', args=[self.patient.pk]), {'entry_date': timezone.localdate().isoformat(), 'service': 'S', 'rate': '500', 'payment_mode': 'cash', 'payment_status': 'paid'})
        entry = BillingEntry.objects.get()
        page = self.client.get(reverse('billing:invoice', args=[entry.pk]))
        self.assertEqual([l['key'] for l in page.context['links']], ['viber', 'whatsapp', 'sms'])
        self.assertContains(page, 'Viber (opens chat, paste)')
