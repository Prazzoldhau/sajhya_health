import datetime
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Account, ClinicalFocus, ClinicType, EnterpriseType, Profession, ProfessionalProfile, ServiceType

from .helpers import PASSWORD, make_professional, pdf, private_storage

SIGNUP = {
    'first_name': 'Asha', 'last_name': 'Rai', 'mobile': '9800000000', 'title': 'PT', 'email': 'a@example.com',
    'username': 'asha', 'password1': PASSWORD, 'password2': PASSWORD,
}


class SignupTests(TestCase):
    def test_package_and_selection_pages_load(self):
        self.assertEqual(self.client.get(reverse('accounts:package')).status_code, 200)
        for kind in ('professional', 'enterprise'):
            r = self.client.get(reverse('accounts:select-type', args=[kind]))
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.context['options'])  # seeded lookup tables
        # clinics are registered from a professional account, not by their own signup
        self.assertRedirects(self.client.get(reverse('accounts:select-type', args=['clinic'])), reverse('clinics:register'), fetch_redirect_response=False)

    def test_unknown_type_redirects_to_package(self):
        self.assertRedirects(self.client.get('/accounts/signup/bogus/'), reverse('accounts:package'))

    def test_professional_signup_creates_account_and_profile(self):
        profession = Profession.objects.first()
        r = self.client.post(reverse('accounts:signup', args=['professional', profession.pk]), SIGNUP)
        self.assertRedirects(r, reverse('accounts:professional-step', args=[2]))
        profile = ProfessionalProfile.objects.get(account__user__username='asha')
        self.assertEqual(profile.account.profession, profession)
        self.assertEqual(profile.status, 'draft')
        self.assertEqual(profile.completed_step, 1)
        self.assertEqual(self.client.session['_auth_user_id'], str(profile.account.user_id))  # logged in

    def test_photo_uploaded_at_signup_is_kept_and_shown_after_approval(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (30, 30), 'green').save(buf, 'PNG')
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            r = self.client.post(reverse('accounts:signup', args=['professional', Profession.objects.first().pk]),
                                 {**SIGNUP, 'profile_picture': SimpleUploadedFile('me.png', buf.getvalue(), content_type='image/png')})
            self.assertEqual(r.status_code, 302)
            profile = ProfessionalProfile.objects.get(account__user__username='asha')
            self.assertTrue(profile.profile_picture)
            profile.status = 'approved'
            profile.completed_step = 4
            profile.save()
            page = self.client.get(reverse('accounts:dashboard'))
            self.assertContains(page, profile.profile_picture.url)

    def test_signup_rejects_weak_password_and_duplicate_username(self):
        url = reverse('accounts:signup', args=['professional', Profession.objects.first().pk])
        weak = self.client.post(url, {**SIGNUP, 'password1': '12345', 'password2': '12345'})
        self.assertEqual(weak.status_code, 200)
        self.assertFalse(User.objects.filter(username='asha').exists())
        self.client.post(url, SIGNUP)
        self.client.logout()
        again = self.client.post(url, {**SIGNUP, 'email': 'b@example.com'})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(User.objects.filter(username='asha').count(), 1)

    def test_client_signup_and_enterprise_needs_an_organization_name(self):
        r = self.client.post(reverse('accounts:signup-client'), {'username': 'cl1', 'email': 'c@example.com', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertRedirects(r, reverse('accounts:welcome'), fetch_redirect_response=False)
        self.assertEqual(Account.objects.get(user__username='cl1').account_type, 'client')
        self.client.logout()
        url = reverse('accounts:signup', args=['enterprise', EnterpriseType.objects.first().pk])
        missing_org = self.client.post(url, {'username': 'cn1', 'email': 'd@example.com', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertEqual(missing_org.status_code, 200)  # organization name is required for enterprises
        ok = self.client.post(url, {'username': 'cn1', 'email': 'd@example.com', 'password1': PASSWORD, 'password2': PASSWORD, 'organization_name': 'City Hospital'})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(Account.objects.get(user__username='cn1').organization_name, 'City Hospital')

    def test_welcome_requires_login(self):
        self.assertEqual(self.client.get(reverse('accounts:welcome')).status_code, 302)


class LoginTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()

    def test_login_logout_cycle(self):
        r = self.client.post(reverse('accounts:login'), {'username': 'pro', 'password': PASSWORD})
        self.assertRedirects(r, reverse('accounts:welcome'), fetch_redirect_response=False)
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post(reverse('accounts:logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_wrong_password_is_rejected(self):
        r = self.client.post(reverse('accounts:login'), {'username': 'pro', 'password': 'nope'})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_repeated_failures_lock_the_account_out(self):
        for _ in range(3):
            self.client.post(reverse('accounts:login'), {'username': 'pro', 'password': 'wrong'})
        locked = self.client.post(reverse('accounts:login'), {'username': 'pro', 'password': PASSWORD})
        self.assertEqual(locked.status_code, 429)  # even the right password is refused while locked
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_approved_professional_lands_on_dashboard_via_welcome(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('accounts:welcome')), reverse('accounts:dashboard'), fetch_redirect_response=False)


class OnboardingFlowTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional(status='draft', completed_step=1)
        self.client.force_login(self.user)

    def post_step(self, step, data, action='continue'):
        return self.client.post(reverse('accounts:professional-step', args=[step]), {**data, 'action': action})

    def test_cannot_skip_ahead(self):
        r = self.client.get(reverse('accounts:professional-step', args=[3]))
        self.assertRedirects(r, reverse('accounts:professional-step', args=[2]))

    def test_credentials_step_validates_and_advances(self):
        self.assertEqual(self.post_step(2, {'license_number': '123'}).status_code, 200)  # missing authority/expiry
        r = self.post_step(2, {'license_number': 'NHPC-1', 'issuing_authority': 'NHPC', 'license_expiry': '2030-01-01'})
        self.assertRedirects(r, reverse('accounts:professional-step', args=[3]))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.completed_step, 2)

    def test_save_and_finish_later_keeps_partial_answers_without_advancing(self):
        r = self.post_step(2, {'license_number': 'PARTIAL'}, action='later')
        self.assertRedirects(r, reverse('accounts:welcome'), fetch_redirect_response=False)
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.license_number, self.profile.completed_step), ('PARTIAL', 1))
        welcome = self.client.get(reverse('accounts:welcome'))
        self.assertContains(welcome, 'Continue onboarding')

    def complete_through_step_4(self):
        self.post_step(2, {'license_number': 'N1', 'issuing_authority': 'NHPC', 'license_expiry': '2030-01-01'})
        docs = {'id_document': pdf('id.pdf'), 'license_document': pdf('l.pdf'), 'degree_document': pdf('d.pdf')}
        self.assertRedirects(self.post_step(3, docs), reverse('accounts:professional-step', args=[4]))
        practice = {'years_experience': 5, 'focus_areas': [ClinicalFocus.objects.first().pk], 'services': [ServiceType.objects.first().pk]}
        self.assertRedirects(self.post_step(4, practice), reverse('accounts:professional-step', args=[5]))

    def test_document_validation(self):
        self.post_step(2, {'license_number': 'N1', 'issuing_authority': 'NHPC', 'license_expiry': '2030-01-01'})
        base = {'license_document': pdf(), 'degree_document': pdf()}
        with private_storage():
            bad_ext = self.post_step(3, {**base, 'id_document': SimpleUploadedFile('id.exe', b'MZ')})
            fake_pdf = self.post_step(3, {**base, 'id_document': SimpleUploadedFile('id.pdf', b'<html>not a pdf</html>')})
            too_big = self.post_step(3, {**base, 'id_document': SimpleUploadedFile('id.pdf', b'%PDF-' + b'0' * (5 * 1024 * 1024 + 1))})
        for r in (bad_ext, fake_pdf, too_big):
            self.assertEqual(r.status_code, 200)  # stayed on the step with an error
            self.assertTrue(r.context['form'].errors.get('id_document'))

    def test_full_flow_to_submission_and_staff_review(self):
        with private_storage():
            self.complete_through_step_4()
            self.assertEqual(self.client.get(reverse('accounts:professional-step', args=[5])).status_code, 200)
            self.assertRedirects(self.client.post(reverse('accounts:professional-step', args=[5])), reverse('accounts:welcome'), fetch_redirect_response=False)
            self.profile.refresh_from_db()
            self.assertEqual(self.profile.status, 'submitted')

            # documents are private: owner and staff can read them, others and anonymous users cannot
            doc_url = reverse('accounts:professional-document', args=['id_document'])
            self.assertEqual(self.client.get(doc_url).status_code, 200)
            stranger, _ = make_professional('stranger')
            other = self.client_class()
            other.force_login(stranger)
            self.assertEqual(other.get(doc_url).status_code, 404)
            self.assertEqual(self.client_class().get(doc_url).status_code, 302)

            staff, _ = make_professional('boss', staff=True)
            reviewer = self.client_class()
            reviewer.force_login(staff)
            self.assertEqual(reviewer.get(reverse('accounts:professional-document-staff', args=[self.profile.pk, 'id_document'])).status_code, 200)
            self.assertEqual(other.get(reverse('accounts:review-list')).status_code, 302)  # non-staff is bounced

            detail = reverse('accounts:review-detail', args=[self.profile.pk])
            reviewer.post(detail, {'decision': 'reject'})  # a reason is required
            self.profile.refresh_from_db()
            self.assertEqual(self.profile.status, 'submitted')
            reviewer.post(detail, {'decision': 'reject', 'reason': 'ID is blurry'})
            self.profile.refresh_from_db()
            self.assertEqual((self.profile.status, self.profile.rejection_reason, self.profile.reviewed_by), ('rejected', 'ID is blurry', staff))

            # the applicant sees the reason, can fix and resubmit, and is then approved
            self.assertContains(self.client.get(reverse('accounts:welcome')), 'ID is blurry')
            self.assertEqual(self.client.get(reverse('accounts:professional-step', args=[2])).status_code, 200)
            self.client.post(reverse('accounts:professional-step', args=[5]))
            self.profile.refresh_from_db()
            self.assertEqual((self.profile.status, self.profile.rejection_reason), ('submitted', ''))
            reviewer.post(detail, {'decision': 'approve'})
            self.profile.refresh_from_db()
            self.assertEqual(self.profile.status, 'approved')

    def test_cannot_submit_before_finishing_steps(self):
        self.client.post(reverse('accounts:professional-step', args=[2]), {'action': 'later', 'license_number': 'x'})
        self.assertEqual(self.client.get(reverse('accounts:professional-step', args=[5])).status_code, 302)

    def test_profile_picture_upload_validation(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (30, 30), 'green').save(buf, 'PNG')
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            bad = self.client.post(reverse('accounts:profile-picture'), {'profile_picture': SimpleUploadedFile('x.png', b'not an image')})
            self.assertEqual(bad.status_code, 200)
            ok = self.client.post(reverse('accounts:profile-picture'), {'profile_picture': SimpleUploadedFile('me.png', buf.getvalue(), content_type='image/png')})
            self.assertEqual(ok.status_code, 302)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.profile_picture)


class ReviewAccessTests(TestCase):
    def test_review_pages_need_staff(self):
        user, profile = make_professional()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('accounts:review-list')).status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:review-detail', args=[profile.pk])).status_code, 302)
        staff, _ = make_professional('boss', staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('accounts:review-list')).status_code, 200)


