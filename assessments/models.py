"""Assessment scales, forms (bundles of scales) and the results recorded for patients.

Everything about a scale lives in the database, so scales can be added, changed or retired in the Django admin (or by
re-running `manage.py load_scales` with an edited fixtures/scales.json) without touching code. Results keep a *snapshot*
of what was asked and answered, so editing or removing a scale never rewrites a patient's history.
See docs/ASSESSMENTS.md.
"""
from django.db import models
from django.utils import timezone

from .disciplines import DISCIPLINE_CHOICES


class AssessmentScale(models.Model):
    SUM, PERCENT, SINGLE = 'sum', 'percent', 'single'
    SCORING_CHOICES = [
        (SUM, 'Add up all item scores'),
        (PERCENT, 'Percentage of the maximum for the items answered (e.g. Oswestry)'),
        (SINGLE, 'One item - its value is the score (grades, timed tests, VAS)'),
    ]
    CATEGORY_CHOICES = [
        ('functional', 'Functional / ADL'), ('balance', 'Balance & falls'), ('coordination', 'Coordination'),
        ('neuro', 'Neurology'), ('ortho', 'Orthopaedic / MSK'), ('pedia', 'Paediatric'), ('pain', 'Pain'),
        ('cardio', 'Endurance / cardiopulmonary'), ('other', 'Other'),
    ]

    code = models.SlugField(max_length=40, unique=True, help_text='Short stable identifier, e.g. "berg". Never change it once results exist.')
    name = models.CharField(max_length=150)
    abbreviation = models.CharField(max_length=20, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    discipline = models.CharField(max_length=10, choices=DISCIPLINE_CHOICES, default='physio',
                                  help_text='Who sees it: physiotherapists see physiotherapy and general ones, occupational therapists occupational therapy and general ones, and so on.')
    description = models.TextField(blank=True, help_text='What it measures and when to use it.')
    instructions = models.TextField(blank=True, help_text='How to administer / score. Shown above the questions.')
    scoring = models.CharField(max_length=10, choices=SCORING_CHOICES, default=SUM)
    unit = models.CharField(max_length=20, blank=True, help_text='e.g. "points", "seconds", "m", "%"')
    higher_is_better = models.BooleanField(default=True, help_text='Untick for scales where a LOWER score is better (pain, disability, time).')
    mcid = models.DecimalField('Minimal important change', max_digits=7, decimal_places=2, null=True, blank=True,
                               help_text='Smallest change that matters clinically; used to label progress. Leave blank if unknown.')
    reference = models.CharField(max_length=255, blank=True, help_text='Source / citation / licence note.')
    version = models.PositiveSmallIntegerField(default=1, help_text='Raise this when you change the questions or scoring.')
    is_active = models.BooleanField(default=True, help_text='Untick to retire a scale: hidden from new assessments, history kept.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name

    @property
    def short_name(self):
        return self.abbreviation or self.name

    def max_score(self):
        """Highest possible score (None when open-ended, e.g. a timed test with no maximum)."""
        from .scoring import max_score
        return max_score(self)


class ScaleItem(models.Model):
    CHOICE, NUMBER = 'choice', 'number'
    TYPE_CHOICES = [(CHOICE, 'Pick one option'), (NUMBER, 'Enter a number')]

    scale = models.ForeignKey(AssessmentScale, on_delete=models.CASCADE, related_name='items')
    order = models.PositiveSmallIntegerField(default=0)
    code = models.SlugField(max_length=40, help_text='Stable identifier within the scale, e.g. "sit-to-stand".')
    section = models.CharField(max_length=100, blank=True, help_text='Optional heading shown above this question.')
    label = models.CharField(max_length=250)
    help_text = models.CharField(max_length=500, blank=True)
    input_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=CHOICE)
    options_text = models.TextField(blank=True, help_text='One option per line as  score|label  e.g.  4|Able to stand independently. Used for "Pick one option".')
    min_value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text='Numbers only.')
    max_value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text='Numbers only.')
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ['scale', 'order', 'id']
        unique_together = [('scale', 'code')]

    def __str__(self):
        return f'{self.scale.short_name}: {self.label}'

    @property
    def options(self):
        from .scoring import parse_options
        return parse_options(self.options_text)


