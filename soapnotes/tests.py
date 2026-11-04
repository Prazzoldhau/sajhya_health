import datetime
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import TreatmentPlan, Visit
from accounts.tests.helpers import PASSWORD, make_patient, make_professional

from .models import SoapAddendum, SoapNote


def full_note(**extra):
    """A posted SOAP form, filled in the way a physiotherapist would."""
    data = {
        'note_date': timezone.localdate().isoformat(), 'note_type': 'initial', 'chief_complaint': 'Right shoulder pain on overhead reach',
        'mechanism': 'Gradual onset 3 weeks', 'pain_now': '6', 'pain_best': '3', 'pain_worst': '8', 'pain_location': 'Lateral shoulder', 'pain_character': 'Sharp',
        'history': 'Swimmer, increased training load', 'red_flags': ['night_pain'], 'observation': 'Rounded shoulders', 'palpation': 'Tender supraspinatus',
        'rom_json': json.dumps([{'movement': 'Shoulder abduction', 'side': 'Right', 'active': '110', 'passive': '140', 'pain': True, 'note': 'painful arc'}]),
        'strength_json': json.dumps([{'muscle': 'Supraspinatus', 'side': 'Right', 'grade': '4-'}, {'muscle': 'Bad', 'side': 'Nowhere', 'grade': '9'}]),
        'tests_json': json.dumps([{'name': 'Neer impingement', 'result': 'positive', 'note': ''}]),
        'impression': 'Subacromial impingement syndrome', 'icd10_code': 'm75.4', 'stage': 'subacute', 'irritability': 'moderate', 'prognosis': 'good',
        'treatment_today': 'Soft tissue release, scapular setting', 'frequency_per_week': '3', 'duration_weeks': '6', 'next_review': '',
        'measures_json': json.dumps([{'name': 'Shoulder abduction ROM', 'unit': '°', 'baseline': '110', 'target': '170'}, {'name': 'Pain on activity (VAS 0-10)', 'unit': '/10', 'baseline': '7', 'target': '2'}]),
        'goals_json': json.dumps([{'text': 'Pain-free overhead reach', 'term': 'short', 'target_date': ''}, {'text': 'Return to swimming', 'term': 'long', 'target_date': '2027-01-31'}]),
        'precautions': 'Avoid loaded overhead lifting', 'education': 'Posture advice', 'hep': 'Pendulums, scapular squeezes', 'action': 'draft',
    }
    data.update(extra)
    return data


class Base(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional('soap')
        self.client.login(username='soap', password=PASSWORD)
        self.patient = make_patient(self.profile, 'Soap Patient')
        self.new = reverse('soapnotes:new', args=[self.patient.pk])

    def as_user(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)

    def create(self, **extra):
        self.client.post(self.new, full_note(**extra))
        return SoapNote.objects.order_by('-id').first()


class TabTests(Base):
    def test_soap_tab_sits_right_after_overview_and_lists_notes(self):
        page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'soap'})
        html = page.content.decode()
        self.assertLess(html.index('?tab=overview'), html.index('?tab=soap'))
        self.assertLess(html.index('?tab=soap'), html.index('?tab=plan'))
        self.assertContains(page, 'No SOAP notes yet')
        note = self.create()
        page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'soap'})
        self.assertContains(page, 'Right shoulder pain on overhead reach')
        self.assertContains(page, '2 metrics')
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk])), 'New SOAP Note')  # quick action on the overview

    def test_form_renders(self):
        page = self.client.get(self.new)
        self.assertContains(page, 'Subjective')
        self.assertContains(page, 'Range of motion')
        self.assertContains(page, 'Baseline metrics')
        self.assertContains(page, 'Clinical goals')
        self.assertContains(page, 'id="hepName"')  # the home exercise programme searches the library
        self.assertContains(page, 'id="dl-hep-dose"')  # and the dose is a searchable list


