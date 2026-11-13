"""Controls that limit and record what the platform operator and staff can see: patient records out of the admin, the code-only support view, the access
log the clinic reads, sign-in alerts, and two-step sign-in (authenticator codes)."""
from django.contrib import admin
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import totp
from accounts.models import AccessLog, TwoFactor
from accounts.tests.helpers import PASSWORD, make_patient, make_professional


def staff(name='operator', password='A-long-staff-password-1'):
    return User.objects.create_user(name, f'{name}@example.com', password, is_staff=True)


class AdminHidesPatientDataTests(TestCase):
    def test_patient_records_are_not_in_the_admin(self):
        from accounts.models import Patient, TreatmentPlan, Visit
        from billing.models import BillingEntry
        from exercises.models import Prescription
        from soapnotes.models import SoapNote
        registered = set(admin.site._registry)
        for model in (Patient, Visit, TreatmentPlan, BillingEntry, Prescription, SoapNote):
            self.assertNotIn(model, registered, model.__name__)
        from accounts.models import ProfessionalProfile
        from clinics.models import Clinic
        self.assertIn(ProfessionalProfile, registered)  # the operator keeps what is needed to run the service
        self.assertIn(Clinic, registered)


class SupportViewTests(TestCase):
    def setUp(self):
        self.owner, self.profile = make_professional('owner1')
        self.owner.email = 'owner@example.com'
        self.owner.save()
        self.patient = make_patient(self.profile, 'Sita Secret Name', phone='9841777777')
        self.ops = staff()
        self.client.force_login(self.ops)

    def test_support_sees_codes_and_counts_never_names_or_phones(self):
        page = self.client.get(reverse('support-workspace', args=[self.profile.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.patient.patient_code)
        self.assertNotContains(page, 'Sita Secret Name')
        self.assertNotContains(page, '9841777777')
        overview = self.client.get(reverse('support-overview'))
        self.assertEqual(overview.status_code, 200)

    def test_it_is_written_to_the_clinics_access_log_and_the_owner_is_told(self):
        self.client.get(reverse('support-workspace', args=[self.profile.pk]))
        line = AccessLog.objects.get(workspace=self.profile, action='support')
        self.assertTrue(line.operator)
        self.assertEqual(line.user, self.ops)
        self.assertEqual([m.to for m in mail.outbox if 'support opened' in m.subject], [['owner@example.com']])
        self.client.get(reverse('support-workspace', args=[self.profile.pk]))   # the same visit again within ten minutes: one line, one e-mail
        self.assertEqual(AccessLog.objects.filter(workspace=self.profile, action='support').count(), 1)

    def test_only_staff_can_open_it(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('support-overview')).status_code, 302)


class AccessLogTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional('owner2')
        self.patient = make_patient(self.profile, 'Ram Visible')
        self.client.force_login(self.user)

    def test_opening_a_patients_record_is_logged_and_the_owner_reads_it_with_the_name(self):
        self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'soap'})
        line = AccessLog.objects.get(action='view', patient_code=self.patient.patient_code)
        self.assertEqual((line.workspace, line.user, line.operator), (self.profile, self.user, False))
        page = self.client.get(reverse('accounts:access-log'))
        self.assertContains(page, 'Ram Visible')
        self.assertContains(page, 'opened the soap tab')

    def test_the_support_lines_are_marked_and_another_clinic_sees_none_of_it(self):
        ops = staff('ops2')
        AccessLog.objects.create(user=ops, user_label='ops2', role='platform staff', operator=True, workspace=self.profile, action='support', detail='opened the support view')
        page = self.client.get(reverse('accounts:access-log'))
        self.assertContains(page, 'Sajhya staff')
        self.assertContains(page, '1 line below is from Sajhya support staff')
        other, other_profile = make_professional('other-owner')
        client = self.client_class()
        client.force_login(other)
        self.assertNotContains(client.get(reverse('accounts:access-log')), 'opened the support view')

    def test_exports_and_shares_are_logged_each_time(self):
        self.client.get(reverse('billing:export-csv'))
        self.client.get(reverse('billing:export-csv'))
        self.assertEqual(AccessLog.objects.filter(action='export', workspace=self.profile).count(), 2)

    def test_sign_ins_are_logged(self):
        client = self.client_class()
        client.post(reverse('accounts:login'), {'username': self.user.get_username(), 'password': PASSWORD})
        self.assertTrue(AccessLog.objects.filter(action='login', user=self.user).exists())


class StaffAlertTests(TestCase):
    @override_settings(SECURITY_ALERT_EMAILS=['boss@example.com'])
    def test_a_staff_sign_in_and_a_failed_one_are_e_mailed(self):
        staff('ops3', 'A-long-staff-password-3')
        self.client.post(reverse('accounts:login'), {'username': 'ops3', 'password': 'wrong-password-here'})
        self.client.post(reverse('accounts:login'), {'username': 'ops3', 'password': 'A-long-staff-password-3'})
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any('Failed staff sign-in' in s for s in subjects), subjects)
        self.assertTrue(any('Staff sign-in' in s for s in subjects), subjects)
        self.assertEqual(mail.outbox[0].to, ['boss@example.com'])

    @override_settings(SECURITY_ALERT_EMAILS=['boss@example.com'])
    def test_an_ordinary_sign_in_sends_no_alert(self):
        user, profile = make_professional('ordinary')
        self.client.post(reverse('accounts:login'), {'username': user.get_username(), 'password': PASSWORD})
        self.assertEqual(mail.outbox, [])


