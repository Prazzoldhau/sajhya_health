import datetime
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.tests.helpers import PASSWORD, make_patient, make_professional

from .models import AssessmentForm, AssessmentResult, AssessmentScale, AssessmentSession, ClinicalForm, ClinicalRecord, ScaleItem
from .scoring import change, parse_options, score_answers


class Base(TestCase):
    def setUp(self):
        call_command('load_scales', verbosity=0)
        self.user, self.profile = make_professional('assess')
        self.client.login(username='assess', password=PASSWORD)
        self.patient = make_patient(self.profile)

    def answers(self, scale, pick):
        """Posted data answering every item of a scale; pick(item) returns the string to send."""
        return {f'i_{i.pk}': pick(i) for i in scale.items.all()}

    def save(self, scales, data, **extra):
        body = {'scales': ','.join(str(s.pk) for s in scales), 'assessed_on': datetime.date.today().isoformat(), 'assessor': 'Asha', **data, **extra}
        return self.client.post(reverse('assessments:fill', args=[self.patient.pk]), body)


class CatalogueTests(Base):
    def test_shipped_scales_are_consistent(self):
        self.assertGreaterEqual(AssessmentScale.objects.count(), 25)
        expected_max = {'barthel': 100, 'fim': 126, 'berg': 56, 'lefs': 80, 'gcs': 15, 'nihss': 42, 'sara': 40, 'odi': 100, 'pbs': 56, 'mrs': 6, 'milestones': 12}
        for code, top in expected_max.items():
            self.assertEqual(AssessmentScale.objects.get(code=code).max_score(), Decimal(top), code)
        self.assertEqual(AssessmentScale.objects.get(code='fim').items.count(), 18)
        for form in AssessmentForm.objects.all():
            self.assertTrue(form.scales.exists(), form.name)
        for scale in AssessmentScale.objects.all():
            for item in scale.items.filter(input_type='choice'):
                self.assertTrue(item.options, f'{scale.code}: {item.label} has no options')

    def test_loading_twice_keeps_admin_edits_unless_update(self):
        scale = AssessmentScale.objects.get(code='barthel')
        scale.name = 'Barthel (edited)'
        scale.save()
        call_command('load_scales', verbosity=0)
        scale.refresh_from_db()
        self.assertEqual(scale.name, 'Barthel (edited)')
        call_command('load_scales', '--update', verbosity=0)
        scale.refresh_from_db()
        self.assertEqual(scale.name, 'Barthel Index of ADL')
        self.assertEqual(scale.items.count(), 10)

    def test_parse_options_ignores_bad_lines(self):
        self.assertEqual([(o['value'], o['label']) for o in parse_options('4|Good\nnonsense\nx|bad\n1.5|Half')], [(Decimal(4), 'Good'), (Decimal('1.5'), 'Half')])


class ScoringTests(Base):
    def test_sum_scale_and_interpretation(self):
        berg = AssessmentScale.objects.get(code='berg')
        result, errors = score_answers(berg, {i.pk: '3' for i in berg.items.all()})
        self.assertEqual((result['score'], result['max_score'], errors), (Decimal(42), Decimal(56), []))

    def test_missing_required_item_is_an_error_and_blank_scale_is_skipped(self):
        barthel = AssessmentScale.objects.get(code='barthel')
        items = list(barthel.items.all())
        result, errors = score_answers(barthel, {items[0].pk: '10'})
        self.assertIsNone(result)
        self.assertIn('every question', errors[0])
        self.assertEqual(score_answers(barthel, {}), (None, []))

    def test_value_must_be_a_listed_option_or_in_range(self):
        barthel = AssessmentScale.objects.get(code='barthel')
        first = barthel.items.first()
        self.assertIn('listed options', score_answers(barthel, {first.pk: '7'})[1][0])
        tug = AssessmentScale.objects.get(code='tug')
        self.assertIn('between', score_answers(tug, {tug.items.get().pk: '999'})[1][0])
        self.assertIn('number', score_answers(tug, {tug.items.get().pk: 'abc'})[1][0])

    def test_percent_scale_allows_a_skipped_section(self):
        odi = AssessmentScale.objects.get(code='odi')
        items = list(odi.items.all())
        raw = {i.pk: '2' for i in items[:9]}  # last section skipped
        result, errors = score_answers(odi, raw)
        self.assertEqual((result['score'], errors), (Decimal('40.0'), []))

    def test_single_scale_uses_the_value_itself(self):
        mas = AssessmentScale.objects.get(code='mas')
        result, _ = score_answers(mas, {mas.items.get().pk: '1.5'})
        self.assertEqual(result['score'], Decimal('1.5'))

    def test_change_respects_direction_and_minimal_important_change(self):
        def res(score, hib, mcid=None):
            return AssessmentResult(score=Decimal(score), higher_is_better=hib, mcid=mcid)
        self.assertEqual(change(res(50, True), res(40, True)), ('Improved +10', 'good'))
        self.assertEqual(change(res(3, False), res(6, False)), ('Improved -3', 'good'))
        self.assertEqual(change(res(44, True, Decimal(9)), res(40, True))[1], 'ok')  # inside the noise band
        self.assertEqual(change(res(30, True), res(40, True))[0], 'Worse -10')


