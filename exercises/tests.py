import json

from django.test import TestCase
from django.urls import reverse

from accounts.tests.helpers import make_patient, make_professional

from .models import ExerciseMain, ExerciseStepImage, Prescription, PrescriptionExercise, Region, SubRegion


class LibraryBase(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        region = Region.objects.create(region_name='Lower_Limb')
        self.knee = SubRegion.objects.create(region_fk=region, sub_region_name='Knee')
        self.ankle = SubRegion.objects.create(region_fk=region, sub_region_name='Ankle')
        self.squat = ExerciseMain.objects.create(sub_region_fk=self.knee, exercise_name='Wall Squat', exercise_type='Strengthening', difficulty_level=2,
                                                 default_sets=3, default_reps=12, hold_time_sec=5, exercise_description='Lean on the wall', exercise_url='/static/exercises/knee/squat.png')
        self.raise_ = ExerciseMain.objects.create(sub_region_fk=self.ankle, exercise_name='Calf Raise', exercise_type='Isometric', difficulty_level=1,
                                                  default_sets=2, default_reps=15, hold_time_sec=0)
        ExerciseStepImage.objects.create(exercise=self.raise_, order=2, image_url='/static/exercises/ankle/2.png')
        ExerciseStepImage.objects.create(exercise=self.raise_, order=1, image_url='/static/exercises/ankle/1 (1).png')

    def prescribe(self, rows, **extra):
        data = {'patient_id': self.patient.pk, 'condition_label': 'Knee', 'exercises': rows, **extra}
        return self.client.post(reverse('exercises:prescribe'), data=json.dumps(data), content_type='application/json')


class LibraryBrowseTests(LibraryBase):
    def names(self, **params):
        return [e.exercise_name for e in self.client.get(reverse('exercises:library'), params).context['page_obj']]

    def test_filters_and_search(self):
        self.assertEqual(self.names(), ['Calf Raise', 'Wall Squat'])
        self.assertEqual(self.names(sub=self.knee.pk), ['Wall Squat'])
        self.assertEqual(self.names(region=self.ankle.region_fk_id), ['Calf Raise', 'Wall Squat'])
        self.assertEqual(self.names(q='squat'), ['Wall Squat'])
        self.assertEqual(self.names(q='wall'), ['Wall Squat'])  # also matches the description
        self.assertEqual(self.names(type='Isometric'), ['Calf Raise'])
        self.assertEqual(self.names(level=2), ['Wall Squat'])
        self.assertEqual(self.names(q='nothing like this'), [])
        self.assertEqual(self.client.get(reverse('exercises:library'), {'page': 999}).status_code, 200)

    def test_images_use_steps_in_order_else_the_single_image(self):
        self.assertEqual(self.raise_.images, ['/static/exercises/ankle/1%20%281%29.png', '/static/exercises/ankle/2.png'])
        self.assertEqual(self.squat.images, ['/static/exercises/knee/squat.png'])
        self.assertEqual(self.squat.cover, '/static/exercises/knee/squat.png')

    def test_detail_json_and_search(self):
        data = self.client.get(reverse('exercises:detail', args=[self.squat.pk])).json()
        self.assertEqual((data['name'], data['dose'], data['level_label']), ('Wall Squat', '3 sets × 12 reps, hold 5s', 'Intermediate'))
        self.assertEqual(self.client.get(reverse('exercises:detail', args=[9999])).status_code, 404)
        found = self.client.get(reverse('exercises:search'), {'q': 'calf'}).json()['results']
        self.assertEqual([r['name'] for r in found], ['Calf Raise'])
        self.assertEqual(self.client.get(reverse('exercises:search'), {'q': 'c'}).json()['results'], [])

    def test_library_requires_a_logged_in_professional(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('exercises:library')).status_code, 302)

    def test_patient_context_is_private(self):
        other_user, other_profile = make_professional('other')
        theirs = make_patient(other_profile, 'Theirs')
        self.assertEqual(self.client.get(reverse('exercises:library'), {'patient': theirs.pk}).status_code, 404)
        page = self.client.get(reverse('exercises:library'), {'patient': self.patient.pk})
        self.assertEqual(page.context['patient'], self.patient)