class WritingTests(Base):
    def test_a_draft_stores_everything_cleaned(self):
        r = self.client.post(self.new, full_note())
        note = SoapNote.objects.get()
        self.assertRedirects(r, reverse('soapnotes:edit', args=[note.pk]), fetch_redirect_response=False)
        self.assertEqual((note.status, note.note_type, note.author, note.icd10_code), ('draft', 'initial', self.profile, 'M75.4'))
        self.assertEqual((note.pain_now, note.pain_worst, note.frequency_per_week, note.duration_weeks), (6, 8, 3, 6))
        self.assertEqual(note.red_flags, ['night_pain'])
        self.assertEqual(note.rom[0], {'movement': 'Shoulder abduction', 'side': 'Right', 'active': '110', 'passive': '140', 'pain': True, 'note': 'painful arc'})
        self.assertEqual(note.strength, [{'muscle': 'Supraspinatus', 'side': 'Right', 'grade': '4-'}, {'muscle': 'Bad', 'side': '', 'grade': ''}])  # invalid side/grade dropped
        self.assertEqual(note.measures[0], {'name': 'Shoulder abduction ROM', 'unit': '°', 'baseline': '110', 'target': '170'})
        self.assertEqual([g['term'] for g in note.goals], ['short', 'long'])
        self.assertEqual(note.goals[1]['target_date'], '2027-01-31')

    def test_validation_keeps_the_page_and_saves_nothing(self):
        for bad in ({'pain_now': '11'}, {'frequency_per_week': '40'}, {'note_date': ''}, {'next_review': 'soon'},
                    {'measures_json': json.dumps([{'name': 'ROM', 'baseline': 'abc', 'target': '5'}])},
                    {'goals_json': json.dumps([{'text': 'Goal', 'target_date': '31/12'}])}):
            r = self.client.post(self.new, full_note(**bad))
            self.assertEqual(r.status_code, 200, bad)
            self.assertContains(r, 'Please fix')
            self.assertContains(r, 'Right shoulder pain on overhead reach')  # what was typed is kept
        self.assertFalse(SoapNote.objects.exists())
        tomorrow = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        self.assertContains(self.client.post(self.new, full_note(note_date=tomorrow)), 'cannot be in the future')

    def test_cannot_finalise_an_empty_note(self):
        r = self.client.post(self.new, {'note_date': timezone.localdate().isoformat(), 'action': 'final'})
        self.assertContains(r, 'needs at least')
        self.assertFalse(SoapNote.objects.exists())

    def test_finalising_locks_the_note_and_allows_addenda(self):
        r = self.client.post(self.new, full_note(action='final'))
        note = SoapNote.objects.get()
        self.assertRedirects(r, reverse('soapnotes:detail', args=[note.pk]), fetch_redirect_response=False)
        self.assertEqual((note.status, bool(note.finalized_at)), ('final', True))
        self.assertRedirects(self.client.get(reverse('soapnotes:edit', args=[note.pk])), reverse('soapnotes:detail', args=[note.pk]), fetch_redirect_response=False)
        self.client.post(reverse('soapnotes:edit', args=[note.pk]), full_note(chief_complaint='Rewritten history'))
        note.refresh_from_db()
        self.assertEqual(note.chief_complaint, 'Right shoulder pain on overhead reach')  # locked
        self.client.post(reverse('soapnotes:addendum', args=[note.pk]), {'text': 'Patient called: pain easing.'})
        self.assertEqual(SoapAddendum.objects.get().author_name, 'Asha Rai')
        self.assertContains(self.client.get(reverse('soapnotes:detail', args=[note.pk])), 'Patient called: pain easing.')
        self.client.post(reverse('soapnotes:delete', args=[note.pk]))
        self.assertEqual(SoapNote.objects.count(), 1)  # a final note cannot be deleted

    def test_draft_can_be_edited_finalised_and_deleted(self):
        note = self.create()
        self.client.post(reverse('soapnotes:edit', args=[note.pk]), full_note(chief_complaint='Edited complaint'))
        note.refresh_from_db()
        self.assertEqual(note.chief_complaint, 'Edited complaint')
        self.assertContains(self.client.get(reverse('soapnotes:edit', args=[note.pk])), 'Edited complaint')
        self.client.post(reverse('soapnotes:addendum', args=[note.pk]), {'text': 'x'})  # drafts take no addenda
        self.assertFalse(SoapAddendum.objects.exists())
        self.client.post(reverse('soapnotes:delete', args=[note.pk]))
        self.assertFalse(SoapNote.objects.exists())

    def test_recording_a_visit_is_optional_and_happens_once(self):
        note = self.create()
        self.assertFalse(Visit.objects.exists())
        url = reverse('soapnotes:edit', args=[note.pk])
        self.client.post(url, full_note(record_visit='1'))
        self.client.post(url, full_note(record_visit='1'))
        self.assertEqual(Visit.objects.count(), 1)
        self.assertTrue(Visit.objects.get().notes.startswith('SOAP note:'))
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.last_visit, timezone.localdate())

    def test_a_follow_up_starts_from_the_previous_notes_metrics_and_goals(self):
        self.create(action='final')
        page = self.client.get(self.new)
        self.assertContains(page, 'carried over')
        state = page.context['state']
        self.assertEqual([m['name'] for m in state['measures']], ['Shoulder abduction ROM', 'Pain on activity (VAS 0-10)'])
        self.assertEqual([m['baseline'] for m in state['measures']], ['', ''])  # today's readings are entered fresh
        self.assertEqual(state['measures'][0]['target'], '170')
        self.assertEqual(len(state['goals']), 2)
        self.assertEqual(page.context['v']['note_type'], 'follow_up')