class FlowTests(Base):
    def test_choose_and_fill_pages_render(self):
        self.assertContains(self.client.get(reverse('assessments:choose', args=[self.patient.pk])), 'Stroke / neurology')
        form = AssessmentForm.objects.get(name='Balance and falls risk')
        ids = ','.join(str(s.pk) for s in form.scales.all())
        page = self.client.get(reverse('assessments:fill', args=[self.patient.pk]), {'form': form.pk, 'scales': ids})
        self.assertContains(page, 'Berg Balance Scale')
        self.assertContains(page, 'Timed Up and Go')
        self.assertRedirects(self.client.get(reverse('assessments:fill', args=[self.patient.pk])), reverse('assessments:choose', args=[self.patient.pk]), fetch_redirect_response=False)

    def test_recording_an_assessment_creates_session_results_and_snapshot(self):
        berg, tug = AssessmentScale.objects.get(code='berg'), AssessmentScale.objects.get(code='tug')
        data = {**self.answers(berg, lambda i: '4'), **self.answers(tug, lambda i: '12'), f'n_{tug.pk}': 'with walker'}
        r = self.save([berg, tug, AssessmentScale.objects.get(code='nprs')], data)  # NPRS left blank: skipped
        self.assertRedirects(r, reverse('accounts:patient-detail', args=[self.patient.pk]) + '?tab=assessments', fetch_redirect_response=False)
        session = AssessmentSession.objects.get()
        results = {x.scale_code: x for x in session.results.all()}
        self.assertEqual(set(results), {'berg', 'tug'})
        self.assertEqual((results['berg'].score, results['berg'].interpretation, results['berg'].tone), (Decimal(56), 'Low fall risk', 'good'))
        self.assertEqual((results['tug'].score, results['tug'].interpretation, results['tug'].notes), (Decimal(12), 'Mostly independent', 'with walker'))
        # editing the scale afterwards does not change the recorded history
        berg.name = 'Renamed'
        berg.version = 2
        berg.save()
        ScaleItem.objects.filter(scale=berg).delete()
        results['berg'].refresh_from_db()
        self.assertEqual((results['berg'].scale_name, results['berg'].scale_version, len(results['berg'].answers)), ('Berg Balance Scale', 1, 14))
        self.assertContains(self.client.get(reverse('assessments:detail', args=[session.pk])), 'Sitting to standing')

    def test_errors_keep_the_page_and_save_nothing(self):
        barthel = AssessmentScale.objects.get(code='barthel')
        first = barthel.items.first()
        r = self.save([barthel], {f'i_{first.pk}': '10'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'every question')
        self.assertContains(r, 'checked')  # what was typed is kept
        self.assertEqual(AssessmentSession.objects.count(), 0)
        self.assertContains(self.save([barthel], {}), 'Answer at least one scale')
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self.assertContains(self.save([barthel], self.answers(barthel, lambda i: '0'), assessed_on=tomorrow), 'cannot be in the future')

    def test_patient_tab_shows_progress_between_sessions(self):
        tug = AssessmentScale.objects.get(code='tug')
        for days_ago, seconds in ((14, '25'), (0, '14')):
            day = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
            self.save([tug], self.answers(tug, lambda i, s=seconds: s), assessed_on=day)
        page = self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'assessments'})
        self.assertContains(page, 'Improved -11')
        self.assertContains(page, '2 reading')
        self.assertContains(page, '<polyline')

    def test_retired_scales_disappear_but_history_stays(self):
        tug = AssessmentScale.objects.get(code='tug')
        self.save([tug], self.answers(tug, lambda i: '12'))
        tug.is_active = False
        tug.save()
        self.assertNotContains(self.client.get(reverse('assessments:choose', args=[self.patient.pk])), 'Timed Up and Go (TUG)')
        self.assertContains(self.client.get(reverse('accounts:patient-detail', args=[self.patient.pk]), {'tab': 'assessments'}), 'Timed Up and Go')

    def test_delete_session(self):
        tug = AssessmentScale.objects.get(code='tug')
        self.save([tug], self.answers(tug, lambda i: '12'))
        session = AssessmentSession.objects.get()
        self.client.post(reverse('assessments:delete', args=[session.pk]))
        self.assertEqual(AssessmentSession.objects.count(), 0)