class PrescribeTests(LibraryBase):
    def test_validation(self):
        self.assertEqual(self.prescribe([]).status_code, 400)
        self.assertEqual(self.prescribe([{'id': 999999}]).status_code, 400)
        no_patient = self.client.post(reverse('exercises:prescribe'), data=json.dumps({'exercises': [{'id': self.squat.pk}]}), content_type='application/json')
        self.assertEqual(no_patient.status_code, 400)
        self.assertEqual(self.client.post(reverse('exercises:prescribe'), data='garbage', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get(reverse('exercises:prescribe')).status_code, 404)
        self.assertEqual(Prescription.objects.count(), 0)

    def test_cannot_prescribe_to_someone_elses_patient(self):
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        r = other.post(reverse('exercises:prescribe'), data=json.dumps({'patient_id': self.patient.pk, 'exercises': [{'id': self.squat.pk}]}), content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Prescription.objects.count(), 0)

    def test_prescription_uses_defaults_overrides_and_clamps_values(self):
        r = self.prescribe([{'id': self.squat.pk}, {'id': self.raise_.pk, 'sets': 4, 'reps': 'abc', 'hold': 99999, 'morning': True, 'evening': True}])
        self.assertEqual(r.status_code, 200)
        self.assertIn('tab=exercises', r.json()['redirect'])
        rx = Prescription.objects.get()
        first, second = rx.exercises.all()
        self.assertEqual((first.sets, first.reps, first.hold_time_sec), (3, 12, 5))
        self.assertEqual((second.sets, second.reps, second.hold_time_sec), (4, 15, 600))  # bad reps -> default, hold capped
        self.assertEqual(second.schedule_label, 'Morning · Evening')
        self.assertEqual((rx.condition_label, rx.professional), ('Knee', self.profile))

    def test_new_prescription_supersedes_the_old_and_append_adds_to_it(self):
        self.prescribe([{'id': self.squat.pk}])
        first = Prescription.objects.get()
        self.prescribe([{'id': self.raise_.pk}], prescription_id=first.pk)
        self.assertEqual((Prescription.objects.count(), first.exercises.count()), (1, 2))
        self.prescribe([{'id': self.squat.pk}])
        first.refresh_from_db()
        self.assertEqual(first.status, 'superseded')
        self.assertEqual(Prescription.objects.filter(status='active').count(), 1)

    def test_actions_toggle_remove_complete_cancel_reassign(self):
        self.prescribe([{'id': self.squat.pk}, {'id': self.raise_.pk}])
        rx = Prescription.objects.get()
        item = rx.exercises.first()
        act = lambda **d: self.client.post(reverse('exercises:prescription-action', args=[rx.pk]), d)
        act(action='toggle', item=item.pk)
        item.refresh_from_db()
        self.assertTrue(item.is_completed)
        self.assertEqual(rx.completion_percentage, 50)
        act(action='toggle', item=item.pk)
        item.refresh_from_db()
        self.assertFalse(item.is_completed)
        act(action='remove', item=item.pk)
        self.assertEqual(rx.exercises.count(), 1)
        act(action='complete')
        rx.refresh_from_db()
        self.assertEqual(rx.status, 'completed')
        act(action='reassign')
        self.assertEqual(Prescription.objects.count(), 2)
        self.assertEqual(Prescription.objects.get(status='active').exercises.count(), 1)

    def test_prescription_actions_are_private(self):
        self.prescribe([{'id': self.squat.pk}])
        rx = Prescription.objects.get()
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        self.assertEqual(other.post(reverse('exercises:prescription-action', args=[rx.pk]), {'action': 'cancel'}).status_code, 404)
        rx.refresh_from_db()
        self.assertEqual(rx.status, 'active')

    def test_exercises_tab_lists_prescriptions(self):
        self.prescribe([{'id': self.squat.pk}])
        page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'exercises'})
        self.assertContains(page, 'Wall Squat')

    def test_snapshot_survives_library_deletion(self):
        self.prescribe([{'id': self.squat.pk}])
        self.squat.delete()
        item = PrescriptionExercise.objects.get()
        self.assertEqual((item.exercise_name, item.exercise), ('Wall Squat', None))


class ThumbnailTests(LibraryBase):
    """Small exercise pictures help a physiotherapist recognise exercises at a glance."""

    def setUp(self):
        super().setUp()
        rx = Prescription.objects.create(patient=self.patient, professional=self.profile, condition_label='Knee')
        PrescriptionExercise.objects.create(prescription=rx, exercise=self.squat, exercise_name='Wall Squat')
        PrescriptionExercise.objects.create(prescription=rx, exercise=self.raise_, exercise_name='Calf Raise')
        PrescriptionExercise.objects.create(prescription=rx, exercise=None, exercise_name='Removed Move')
        self.rx = rx

    def test_search_results_carry_the_cover(self):
        results = {r['name']: r['cover'] for r in self.client.get(reverse('exercises:search'), {'q': 'ra'}).json()['results']}
        self.assertEqual(results['Calf Raise'], '/static/exercises/ankle/1%20%281%29.png')

    def test_prescribed_exercises_show_thumbnails_with_a_letter_fallback(self):
        page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'exercises'})
        self.assertContains(page, 'class="ex-thumb" src="/static/exercises/knee/squat.png"')
        self.assertContains(page, 'class="ex-thumb" src="/static/exercises/ankle/1%20%281%29.png"')  # first step image
        self.assertContains(page, '<span class="ex-thumb ex-thumb-blank" title="Removed Move">R</span>')

    def test_rehab_summary_and_library_use_them_too(self):
        profile_page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'profile', 'section': 'rehab'})
        self.assertContains(profile_page, 'ex-thumb')
        self.assertContains(self.client.get(reverse('exercises:library')), 'data-cover="/static/exercises/knee/squat.png"')
