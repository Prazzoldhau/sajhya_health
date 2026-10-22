import io
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from accounts.models import Patient

from .helpers import make_patient, make_professional, private_storage

NEW = {'name': 'Photo Patient', 'date_of_birth': '1980-05-05', 'gender': 'M', 'phone': '9841234567'}


def image_upload(name='me.png', size=(1600, 1200), fmt='PNG', color='green', mode='RGB'):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f'image/{fmt.lower()}')


class PatientPhotoTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)

    def test_add_patient_with_a_picture_resizes_and_strips_it(self):
        with private_storage():
            r = self.client.post(reverse('accounts:patient-add'), {**NEW, 'photo': image_upload()})
            self.assertRedirects(r, reverse('accounts:patients'))
            patient = Patient.objects.get(name='Photo Patient')
            self.assertTrue(patient.photo.name.startswith(f'patients/{self.profile.pk}/'))
            self.assertTrue(patient.photo.name.endswith('.jpg'))
            with Image.open(patient.photo.path) as stored:
                self.assertEqual(stored.format, 'JPEG')
                self.assertLessEqual(max(stored.size), 640)  # 1600x1200 shrunk
                self.assertEqual(stored.size, (640, 480))  # aspect ratio kept
                self.assertFalse(stored.getexif())  # no metadata left

    def test_patient_without_a_picture_still_works(self):
        self.client.post(reverse('accounts:patient-add'), NEW)
        self.assertFalse(Patient.objects.get(name='Photo Patient').photo)

    def test_non_images_are_rejected(self):
        with private_storage():
            for fake in (SimpleUploadedFile('x.png', b'not an image'), SimpleUploadedFile('x.exe', b'MZ\x90'), SimpleUploadedFile('x.jpg', b'<html></html>')):
                r = self.client.post(reverse('accounts:patient-add'), {**NEW, 'photo': fake})
                self.assertEqual(r.status_code, 200, fake.name)
            self.assertEqual(Patient.objects.filter(name='Photo Patient').count(), 0)

    def test_transparent_png_and_other_formats_are_accepted(self):
        with private_storage():
            for upload in (image_upload('a.png', (50, 50), 'PNG', mode='RGBA', color=(0, 128, 0, 80)), image_upload('b.webp', (50, 50), 'WEBP'), image_upload('c.jpg', (50, 50), 'JPEG')):
                r = self.client.post(reverse('accounts:patient-photo-update', args=[self.patient.pk]), {'photo': upload})
                self.assertEqual(r.status_code, 302, upload.name)
                self.patient.refresh_from_db()
                self.assertTrue(self.patient.photo, upload.name)

    def test_change_replaces_the_file_and_remove_clears_it(self):
        with private_storage():
            update = reverse('accounts:patient-photo-update', args=[self.patient.pk])
            self.client.post(update, {'photo': image_upload()})
            self.patient.refresh_from_db()
            first = self.patient.photo.path
            self.assertTrue(os.path.exists(first))
            self.client.post(update, {'photo': image_upload(color='blue')})
            self.patient.refresh_from_db()
            self.assertNotEqual(self.patient.photo.path, first)
            self.assertFalse(os.path.exists(first))  # the old picture is deleted, not orphaned
            second = self.patient.photo.path
            self.client.post(update, {'remove': '1'})
            self.patient.refresh_from_db()
            self.assertFalse(self.patient.photo)
            self.assertFalse(os.path.exists(second))
            r = self.client.post(update, {})  # nothing chosen
            self.assertEqual(r.status_code, 302)

    def test_picture_is_served_only_to_the_owner(self):
        with private_storage():
            self.client.post(reverse('accounts:patient-photo-update', args=[self.patient.pk]), {'photo': image_upload()})
            self.patient.refresh_from_db()
            url = self.patient.photo_url
            self.assertIn(f'/patients/{self.patient.pk}/photo/', url)
            r = self.client.get(url)
            self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/jpeg'))
            self.assertIn('private', r['Cache-Control'])
            self.assertEqual(self.client_class().get(url).status_code, 302)  # anonymous: sent to login
            stranger, _ = make_professional('stranger')
            other = self.client_class()
            other.force_login(stranger)
            self.assertEqual(other.get(url).status_code, 404)
            self.assertEqual(other.post(reverse('accounts:patient-photo-update', args=[self.patient.pk]), {'remove': '1'}).status_code, 404)
            self.assertEqual(self.client.get(reverse('accounts:patient-photo', args=[make_patient(self.profile, 'No Pic').pk, 'x.jpg'])).status_code, 404)

    def test_avatar_shows_the_picture_everywhere_a_patient_is_listed(self):
        with private_storage():
            self.client.post(reverse('accounts:patient-photo-update', args=[self.patient.pk]), {'photo': image_upload()})
            self.patient.refresh_from_db()
            for url in (reverse('accounts:patients'), reverse('accounts:patient-detail', args=[self.patient.pk])):
                self.assertContains(self.client.get(url), self.patient.photo_url)
        plain = make_patient(self.profile, 'Initials Only')
        self.assertContains(self.client.get(reverse('accounts:patients')), '>IO</span>')  # falls back to initials

    def test_edit_form_can_change_the_picture(self):
        with private_storage():
            data = {'name': 'Sita G', 'date_of_birth': '1990-01-02', 'gender': 'F', 'phone': '9841000000', 'status': 'active', 'photo': image_upload()}
            self.client.post(reverse('accounts:patient-edit', args=[self.patient.pk]), data)
            self.patient.refresh_from_db()
            self.assertTrue(self.patient.photo)
            first = self.patient.photo.path
            self.client.post(reverse('accounts:patient-edit', args=[self.patient.pk]), {**data, 'photo': image_upload(color='red')})
            self.patient.refresh_from_db()
            self.assertNotEqual(self.patient.photo.path, first)
            self.assertFalse(os.path.exists(first))  # editing also cleans up the replaced picture
            kept = self.patient.photo.path
            self.client.post(reverse('accounts:patient-edit', args=[self.patient.pk]), {k: v for k, v in data.items() if k != 'photo'})
            self.patient.refresh_from_db()
            self.assertTrue(os.path.exists(kept))  # saving without choosing a picture keeps the current one
