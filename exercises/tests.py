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


class LibraryFixtureTests(TestCase):
    """`manage.py load_exercises` must carry the whole library: pictures, step images, YouTube and hosted video links, Nepali text."""

    def load(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('load_exercises', *args, stdout=out)
        return out.getvalue()

    def test_the_full_live_library_is_loaded_with_links(self):
        output = self.load()
        self.assertEqual(ExerciseMain.objects.filter(discipline='physio').count(), 790)  # the imported catalogue is the physiotherapy library
        self.assertEqual(SubRegion.objects.filter(pk__lt=2000).count(), 30)
        self.assertEqual(ExerciseMain.objects.exclude(youtube_url='').count(), 155)
        self.assertEqual(ExerciseMain.objects.exclude(hosted_video_url='').count(), 26)
        self.assertEqual(ExerciseMain.objects.exclude(exercise_description_nepali='').count(), 221)
        self.assertGreater(ExerciseMain.objects.exclude(exercise_url='').count(), 700)  # main pictures (a few files are not in this repository)
        self.assertGreater(ExerciseStepImage.objects.count(), 1800)
        self.assertIn('155 YouTube links, 26 hosted videos', output)
        pelvic = ExerciseMain.objects.get(exercise_name='Supine Pelvic Tilt')
        self.assertTrue(pelvic.youtube_url.startswith('https://youtu.be/'))
        self.assertTrue(pelvic.hosted_video_url.endswith('.mp4'))
        self.assertTrue(pelvic.cover.startswith('/static/exercises/'))

    def test_every_loaded_picture_exists_on_disk(self):
        """Nothing is shown broken: a path whose file is missing is dropped at load time."""
        from pathlib import Path
        from django.conf import settings
        self.load()
        root = Path(settings.STATICFILES_DIRS[0])
        urls = list(ExerciseMain.objects.exclude(exercise_url='').values_list('exercise_url', flat=True)) + list(ExerciseStepImage.objects.values_list('image_url', flat=True))
        missing = [u for u in urls if not (root / u.removeprefix('/static/')).exists()]
        self.assertEqual(missing, [])

    def test_loading_twice_changes_nothing_and_prune_removes_old_entries(self):
        self.load()
        stray = ExerciseMain.objects.create(sub_region_fk=SubRegion.objects.first(), exercise_name='Old library entry', exercise_type='x', difficulty_level=1, default_sets=3, default_reps=10, hold_time_sec=0)
        self.load()
        physio = ExerciseMain.objects.filter(discipline='physio')
        others = ExerciseMain.objects.exclude(discipline='physio').count()
        self.assertGreater(others, 0)  # the other departments' starter activities
        self.assertEqual(physio.count(), 791)  # a plain load never deletes
        self.assertIn('Pruned 1', self.load('--prune'))
        self.assertEqual(physio.count(), 790)
        self.assertEqual(ExerciseMain.objects.exclude(discipline='physio').count(), others)  # pruning never touches them
        self.assertFalse(ExerciseMain.objects.filter(pk=stray.pk).exists())


class DepartmentLibraryTests(TestCase):
    """Each department has its own exercise library: occupational therapy, speech and behaviour are not mixed with physiotherapy."""
    def setUp(self):
        from accounts.models import Account, Profession
        self.pt_user, self.pt = make_professional('pt-asha')  # physiotherapist
        self.ot_user, self.ot = make_professional('ot-bina')
        Account.objects.filter(pk=self.ot.account_id).update(profession=Profession.objects.get_or_create(name='occupational therapist')[0])
        self.speech_user, self.speech = make_professional('slp-chandra')
        Account.objects.filter(pk=self.speech.account_id).update(profession=Profession.objects.get_or_create(name='speech therapist')[0])
        region = Region.objects.create(region_name='Lower_Limb')
        self.knee = SubRegion.objects.create(region_fk=region, sub_region_name='Knee')
        self.squat = ExerciseMain.objects.create(sub_region_fk=self.knee, exercise_name='Wall Squat', exercise_type='Strengthening', difficulty_level=2, default_sets=3, default_reps=12, hold_time_sec=5)

    def names(self, response):
        return [e.exercise_name for e in response.context['page_obj']]

    def test_each_department_sees_only_its_own_library(self):
        self.client.force_login(self.ot_user)
        ot = self.client.get(reverse('exercises:library'))
        self.assertIn('Bead threading', self.names(ot))
        self.assertNotIn('Wall Squat', self.names(ot))
        self.assertNotIn('Tongue movements', self.names(ot))
        self.assertEqual(ot.context['current'], 'ot')
        self.assertEqual(ot.context['switcher'], [])  # a specific discipline has no switcher
        self.client.force_login(self.speech_user)
        speech = self.client.get(reverse('exercises:library'))
        self.assertIn('Tongue movements', self.names(speech))
        self.assertNotIn('Bead threading', self.names(speech))
        self.client.force_login(self.pt_user)
        pt = self.client.get(reverse('exercises:library'))
        self.assertIn('Wall Squat', self.names(pt))
        self.assertNotIn('Bead threading', self.names(pt))
        self.assertNotIn('Tongue movements', self.names(pt))
        self.assertEqual(pt.context['total'], ExerciseMain.objects.filter(discipline__in=['physio', 'general']).count())
        # regions listed are only the department's own
        self.assertEqual({r.region_name for r in ot.context['regions']}, {'Fine motor and hand function', 'Sensory processing', 'Handwriting and self-care'})

    def test_the_server_refuses_another_departments_exercises(self):
        bead = ExerciseMain.objects.get(exercise_name='Bead threading')
        self.client.force_login(self.pt_user)
        self.assertEqual(self.client.get(reverse('exercises:detail', args=[bead.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('exercises:search'), {'q': 'bead'}).json()['results'], [])
        patient = make_patient(self.pt)
        r = self.client.post(reverse('exercises:prescribe'), data=json.dumps({'patient_id': patient.pk, 'exercises': [{'id': bead.pk}]}), content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Prescription.objects.count(), 0)
        ok = self.client.post(reverse('exercises:prescribe'), data=json.dumps({'patient_id': patient.pk, 'exercises': [{'id': self.squat.pk}, {'id': bead.pk}]}), content_type='application/json')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual([i.exercise_name for i in Prescription.objects.get().exercises.all()], ['Wall Squat'])  # the OT exercise is left out
        self.client.force_login(self.ot_user)
        self.assertEqual(self.client.get(reverse('exercises:detail', args=[bead.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('exercises:detail', args=[self.squat.pk])).status_code, 404)

    def test_general_exercises_are_in_every_library(self):
        shared = ExerciseMain.objects.create(sub_region_fk=self.knee, exercise_name='Deep Breathing', exercise_type='Breathing', difficulty_level=1, default_sets=3, default_reps=5,
                                             hold_time_sec=0, discipline='general')
        for user in (self.pt_user, self.ot_user, self.speech_user):
            self.client.force_login(user)
            self.assertIn('Deep Breathing', self.names(self.client.get(reverse('exercises:library'), {'q': 'Deep'})))

    def test_the_clinic_login_switches_between_the_departments_libraries(self):
        from clinics.login import set_clinic_login
        from clinics.models import Clinic, ClinicSubscription
        clinic = Clinic.objects.create(owner=self.pt, name='Mixed', phone='01555')
        ClinicSubscription.objects.create(professional=self.pt, status='active')
        user = set_clinic_login(clinic, 'mixed-clinic', 'Gr33n!Health-99')
        self.client.force_login(user)
        page = self.client.get(reverse('exercises:library'))
        self.assertEqual(page.context['current'], 'physio')
        self.assertEqual([key for key, _, _ in page.context['switcher']], ['physio', 'ot', 'speech', 'behaviour'])
        speech = self.client.get(reverse('exercises:library'), {'discipline': 'speech'})
        self.assertIn('Tongue movements', self.names(speech))
        self.assertNotIn('Wall Squat', self.names(speech))
        again = self.client.get(reverse('exercises:library'))  # the choice is remembered
        self.assertEqual(again.context['current'], 'speech')

    def test_the_session_form_search_uses_the_persons_own_library(self):
        from accounts.treatments import search_options
        self.assertEqual([r['name'] for r in search_options('tongue', 'exercise', ['speech', 'general'])], ['Tongue movements'])
        self.assertEqual(search_options('tongue', 'exercise', ['physio', 'general']), [])
        self.client.force_login(self.ot_user)
        found = self.client.get(reverse('accounts:treatment-search'), {'q': 'bead', 'kind': 'exercise'}).json()['results']
        self.assertEqual([r['name'] for r in found], ['Bead threading'])
        self.assertEqual(self.client.get(reverse('accounts:treatment-search'), {'q': 'squat', 'kind': 'exercise'}).json()['results'], [])

    def test_starter_sets_exist_and_loading_again_keeps_admin_edits(self):
        from django.core.management import call_command
        for discipline in ('ot', 'speech', 'behaviour'):
            self.assertGreaterEqual(ExerciseMain.objects.filter(discipline=discipline).count(), 6, discipline)
        bead = ExerciseMain.objects.get(exercise_name='Bead threading')
        bead.default_reps = 99
        bead.save()
        before = ExerciseMain.objects.count()
        call_command('load_discipline_library', verbosity=0)
        bead.refresh_from_db()
        self.assertEqual((ExerciseMain.objects.count(), bead.default_reps), (before, 99))