class TreatmentPlanLinkTests(Base):
    def state(self, **params):
        return self.client.get(reverse('accounts:plan-new', args=[self.patient.pk]), params).context['state']

    def test_new_plan_starts_from_the_latest_soap_note(self):
        self.create(action='final')
        page = self.client.get(reverse('accounts:plan-new', args=[self.patient.pk]))
        self.assertContains(page, 'Started from the SOAP note')
        state = page.context['state']
        self.assertEqual([(m['name'], m['baseline'], m['target']) for m in state['measures']], [('Shoulder abduction ROM', '110', '170'), ('Pain on activity (VAS 0-10)', '7', '2')])
        self.assertEqual([(g['text'], g['term']) for g in state['goals']], [('Pain-free overhead reach', 'short'), ('Return to swimming', 'long')])
        self.assertEqual((state['diagnosis'], state['icd10_code'], state['precautions'], state['education']), ('Subacromial impingement syndrome', 'M75.4', 'Avoid loaded overhead lifting', 'Posture advice'))
        self.assertEqual((state['phases'][0]['frequency_per_week'], state['phases'][0]['week_end']), (3, 6))

    def test_choosing_blank_or_a_specific_note_and_the_prefilled_plan_saves(self):
        first = self.create(action='final', measures_json=json.dumps([{'name': 'Old measure', 'unit': '', 'baseline': '1', 'target': '2'}]))
        self.create(action='final')
        self.assertEqual(self.state(from_soap='none')['measures'], [])
        self.assertEqual([m['name'] for m in self.state(from_soap=str(first.pk))['measures']], ['Old measure'])
        # a later note without metrics does not hide the earlier note's metrics
        self.create(action='final', measures_json='[]', goals_json='[]', note_type='follow_up')
        self.assertEqual(len(self.state()['measures']), 2)
        # saving the pre-filled plan through the normal builder endpoint works
        state = self.state()
        state['phases'][0]['items'] = []
        r = self.client.post(reverse('accounts:plan-create', args=[self.patient.pk]), json.dumps({**state, 'action': 'draft'}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        plan = TreatmentPlan.objects.get()
        self.assertEqual(plan.measures.count(), 2)
        self.assertEqual(plan.goals.count(), 2)

    def test_plan_without_notes_is_unchanged(self):
        page = self.client.get(reverse('accounts:plan-new', args=[self.patient.pk]))
        self.assertNotContains(page, 'Started from the SOAP note')
        self.assertEqual(page.context['state']['measures'], [])


class AccessTests(Base):
    def test_other_professionals_cannot_see_or_change_notes(self):
        note = self.create(action='final')
        make_professional('stranger')
        self.as_user('stranger')
        for url in (reverse('soapnotes:detail', args=[note.pk]), reverse('soapnotes:edit', args=[note.pk]), reverse('soapnotes:new', args=[self.patient.pk])):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        for url in (reverse('soapnotes:addendum', args=[note.pk]), reverse('soapnotes:delete', args=[note.pk])):
            self.assertEqual(self.client.post(url, {'text': 'x'}).status_code, 404, url)

    def test_unapproved_professional_is_locked_out(self):
        make_professional('waiting', status='submitted')
        self.as_user('waiting')
        self.assertRedirects(self.client.get(self.new), reverse('accounts:welcome'), fetch_redirect_response=False)

    def test_clinic_colleagues_read_notes_but_only_the_author_edits_a_draft(self):
        from clinics.models import Clinic, ClinicMember, ClinicSubscription
        clinic = Clinic.objects.create(owner=self.profile, name='Team Clinic', phone='015550001')
        ClinicSubscription.objects.create(professional=self.profile, status='active')
        self.patient.clinic = clinic
        self.patient.save()
        physio_user, physio = make_professional('colleague')
        self.patient.assigned.add(ClinicMember.objects.create(clinic=clinic, physio=physio, status='active'))
        draft = self.create()
        final = self.create(action='final')
        self.as_user('colleague')
        self.assertEqual(self.client.get(reverse('soapnotes:detail', args=[final.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('soapnotes:edit', args=[draft.pk])).status_code, 404)  # not their draft
        self.client.post(reverse('soapnotes:addendum', args=[final.pk]), {'text': 'Colleague addendum'})
        self.assertEqual(SoapAddendum.objects.get().author_name, physio.full_name)
        # and the colleague can write their own note on the shared patient
        r = self.client.post(reverse('soapnotes:new', args=[self.patient.pk]), full_note(action='final'))
        self.assertEqual(SoapNote.objects.filter(author=physio).count(), 1)


class SendToPatientTests(Base):
    """A finalised note can be sent to the patient: PDF, picture, a message with a signed link, e-mail."""
    def final(self, **extra):
        return self.create(action='final', **extra)

    def test_only_a_finalised_note_can_be_sent_and_the_button_appears_after_finalising(self):
        draft = self.create()
        self.assertNotContains(self.client.get(reverse('soapnotes:detail', args=[draft.pk])), 'Send to patient')
        self.assertRedirects(self.client.get(reverse('soapnotes:send', args=[draft.pk])), reverse('soapnotes:detail', args=[draft.pk]), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('soapnotes:pdf', args=[draft.pk])).status_code, 404)
        note = self.final()
        self.assertContains(self.client.get(reverse('soapnotes:detail', args=[note.pk])), 'Send to patient')

    def test_the_send_page_has_the_picture_pdf_and_whatsapp_options_and_the_patients_number(self):
        self.patient.phone = '9841234567'
        self.patient.save()
        note = self.final()
        page = self.client.get(reverse('soapnotes:send', args=[note.pk]))
        self.assertEqual(page.status_code, 200)
        for text in ('Send as picture', 'WhatsApp: picture only', 'Download PDF', 'Subacromial impingement', 'wa.me/9779841234567'):
            self.assertContains(page, text)
        self.assertContains(page, 'Soap Patient')
        self.assertIn('/shared/', page.context['public_url'])
        self.assertIn('Soap Patient', page.context['message'])

    def test_the_pdf_is_a_real_pdf_and_the_signed_link_works_without_signing_in(self):
        note = self.final()
        r = self.client.get(reverse('soapnotes:pdf', args=[note.pk]))
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/pdf'))
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('attachment', self.client.get(reverse('soapnotes:pdf', args=[note.pk]) + '?download=1')['Content-Disposition'])
        from . import share
        url = reverse('soapnotes:public', args=[share.note_token(note)])
        self.client.logout()
        public = self.client.get(url)
        self.assertEqual((public.status_code, public['Content-Type']), (200, 'application/pdf'))
        self.assertEqual(self.client.get(reverse('soapnotes:public', args=['not-a-real-link'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('soapnotes:pdf', args=[note.pk])).status_code, 302)  # the file itself needs a sign-in

    def test_a_link_to_a_note_that_is_not_final_or_other_text_in_another_script_does_not_break(self):
        from . import share
        note = self.final(impression='तनाव संबन्धी समस्या')  # Nepali text
        self.assertTrue(share.build_pdf(note).startswith(b'%PDF'))
        draft = self.create()
        self.assertIsNone(share.note_from_token(share.note_token(draft)))

    def test_other_practices_cannot_open_the_send_page_or_the_pdf(self):
        note = self.final()
        make_professional('other-soap')
        self.as_user('other-soap')
        self.assertEqual(self.client.get(reverse('soapnotes:send', args=[note.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('soapnotes:pdf', args=[note.pk])).status_code, 404)

    def test_the_note_can_be_e_mailed_as_a_pdf(self):
        from django.core import mail
        note = self.final()
        self.client.post(reverse('soapnotes:email', args=[note.pk]), {'email': 'patient@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['patient@example.com'])
        self.assertEqual((sent.attachments[0][2], sent.attachments[0][1][:4]), ('application/pdf', b'%PDF'))
        self.client.post(reverse('soapnotes:email', args=[note.pk]), {'email': 'nonsense'})
        self.assertEqual(len(mail.outbox), 1)


class EmailedNoteTests(Base):
    """The e-mail is a designed page with the PDF attached, every send is recorded, and the patient's address is used when there is one."""
    def final(self):
        return self.create(action='final')

    def test_the_email_has_an_html_page_with_the_practice_header_button_and_the_pdf_attached(self):
        from django.core import mail
        note = self.final()
        self.client.post(reverse('soapnotes:email', args=[note.pk]), {'email': 'patient@example.com'})
        sent = mail.outbox[0]
        html = sent.alternatives[0][0]
        self.assertEqual(sent.alternatives[0][1], 'text/html')
        for text in ('Your physiotherapy note', 'Open the note (PDF)', 'Soap Patient', '#116b43', '/shared/'):
            self.assertIn(text, html)
        self.assertIn('Soap Patient', sent.body)  # the plain-text version is still there
        self.assertEqual(sent.attachments[0][0], f'SOAP-note-{note.note_date:%Y-%m-%d}-{note.patient.patient_code}.pdf')

    def test_every_send_is_recorded_and_shown_on_the_note_and_the_send_page(self):
        from .models import SoapShare
        note = self.final()
        self.client.post(reverse('soapnotes:email', args=[note.pk]), {'email': 'patient@example.com'})
        share = SoapShare.objects.get()
        self.assertEqual((share.address, share.channel, share.note_id), ('patient@example.com', 'email', note.pk))
        self.assertTrue(share.sent_by_name)
        self.assertContains(self.client.get(reverse('soapnotes:detail', args=[note.pk])), 'Last e-mailed to patient@example.com')
        self.assertContains(self.client.get(reverse('soapnotes:send', args=[note.pk])), 'SENT BY E-MAIL')
        self.client.post(reverse('soapnotes:email', args=[note.pk]), {'email': 'bad'})  # a failed send is not recorded
        self.assertEqual(SoapShare.objects.count(), 1)

    def test_the_patients_email_is_filled_in_and_a_typed_one_can_be_saved_on_the_record(self):
        note = self.final()
        page = self.client.get(reverse('soapnotes:send', args=[note.pk]))
        self.assertContains(page, 'has no e-mail on record yet')
        self.assertContains(page, 'Save this e-mail on the patient')
        self.client.post(reverse('soapnotes:email', args=[note.pk]), {'email': 'new@example.com', 'save_email': '1'})
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.email, 'new@example.com')
        page = self.client.get(reverse('soapnotes:send', args=[note.pk]))
        self.assertContains(page, 'value="new@example.com"')
        self.assertContains(page, "Filled in from the patient's record")
        self.client.post(reverse('soapnotes:email', args=[note.pk]), {'email': 'other@example.com', 'save_email': '1'})
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.email, 'new@example.com')  # an address on record is never overwritten
