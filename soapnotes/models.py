"""SOAP notes written for physiotherapy: Subjective, Objective, Assessment, Plan - with baseline metrics and clinical goals in
the same format as a treatment plan, so a plan can be started from a note. See docs/SOAP_NOTES.md.

A note is a draft until it is finalised; a finalised note is locked and can only receive dated addenda (the usual
medico-legal practice), so the record of what was found and decided on the day is never silently rewritten.
"""
from django.db import models
from django.utils import timezone


class SoapNote(models.Model):
    INITIAL, FOLLOW_UP, REASSESSMENT, DISCHARGE = 'initial', 'follow_up', 'reassessment', 'discharge'
    TYPE_CHOICES = [(INITIAL, 'Initial assessment'), (FOLLOW_UP, 'Follow-up / treatment session'), (REASSESSMENT, 'Re-assessment'), (DISCHARGE, 'Discharge summary')]
    DRAFT, FINAL = 'draft', 'final'
    STATUS_CHOICES = [(DRAFT, 'Draft'), (FINAL, 'Final (locked)')]
    PROGNOSIS_CHOICES = [('', 'Not stated'), ('excellent', 'Excellent'), ('good', 'Good'), ('fair', 'Fair'), ('poor', 'Poor'), ('guarded', 'Guarded')]
    IRRITABILITY_CHOICES = [('', 'Not stated'), ('low', 'Low'), ('moderate', 'Moderate'), ('high', 'High')]
    STAGE_CHOICES = [('', 'Not stated'), ('acute', 'Acute'), ('subacute', 'Sub-acute'), ('chronic', 'Chronic'), ('post_op', 'Post-operative')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='soap_notes')
    author = models.ForeignKey('accounts.ProfessionalProfile', null=True, on_delete=models.SET_NULL, related_name='+')
    author_name = models.CharField(max_length=200)
    note_date = models.DateField(default=timezone.localdate)
    note_type = models.CharField(max_length=15, choices=TYPE_CHOICES, default=INITIAL)
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default=DRAFT)
    finalized_at = models.DateTimeField(null=True, blank=True)
    visit = models.ForeignKey('accounts.Visit', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ---- S: subjective
    chief_complaint = models.CharField(max_length=250, blank=True)
    history = models.TextField('History of present condition', blank=True)
    mechanism = models.CharField('Onset / mechanism of injury', max_length=250, blank=True)
    pain_now = models.PositiveSmallIntegerField(null=True, blank=True)
    pain_best = models.PositiveSmallIntegerField(null=True, blank=True)
    pain_worst = models.PositiveSmallIntegerField(null=True, blank=True)
    pain_location = models.CharField(max_length=200, blank=True)
    pain_character = models.CharField(max_length=150, blank=True)
    aggravating = models.CharField('Aggravating factors', max_length=300, blank=True)
    easing = models.CharField('Easing factors', max_length=300, blank=True)
    pattern_24h = models.CharField('24-hour pattern', max_length=300, blank=True)
    red_flags = models.JSONField(default=list, blank=True)
    medical_history = models.TextField('Medical history, medications, investigations', blank=True)
    functional_limits = models.TextField('Functional limitations (ADL, work, sport)', blank=True)
    patient_goals = models.TextField("Patient's goals and expectations", blank=True)

    # ---- O: objective
    observation = models.TextField('Observation and posture', blank=True)
    palpation = models.TextField(blank=True)
    vitals = models.CharField(max_length=150, blank=True)
    rom = models.JSONField(default=list, blank=True)            # [{movement, side, active, passive, pain, note}]
    strength = models.JSONField(default=list, blank=True)       # [{muscle, side, grade}]
    neuro = models.TextField('Neurological screen (sensation, reflexes, myotomes)', blank=True)
    special_tests = models.JSONField(default=list, blank=True)  # [{name, result, note}]
    gait_function = models.TextField('Gait, balance and functional tests', blank=True)

    # ---- A: assessment
    impression = models.TextField('Clinical impression / physiotherapy diagnosis', blank=True)
    icd10_code = models.CharField('ICD-10 code', max_length=20, blank=True)
    problem_list = models.TextField(blank=True)
    contributing = models.TextField('Contributing factors', blank=True)
    stage = models.CharField(max_length=10, choices=STAGE_CHOICES, blank=True)
    irritability = models.CharField(max_length=10, choices=IRRITABILITY_CHOICES, blank=True)
    prognosis = models.CharField(max_length=10, choices=PROGNOSIS_CHOICES, blank=True)

    # ---- P: plan  (measures and goals use the same shape as the treatment plan builder)
    treatment_today = models.TextField('Treatment given today', blank=True)
    measures = models.JSONField(default=list, blank=True)       # [{name, unit, baseline, target}]
    goals = models.JSONField(default=list, blank=True)          # [{text, term, target_date}]
    frequency_per_week = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    hep = models.TextField('Home exercise programme', blank=True)
    education = models.TextField('Patient education and advice', blank=True)
    precautions = models.TextField('Precautions / contraindications', blank=True)
    referral = models.CharField('Referral / follow-up with other professionals', max_length=300, blank=True)
    next_review = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-note_date', '-id']

    def __str__(self):
        return f'{self.patient} - {self.get_note_type_display()} - {self.note_date}'

    @property
    def is_final(self):
        return self.status == self.FINAL

    @property
    def headline(self):
        return self.chief_complaint or self.impression[:80] or 'SOAP note'


class SoapAddendum(models.Model):
    """A dated addition to a finalised note."""
    note = models.ForeignKey(SoapNote, on_delete=models.CASCADE, related_name='addenda')
    text = models.TextField()
    author_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