class TotpTests(TestCase):
    def test_codes_match_the_rfc_6238_test_vector_and_cannot_be_reused(self):
        import base64
        secret = base64.b32encode(b'12345678901234567890').decode()       # the RFC's sample key
        self.assertEqual(totp._code(secret, 59 // 30), '287082')          # RFC 6238: time 59 gives 94287082 (last six digits)
        step = totp.current_step()
        code = totp._code(secret, step)
        self.assertEqual(totp.verify(secret, code, 0), step)
        self.assertIsNone(totp.verify(secret, code, step))                # already used
        self.assertIsNone(totp.verify(secret, '000000', 0) if code != '000000' else None)
        self.assertIsNone(totp.verify(secret, 'abc', 0))


class TwoStepSignInTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional('twostep')

    def turn_on(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse('accounts:security'))
        self.assertContains(page, 'Enter a setup key')
        secret = self.client.session['mfa_setup_secret']
        bad = self.client.post(reverse('accounts:security'), {'action': 'confirm', 'code': '000000'})
        self.assertContains(bad, 'not right')
        done = self.client.post(reverse('accounts:security'), {'action': 'confirm', 'code': totp._code(secret, totp.current_step())})
        codes = done.context['new_codes']
        self.assertEqual(len(codes), 10)
        self.client.logout()
        return secret, codes

    def test_setup_then_sign_in_needs_the_code(self):
        secret, codes = self.turn_on()
        response = self.client.post(reverse('accounts:login'), {'username': 'twostep', 'password': PASSWORD})
        self.assertRedirects(response, reverse('accounts:login-verify'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 302)      # not signed in yet
        wrong = self.client.post(reverse('accounts:login-verify'), {'code': '123456'})
        self.assertContains(wrong, 'not right')
        two = TwoFactor.objects.get(user=self.user)
        two.last_step = 0
        two.save()
        ok = self.client.post(reverse('accounts:login-verify'), {'code': totp._code(secret, totp.current_step())})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)       # signed in

    def test_a_recovery_code_works_once(self):
        secret, codes = self.turn_on()
        self.client.post(reverse('accounts:login'), {'username': 'twostep', 'password': PASSWORD})
        self.assertEqual(self.client.post(reverse('accounts:login-verify'), {'code': codes[0]}).status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        self.client.logout()
        self.client.post(reverse('accounts:login'), {'username': 'twostep', 'password': PASSWORD})
        again = self.client.post(reverse('accounts:login-verify'), {'code': codes[0]})
        self.assertContains(again, 'not right')

    def test_too_many_wrong_codes_end_the_attempt(self):
        self.turn_on()
        self.client.post(reverse('accounts:login'), {'username': 'twostep', 'password': PASSWORD})
        for _ in range(5):
            last = self.client.post(reverse('accounts:login-verify'), {'code': '111111'})
        self.assertEqual(last.status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:login-verify')).status_code, 302)   # the pending attempt is gone

    def test_a_person_without_two_step_signs_in_as_before(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'twostep', 'password': PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)

    def test_turning_it_off_needs_the_password_and_a_code(self):
        secret, codes = self.turn_on()
        self.client.post(reverse('accounts:login'), {'username': 'twostep', 'password': PASSWORD})
        two = TwoFactor.objects.get(user=self.user)
        self.client.post(reverse('accounts:login-verify'), {'code': codes[1]})
        two.refresh_from_db()
        bad = self.client.post(reverse('accounts:security'), {'action': 'disable', 'code': totp._code(secret, totp.current_step() + 1), 'password': 'wrong'})
        self.assertContains(bad, 'not right')
        self.assertTrue(TwoFactor.objects.filter(user=self.user).exists())


@override_settings(REQUIRE_STAFF_MFA=True)
class StaffNeedTwoStepTests(TestCase):
    def test_staff_without_it_are_sent_to_set_it_up_and_can_then_use_the_support_pages(self):
        ops = staff('ops4')
        self.client.force_login(ops)
        response = self.client.get(reverse('support-overview'))
        self.assertRedirects(response, reverse('accounts:security'), fetch_redirect_response=False)
        self.assertEqual(self.client.get('/' + __import__('django.conf', fromlist=['settings']).settings.ADMIN_URL).status_code, 302)
        page = self.client.get(reverse('accounts:security'))
        self.assertContains(page, 'Platform staff accounts need this')
        secret = self.client.session['mfa_setup_secret']
        self.client.post(reverse('accounts:security'), {'action': 'confirm', 'code': totp._code(secret, totp.current_step())})
        self.assertEqual(self.client.get(reverse('support-overview')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)
        self.assertTrue(AccessLog.objects.filter(action='operator', user=ops).exists())   # the admin page is in the log

    def test_staff_cannot_turn_it_off(self):
        ops = staff('ops5')
        self.client.force_login(ops)
        self.client.get(reverse('accounts:security'))
        secret = self.client.session['mfa_setup_secret']
        self.client.post(reverse('accounts:security'), {'action': 'confirm', 'code': totp._code(secret, totp.current_step())})
        page = self.client.post(reverse('accounts:security'), {'action': 'disable', 'code': totp._code(secret, totp.current_step() + 1), 'password': 'A-long-staff-password-1'})
        self.assertContains(page, 'must keep two-step sign-in on')