class BusinessOwnerTests(TestCase):
    """A business owner signs up as a professional, verifies with business documents and then registers clinics."""
    BUSINESS = {'business_name': 'Himal Care Pvt. Ltd.', 'business_registration_number': 'REG-1234', 'tax_number': '601234567', 'issuing_authority': 'Office of the Company Registrar'}

    def signup(self):
        owner = Profession.objects.get(is_business_owner=True)
        url = reverse('accounts:signup', args=['professional', owner.pk])
        self.assertNotIn('title', self.client.get(url).context['form'].fields)  # no professional title for an owner
        data = {k: v for k, v in SIGNUP.items() if k != 'title'}
        self.assertRedirects(self.client.post(url, data), reverse('accounts:professional-step', args=[2]))
        return ProfessionalProfile.objects.get(account__user__username='asha')

    def test_business_owner_is_a_profession_choice_beside_the_health_professions(self):
        page = self.client.get(reverse('accounts:select-type', args=['professional']))
        self.assertIn('business owner', [p.name for p in page.context['options']])
        self.assertEqual(Profession.objects.first().name, 'physiotherapist')  # existing choices are untouched
        self.assertEqual(Profession.objects.filter(is_business_owner=True).count(), 1)

    def test_business_onboarding_asks_for_registration_and_tax_documents_not_a_licence(self):
        profile = self.signup()
        self.assertTrue(profile.is_business_owner)
        self.assertEqual(profile.title, 'Owner')
        step2 = self.client.get(reverse('accounts:professional-step', args=[2]))
        self.assertContains(step2, 'Business registration number')
        self.assertContains(step2, 'PAN / tax number')
        self.assertNotContains(step2, 'Licence expiry')
        self.assertEqual([label for _, label, _ in step2.context['steps']], ['Account', 'Business', 'Documents', 'Review'])
        self.assertEqual(self.client.post(reverse('accounts:professional-step', args=[2]), {'business_name': 'X'}).status_code, 200)  # all four are required
        r = self.client.post(reverse('accounts:professional-step', args=[2]), self.BUSINESS)
        self.assertRedirects(r, reverse('accounts:professional-step', args=[3]))
        with private_storage():
            step3 = self.client.get(reverse('accounts:professional-step', args=[3]))
            self.assertContains(step3, 'Business registration certificate')
            self.assertContains(step3, 'PAN / tax registration certificate')
            self.assertNotContains(step3, 'Academic degrees')
            self.assertNotContains(step3, 'Proof of professional licence')
            docs = lambda: {'id_document': pdf('id.pdf'), 'registration_document': pdf('reg.pdf'), 'tax_document': pdf('pan.pdf')}  # fresh files for each post
            missing = self.client.post(reverse('accounts:professional-step', args=[3]), {k: v for k, v in docs().items() if k != 'tax_document'})
            self.assertTrue(missing.context['form'].errors.get('tax_document'))
            # straight to the review: there is no practice step
            self.assertRedirects(self.client.post(reverse('accounts:professional-step', args=[3]), docs()), reverse('accounts:professional-step', args=[5]))
            self.assertEqual(self.client.get(reverse('accounts:professional-step', args=[4])).status_code, 404)
            review = self.client.get(reverse('accounts:professional-step', args=[5]))
            self.assertContains(review, 'Himal Care Pvt. Ltd.')
            self.assertContains(review, 'Business registration certificate')
            self.assertNotContains(review, 'years of experience')
            self.assertRedirects(self.client.post(reverse('accounts:professional-step', args=[5])), reverse('accounts:welcome'), fetch_redirect_response=False)
            profile.refresh_from_db()
            self.assertEqual(profile.status, 'submitted')
            # the documents are private to the owner and the verification team
            stranger, _ = make_professional('stranger')
            other = self.client_class()
            other.force_login(stranger)
            for field in ('registration_document', 'tax_document'):
                self.assertEqual(self.client.get(reverse('accounts:professional-document', args=[field])).status_code, 200)
                self.assertEqual(other.get(reverse('accounts:professional-document', args=[field])).status_code, 404)
            staff, _ = make_professional('boss', staff=True)
            reviewer = self.client_class()
            reviewer.force_login(staff)
            detail = reviewer.get(reverse('accounts:review-detail', args=[profile.pk]))
            self.assertContains(detail, 'REG-1234')
            self.assertContains(detail, '601234567')
            self.assertContains(detail, 'Business registration certificate')
            self.assertContains(detail, 'PAN / tax certificate')
            self.assertNotContains(detail, 'Licensing')
            reviewer.post(reverse('accounts:review-detail', args=[profile.pk]), {'decision': 'approve'})
        profile.refresh_from_db()
        self.assertEqual(profile.status, 'approved')

    def test_an_approved_business_owner_is_sent_to_clinic_connect_and_can_register_a_clinic(self):
        profile = self.signup()
        ProfessionalProfile.objects.filter(pk=profile.pk).update(status='approved', completed_step=4, **self.BUSINESS)
        self.assertRedirects(self.client.get(reverse('accounts:welcome')), reverse('accounts:dashboard'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('accounts:dashboard')), reverse('clinics:hub'), fetch_redirect_response=False)
        hub = self.client.get(reverse('clinics:hub'))
        self.assertEqual(hub.status_code, 200)
        self.assertNotContains(hub, reverse('accounts:patients'))  # no patient workspace in the menu
        self.assertNotContains(hub, reverse('accounts:reports'))
        self.assertEqual(self.client.get(reverse('clinics:create')).status_code, 200)
        r = self.client.post(reverse('clinics:create'), {'name': 'Himal Physio Centre', 'phone': '9800000001', 'province': 'Bagmati', 'district': 'Lalitpur', 'slot_minutes': 30})
        self.assertEqual(r.status_code, 302)
        from clinics.models import Clinic
        self.assertEqual(Clinic.objects.get().owner_id, profile.pk)

    def test_health_professionals_are_unchanged(self):
        user, profile = make_professional()
        self.assertFalse(profile.is_business_owner)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        self.assertContains(self.client.get(reverse('accounts:patients')), reverse('accounts:reports'))
