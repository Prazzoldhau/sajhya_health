import datetime
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.tests.helpers import PASSWORD, make_patient, make_professional

from .models import AssessmentForm, AssessmentResult, AssessmentScale, AssessmentSession, ScaleItem
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
