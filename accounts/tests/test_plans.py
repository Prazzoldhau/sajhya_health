import datetime
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import PlanGoal, PlanMeasure, PlanPhase, PlanReading, TreatmentPlan, Visit

from .helpers import make_patient, make_professional


def payload(**overrides):
    data = {
        'title': 'Shoulder plan', 'diagnosis': 'Impingement', 'icd10_code': 'M75.4', 'onset_date': '2026-08-14',
        'start_date': timezone.localdate().isoformat(), 'precautions': 'No overhead lifting', 'education': 'Posture',
        'goals': [{'text': '170 degrees abduction', 'term': 'long', 'target_date': ''}, {'text': 'Pain < 3/10', 'term': 'short', 'target_date': ''}],
        'measures': [{'name': 'Pain at rest', 'unit': '/10', 'baseline': '6', 'target': '2'}, {'name': 'Abduction', 'unit': '°', 'baseline': '110', 'target': '170'}],
        'phases': [
            {'name': 'Phase 1', 'week_start': 1, 'week_end': 2, 'frequency_per_week': 3, 'frequency_note': 'Clinic', 'goal': '', 'items': [
                {'kind': 'clinic', 'text': 'Passive ROM', 'dosage': ''}, {'kind': 'hep', 'text': 'Pendulum', 'dosage': '3x/day'}, {'kind': 'hep', 'text': '   ', 'dosage': ''}]},
            {'name': 'Phase 2', 'week_start': 3, 'week_end': 4, 'frequency_per_week': 2, 'frequency_note': 'Clinic', 'goal': '', 'items': []},
        ],
        'action': 'draft',
    }
    data.update(overrides)
    return data


class PlanTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)

    def save(self, data, url=None):
        return self.client.post(url or reverse('accounts:plan-create', args=[self.patient.pk]), data=json.dumps(data), content_type='application/json')

    def make_plan(self, **overrides):
        r = self.save(payload(**overrides))
        self.assertEqual(r.status_code, 200, r.content)
        return TreatmentPlan.objects.get()

    def test_builder_pages_load(self):
        self.assertEqual(self.client.get(reverse('accounts:plan-new', args=[self.patient.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:plans')).status_code, 200)

    def test_save_draft_stores_everything_and_skips_blank_items(self):
        plan = self.make_plan()
        self.assertEqual((plan.status, plan.total_weeks, plan.patient), ('draft', 4, self.patient))
        self.assertEqual((plan.phases.count(), plan.measures.count(), plan.goals.count()), (2, 2, 2))
        self.assertEqual(sum(ph.items.count() for ph in plan.phases.all()), 2)  # the blank HEP row was dropped
        self.assertEqual(plan.phases.first().items.get(kind='hep').dosage, '3x/day')

    def test_validation_errors(self):
        url = reverse('accounts:plan-create', args=[self.patient.pk])
        self.assertEqual(self.save(payload(phases=[])).status_code, 400)
        no_name = payload()
        no_name['phases'][0]['name'] = ' '
        self.assertEqual(self.save(no_name).status_code, 400)
        backwards = payload()
        backwards['phases'][0].update(week_start=4, week_end=2)
        self.assertEqual(self.save(backwards).status_code, 400)
        self.assertEqual(self.client.post(url, data='not json', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 404)  # POST only
        self.assertEqual(TreatmentPlan.objects.count(), 0)

    def test_publish_activates_and_starts_first_phase(self):
        plan = self.make_plan(action='publish')
        self.assertEqual(plan.status, 'active')
        self.assertIsNotNone(plan.published_at)
        self.assertEqual([p.status for p in plan.phases.all()], ['current', 'upcoming'])

    def test_editing_keeps_readings_and_goal_state(self):
        plan = self.make_plan(action='publish')
        measure = plan.measures.get(name='Abduction')
        goal = plan.goals.first()
        action = reverse('accounts:plan-action', args=[plan.pk])
        self.client.post(action, {'action': 'log_reading', 'measure': measure.pk, 'value': '140'})
        self.client.post(action, {'action': 'goal_toggle', 'goal': goal.pk})

        from accounts.plans import _state
        state = _state(plan, self.patient)
        state['phases'][0]['name'] = 'Acute'
        state['measures'].append({'id': None, 'name': 'Strength', 'unit': '/5', 'baseline': '3', 'target': '5'})
        self.assertEqual(self.save(state, reverse('accounts:plan-save', args=[plan.pk])).status_code, 200)

        self.assertEqual(plan.measures.count(), 3)
        self.assertEqual(PlanReading.objects.filter(measure=measure).count(), 1)  # history survived
        self.assertTrue(PlanGoal.objects.get(pk=goal.pk).achieved)
        self.assertEqual(plan.phases.first().name, 'Acute')
        self.assertEqual(plan.status, 'active')  # editing a published plan does not demote it

    def test_progress_maths_for_improving_and_decreasing_measures(self):
        plan = self.make_plan()
        pain = plan.measures.get(name='Pain at rest')  # baseline 6 -> target 2 (lower is better)
        rom = plan.measures.get(name='Abduction')      # baseline 110 -> target 170
        self.assertEqual((pain.progress_pct, rom.progress_pct), (0, 0))
        PlanReading.objects.create(measure=pain, value=4)
        PlanReading.objects.create(measure=rom, value=140)
        self.assertEqual((PlanMeasure.objects.get(pk=pain.pk).progress_pct, PlanMeasure.objects.get(pk=rom.pk).progress_pct), (50, 50))
        PlanReading.objects.create(measure=rom, value=500)  # overshoot is capped
        self.assertEqual(PlanMeasure.objects.get(pk=rom.pk).progress_pct, 100)
        no_target = PlanMeasure.objects.create(plan=plan, name='Free text', baseline=5)
        self.assertIsNone(no_target.progress_pct)

    def test_actions_phases_status_and_session_counts(self):
        plan = self.make_plan(action='publish', start_date=(timezone.localdate() - datetime.timedelta(days=8)).isoformat())
        action = reverse('accounts:plan-action', args=[plan.pk])
        phase2 = plan.phases.get(name='Phase 2')
        self.client.post(action, {'action': 'phase_status', 'phase': phase2.pk, 'status': 'current'})
        self.assertEqual(list(plan.phases.values_list('name', 'status')), [('Phase 1', 'upcoming'), ('Phase 2', 'current')])  # only one phase in progress
        self.client.post(action, {'action': 'phase_status', 'phase': phase2.pk, 'status': 'bogus'})
        self.assertEqual(PlanPhase.objects.get(pk=phase2.pk).status, 'current')

        Visit.objects.create(patient=self.patient, therapist='x', date=timezone.localdate())
        page = self.client.get(reverse('accounts:plan-detail', args=[plan.pk]))
        self.assertEqual((page.context['planned_sessions'], page.context['attended_sessions'], page.context['current_week']), (10, 1, 2))

        bad = self.client.post(action, {'action': 'log_reading', 'measure': plan.measures.first().pk, 'value': 'abc'})
        self.assertEqual(bad.status_code, 302)
        self.assertEqual(PlanReading.objects.count(), 0)
        self.client.post(action, {'action': 'complete'})
        self.assertEqual(TreatmentPlan.objects.get().status, 'completed')
        self.client.post(action, {'action': 'reopen'})
        self.assertEqual(TreatmentPlan.objects.get().status, 'active')

    def test_only_drafts_can_be_deleted(self):
        plan = self.make_plan(action='publish')
        self.client.post(reverse('accounts:plan-action', args=[plan.pk]), {'action': 'delete'})
        self.assertTrue(TreatmentPlan.objects.exists())
        TreatmentPlan.objects.update(status='draft')
        self.client.post(reverse('accounts:plan-action', args=[plan.pk]), {'action': 'delete'})
        self.assertFalse(TreatmentPlan.objects.exists())

    def test_plans_are_private_to_their_professional(self):
        plan = self.make_plan()
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        for name in ('plan-detail', 'plan-edit'):
            self.assertEqual(other.get(reverse(f'accounts:{name}', args=[plan.pk])).status_code, 404)
        self.assertEqual(other.post(reverse('accounts:plan-save', args=[plan.pk]), data=json.dumps(payload()), content_type='application/json').status_code, 404)
        self.assertEqual(other.post(reverse('accounts:plan-action', args=[plan.pk]), {'action': 'complete'}).status_code, 404)
        self.assertEqual(other.post(reverse('accounts:plan-create', args=[self.patient.pk]), data=json.dumps(payload()), content_type='application/json').status_code, 404)
        self.assertNotContains(other.get(reverse('accounts:plans')), 'Shoulder plan')
