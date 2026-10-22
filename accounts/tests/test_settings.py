from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import ClinicalFocus, ServiceType
from .helpers import PASSWORD, make_professional


class SettingsTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional('setpro', title='PT')
        self.client.login(username='setpro', password=PASSWORD)
        self.url = reverse('accounts:settings')

    def test_all_tabs_render(self):
        for tab in ('profile', 'practice', 'account', 'bogus'):
            self.assertEqual(self.client.get(self.url, {'tab': tab}).status_code, 200)

    def test_practice_settings_save_and_drive_appointment_default(self):
        r = self.client.post(self.url, {'tab': 'practice', 'practice_name': 'Rai Physio', 'practice_address': 'Lalitpur', 'practice_phone': '015550000',
                                        'facility_code': 'HF-123', 'default_session_minutes': '45'})
        self.assertRedirects(r, self.url + '?tab=practice', fetch_redirect_response=False)
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.practice_name, self.profile.facility_code, self.profile.default_session_minutes), ('Rai Physio', 'HF-123', 45))
        page = self.client.get(reverse('accounts:appointments'))
        self.assertEqual(page.context['duration_default'], 45)
        report = self.client.get(reverse('accounts:reports'))
        self.assertContains(report, 'Rai Physio - Facility code HF-123')

    def test_profile_tab_changes_mobile_but_never_name_title_or_licence(self):
        focus, service = ClinicalFocus.objects.create(name='Sports'), ServiceType.objects.create(name='Home visit')
        self.client.post(self.url, {'tab': 'profile', 'mobile': '9811111111', 'years_experience': '7', 'focus_areas': [focus.pk], 'services': [service.pk],
                                    'first_name': 'Hacked', 'title': 'Dr', 'license_number': 'FAKE', 'status': 'rejected'})
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.mobile, self.profile.years_experience), ('9811111111', 7))
        self.assertEqual((self.profile.first_name, self.profile.title, self.profile.license_number, self.profile.status), ('Asha', 'PT', '', 'approved'))

    def test_email_must_be_unique_and_saves(self):
        User.objects.create_user('other', 'taken@example.com', 'x')
        self.client.post(self.url, {'tab': 'account', 'email': 'TAKEN@example.com'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'setpro@example.com')
        self.client.post(self.url, {'tab': 'account', 'email': 'new@example.com'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')

    def test_unapproved_professional_cannot_open_settings(self):
        self.client.logout()
        make_professional('waiting', status='submitted')
        self.client.login(username='waiting', password=PASSWORD)
        self.assertRedirects(self.client.get(self.url), reverse('accounts:welcome'), fetch_redirect_response=False)