class ScoreBand(models.Model):
    """Interpretation of a score range, e.g. 41-56 'Low fall risk'."""
    TONES = [('good', 'Good'), ('ok', 'Fair'), ('warn', 'Concern'), ('bad', 'Poor')]
    scale = models.ForeignKey(AssessmentScale, on_delete=models.CASCADE, related_name='bands')
    min_score = models.DecimalField(max_digits=8, decimal_places=2)
    max_score = models.DecimalField(max_digits=8, decimal_places=2)
    label = models.CharField(max_length=150)
    tone = models.CharField(max_length=5, choices=TONES, default='ok')

    class Meta:
        ordering = ['scale', 'min_score']

    def __str__(self):
        return f'{self.scale.short_name} {self.min_score}-{self.max_score}: {self.label}'


class AssessmentForm(models.Model):
    """A ready-made bundle of scales, e.g. "Stroke - initial assessment". Choosing a form pre-selects its scales."""
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=AssessmentScale.CATEGORY_CHOICES, default='other')
    discipline = models.CharField(max_length=10, choices=DISCIPLINE_CHOICES, default='physio')
    description = models.CharField(max_length=300, blank=True)
    scales = models.ManyToManyField(AssessmentScale, through='FormScale', related_name='forms')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name


class FormScale(models.Model):
    form = models.ForeignKey(AssessmentForm, on_delete=models.CASCADE)
    scale = models.ForeignKey(AssessmentScale, on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        unique_together = [('form', 'scale')]


class AssessmentSession(models.Model):
    """One sitting: a date, an assessor and one or more scale results for one patient."""
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='assessment_sessions')
    form = models.ForeignKey(AssessmentForm, null=True, blank=True, on_delete=models.SET_NULL, related_name='sessions')
    form_name = models.CharField(max_length=150, blank=True)
    discipline = models.CharField(max_length=10, choices=DISCIPLINE_CHOICES, default='physio')
    assessed_on = models.DateField(default=timezone.localdate)
    assessor = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-assessed_on', '-id']

    def __str__(self):
        return f'{self.patient} - {self.form_name or "Assessment"} - {self.assessed_on}'


class AssessmentResult(models.Model):
    session = models.ForeignKey(AssessmentSession, on_delete=models.CASCADE, related_name='results')
    scale = models.ForeignKey(AssessmentScale, null=True, on_delete=models.SET_NULL, related_name='results')
    # snapshot, so the record still reads correctly if the scale is later edited or retired
    scale_code = models.CharField(max_length=40)
    scale_name = models.CharField(max_length=150)
    scale_version = models.PositiveSmallIntegerField(default=1)
    unit = models.CharField(max_length=20, blank=True)
    higher_is_better = models.BooleanField(default=True)
    mcid = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    answers = models.JSONField(default=list, help_text='[{code, label, value, value_label}] as answered')
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    interpretation = models.CharField(max_length=150, blank=True)
    tone = models.CharField(max_length=5, blank=True)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.scale_name}: {self.score}'

    @property
    def score_display(self):
        if self.score is None:
            return '-'
        text = f'{self.score.normalize():f}'
        if self.max_score is not None and self.unit != '%':
            text += f' / {self.max_score.normalize():f}'
        return f'{text} {self.unit}'.strip() if self.unit and self.unit != 'points' else text


class ClinicalForm(models.Model):
    """A history-and-examination style form (sections of text, tick boxes and tables) such as the paediatric occupational therapy assessment.
    The questions live in `definition`; see assessments/clinical_forms.py for the format."""
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=150)
    discipline = models.CharField(max_length=10, choices=DISCIPLINE_CHOICES, default='ot')
    description = models.CharField(max_length=300, blank=True)
    definition = models.JSONField(default=dict)
    version = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True, help_text='Untick to retire a form: hidden from new assessments, history kept.')

    class Meta:
        ordering = ['discipline', 'name']

    def __str__(self):
        return self.name


class ClinicalRecord(models.Model):
    """One filled-in clinical form for a patient. It keeps a copy of the questions it was filled with, so it still reads correctly if the form is edited later."""
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='clinical_records')
    form = models.ForeignKey(ClinicalForm, null=True, blank=True, on_delete=models.SET_NULL, related_name='records')
    form_code = models.CharField(max_length=40, blank=True)
    form_name = models.CharField(max_length=150)
    form_version = models.PositiveSmallIntegerField(default=1)
    discipline = models.CharField(max_length=10, choices=DISCIPLINE_CHOICES, default='ot')
    definition = models.JSONField(default=dict)
    answers = models.JSONField(default=dict)
    assessed_on = models.DateField(default=timezone.localdate)
    assessor = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-assessed_on', '-id']

    def __str__(self):
        return f'{self.patient} - {self.form_name} - {self.assessed_on}'