class PrivacyAndGateTests(Base):
    def test_other_professionals_cannot_see_or_change_assessments(self):
        tug = AssessmentScale.objects.get(code='tug')
        self.save([tug], self.answers(tug, lambda i: '12'))
        session = AssessmentSession.objects.get()
        self.client.logout()
        make_professional('stranger')
        self.client.login(username='stranger', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('assessments:detail', args=[session.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('assessments:delete', args=[session.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('assessments:choose', args=[self.patient.pk])).status_code, 404)
        self.assertEqual(AssessmentSession.objects.count(), 1)

    def test_unapproved_professional_is_locked_out(self):
        self.client.logout()
        make_professional('waiting', status='submitted')
        self.client.login(username='waiting', password=PASSWORD)
        self.assertRedirects(self.client.get(reverse('assessments:choose', args=[self.patient.pk])), reverse('accounts:welcome'), fetch_redirect_response=False)


class DisciplineSeparationTests(TestCase):
    """The paediatric occupational therapy assessment belongs to occupational therapy; physiotherapy assessments stay with physiotherapy."""
    def setUp(self):
        from accounts.models import Account, Profession
        call_command('load_scales', verbosity=0)
        self.physio_user, self.physio = make_professional('physio-asha')  # the first profession is physiotherapist
        ot_profession = Profession.objects.get_or_create(name='occupational therapist')[0]
        self.ot_user, self.ot = make_professional('ot-bina')
        Account.objects.filter(pk=self.ot.account_id).update(profession=ot_profession)
        self.ot.refresh_from_db()
        self.form = ClinicalForm.objects.get(code='ot-pediatric')
        self.berg = AssessmentScale.objects.get(code='berg')

    def login(self, user):
        self.client.logout()
        self.client.force_login(user)

    def test_the_paediatric_form_is_shipped_for_occupational_therapy(self):
        self.assertEqual((self.form.discipline, self.form.is_active), ('ot', True))
        titles = [s['title'] for s in self.form.definition['sections']]
        for expected in ('Demographic data', 'Pre-natal history', 'Peri-natal history', 'Developmental history', 'Activities of daily living', 'Problem identification, goals and approaches'):
            self.assertIn(expected, titles)
        self.assertTrue(all(s.discipline == 'physio' for s in AssessmentScale.objects.all()))  # everything that existed stays physiotherapy
        call_command('load_clinical_forms', verbosity=0)  # safe to run again
        self.assertEqual(ClinicalForm.objects.count(), 1)
        self.assertEqual(ClinicalForm.objects.get().version, 1)

    def test_each_discipline_is_offered_only_its_own_assessments(self):
        patient_ot = make_patient(self.ot, 'Child A')
        patient_pt = make_patient(self.physio, 'Adult B')
        self.login(self.ot_user)
        page = self.client.get(reverse('assessments:choose', args=[patient_ot.pk]))
        self.assertContains(page, 'Paediatric occupational therapy assessment')
        self.assertNotContains(page, 'Berg')
        self.assertNotContains(page, 'Barthel')
        self.assertEqual(page.context['switcher'], [])  # a specific discipline has no switcher
        self.login(self.physio_user)
        page = self.client.get(reverse('assessments:choose', args=[patient_pt.pk]))
        self.assertNotContains(page, 'Paediatric occupational therapy assessment')
        self.assertContains(page, 'Berg')
        # and the server refuses what the page does not offer
        self.assertEqual(self.client.get(reverse('assessments:clinical-fill', args=[patient_pt.pk, self.form.pk])).status_code, 404)
        self.login(self.ot_user)
        r = self.client.get(reverse('assessments:fill', args=[patient_ot.pk]), {'scales': str(self.berg.pk)})  # a physiotherapy scale
        self.assertRedirects(r, reverse('assessments:choose', args=[patient_ot.pk]), fetch_redirect_response=False)

    def fill(self, patient, **extra):
        data = {'assessed_on': datetime.date.today().isoformat(), 'assessor': 'Bina', 'f_chief_complaints': 'Poor handwriting', 'f_marriage': 'Non-consanguineous',
                'f_abortion': 'No', 'f_abortion__detail': '', 'f_chronic_disease': ['Diabetes', 'Not a real option'], 'f_chronic_disease__other': 'Asthma',
                'f_delivery': ['Normal'], 'g_motor_dev__0__status': 'Attained', 'g_motor_dev__0__age': '3 months', 'g_motor_dev__3__status': 'Not attained',
                'g_adl__2__level': 'No helper', 'g_in_hand__0__stabilization': ['With stabilization', 'Without stabilization'],
                'g_vestibular__1__status': 'Present', 'g_vestibular__1__comments': 'Hypersensitive', 'f_problems': 'Sensory seeking', **extra}
        return self.client.post(reverse('assessments:clinical-fill', args=[patient.pk, self.form.pk]), data)

    def test_filling_the_paediatric_form_keeps_and_shows_only_what_was_answered(self):
        patient = make_patient(self.ot, 'Child A', diagnosis='Autism spectrum disorder')
        self.login(self.ot_user)
        page = self.client.get(reverse('assessments:clinical-fill', args=[patient.pk, self.form.pk]))
        self.assertContains(page, 'value="Child A"')  # filled from the patient record
        self.assertContains(page, 'Autism spectrum disorder')
        r = self.fill(patient)
        record = ClinicalRecord.objects.get()
        self.assertRedirects(r, reverse('assessments:clinical-detail', args=[record.pk]), fetch_redirect_response=False)
        self.assertEqual((record.discipline, record.form_code, record.assessor), ('ot', 'ot-pediatric', 'Bina'))
        a = record.answers
        self.assertEqual(a['marriage'], 'Non-consanguineous')
        self.assertEqual(a['chronic_disease'], {'values': ['Diabetes'], 'other': 'Asthma'})  # an option that does not exist is dropped
        self.assertEqual(a['abortion'], {'value': 'No', 'detail': ''})
        self.assertEqual(a['motor_dev'], [{'row': 'Head control', 'status': 'Attained', 'age': '3 months'}, {'row': 'Sitting', 'status': 'Not attained'}])
        self.assertEqual(a['in_hand'], [{'row': 'Translation: finger to palm', 'stabilization': ['With stabilization', 'Without stabilization']}])
        self.assertEqual(a['vestibular'][0]['comments'], 'Hypersensitive')
        detail = self.client.get(reverse('assessments:clinical-detail', args=[record.pk]))
        self.assertContains(detail, 'Poor handwriting')
        self.assertContains(detail, 'Head control')
        self.assertContains(detail, 'Asthma')
        self.assertNotContains(detail, 'Birth weight')  # not answered: not shown
        self.assertEqual(record.definition, self.form.definition)  # the questions it was filled with are kept
        tab = self.client.get(reverse('accounts:patient-detail', args=[patient.pk]), {'tab': 'assessments'})
        self.assertContains(tab, 'Paediatric occupational therapy assessment')

    def test_a_blank_or_future_dated_form_is_refused(self):
        patient = make_patient(self.ot, 'Child A')
        self.login(self.ot_user)
        blank = self.client.post(reverse('assessments:clinical-fill', args=[patient.pk, self.form.pk]), {'assessed_on': datetime.date.today().isoformat(), 'f_name': 'Child A', 'f_age': '6'})
        self.assertEqual(blank.status_code, 200)  # only the boxes filled from the record: nothing answered
        self.assertContains(blank, 'Fill in at least one answer')
        future = self.fill(patient, assessed_on=(datetime.date.today() + datetime.timedelta(days=2)).isoformat())
        self.assertContains(future, 'cannot be in the future')
        self.assertEqual(ClinicalRecord.objects.count(), 0)

    def test_one_discipline_never_sees_the_others_records(self):
        child = make_patient(self.ot, 'Child A')
        self.login(self.ot_user)
        self.fill(child)
        record = ClinicalRecord.objects.get()
        # a physiotherapy assessment on the same patient
        session = AssessmentSession.objects.create(patient=child, form_name='Berg', discipline='physio', assessor='Asha')
        # the clinic: both therapists belong to it, and the patient is the clinic's
        from clinics.models import Clinic, ClinicMember
        clinic = Clinic.objects.create(owner=self.ot, name='Shared', phone='01555')
        from clinics.models import ClinicSubscription
        ClinicSubscription.objects.create(professional=self.ot, status='active')
        child.clinic = clinic
        child.save()
        child.assigned.add(ClinicMember.objects.create(clinic=clinic, physio=self.physio, role='physio', status='active'))
        self.login(self.physio_user)
        self.assertEqual(self.client.get(reverse('assessments:clinical-detail', args=[record.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('assessments:clinical-delete', args=[record.pk])).status_code, 404)
        tab = self.client.get(reverse('accounts:patient-detail', args=[child.pk]), {'tab': 'assessments'})
        self.assertNotContains(tab, 'Paediatric occupational therapy assessment')
        self.assertContains(tab, 'Berg')
        self.assertEqual(self.client.get(reverse('assessments:detail', args=[session.pk])).status_code, 200)
        self.login(self.ot_user)
        tab = self.client.get(reverse('accounts:patient-detail', args=[child.pk]), {'tab': 'assessments'})
        self.assertContains(tab, 'Paediatric occupational therapy assessment')
        self.assertNotContains(tab, 'Berg')  # the physiotherapist's assessment is not in the OT view
        self.assertEqual(self.client.get(reverse('assessments:detail', args=[session.pk])).status_code, 404)

    def test_scale_assessments_are_filed_under_the_discipline_that_made_them(self):
        patient = make_patient(self.physio, 'Adult B')
        self.login(self.physio_user)
        items = {f'i_{i.pk}': '0' for i in self.berg.items.all()}
        self.client.post(reverse('assessments:fill', args=[patient.pk]), {'scales': str(self.berg.pk), 'assessed_on': datetime.date.today().isoformat(), **items})
        self.assertEqual(AssessmentSession.objects.get().discipline, 'physio')

    def test_the_clinic_login_works_across_disciplines_with_a_switcher(self):
        from clinics.models import Clinic
        from clinics.login import set_clinic_login
        clinic = Clinic.objects.create(owner=self.physio, name='Mixed', phone='01555')
        from clinics.models import ClinicSubscription
        ClinicSubscription.objects.create(professional=self.physio, status='active')
        user = set_clinic_login(clinic, 'mixed-clinic', PASSWORD)
        workspace = clinic.workspace
        patient = make_patient(workspace, 'Child C')
        self.login(user)
        page = self.client.get(reverse('assessments:choose', args=[patient.pk]))
        self.assertEqual(page.context['current'], 'physio')
        self.assertEqual([key for key, _, _ in page.context['switcher']], ['physio', 'ot'])
        ot = self.client.get(reverse('assessments:choose', args=[patient.pk]), {'discipline': 'ot'})
        self.assertContains(ot, 'Paediatric occupational therapy assessment')
        self.assertNotContains(ot, 'Berg')
        self.client.post(reverse('assessments:clinical-fill', args=[patient.pk, self.form.pk]), {'assessed_on': datetime.date.today().isoformat(), 'f_chief_complaints': 'x'})
        tab = self.client.get(reverse('accounts:patient-detail', args=[patient.pk]), {'tab': 'assessments'})
        self.assertContains(tab, 'Occupational therapy')  # with a label saying which discipline
