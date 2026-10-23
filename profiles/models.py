"""Clinical profile sections for a patient: standing info, medicine, nursing, surgical aids, therapies, lab tests.

The physiotherapy part of the rehab profile is NOT stored here - it is read from what the professional already records
every day (visits, treatment plans, exercise prescriptions); see profiles/rehab.py.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import get_private_storage


def _lab_report_path(instance, filename):
    import uuid
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'pdf'
    return f'lab_reports/{instance.patient.professional_id}/{uuid.uuid4().hex}.{ext}'  # random name; never user-supplied


class RecordedByMixin(models.Model):
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class PatientProfile(models.Model):
    """Standing information that applies to every visit: allergies, history and ongoing nursing care needs."""
    patient = models.OneToOneField('accounts.Patient', on_delete=models.CASCADE, related_name='profile_info')
    allergies = models.TextField(blank=True, help_text='Drug, food or other allergies and the reaction')
    medical_history = models.TextField(blank=True, help_text='Past surgeries, chronic conditions, hospital stays, family history')
    wound_catheter_care = models.TextField(blank=True, help_text='Wound dressing, catheter or ostomy care needs')
    nursing_vitals = models.TextField(blank=True, help_text='Free-text vitals note kept on the live site.')
    mobility_assistance = models.TextField(blank=True, help_text='Help needed with transfers, walking, toileting')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return f'Profile: {self.patient}'


class MedicineEntry(RecordedByMixin):
    """A medicine the patient takes. `pharmacy_product` links to the pharmacy catalogue when it was picked from
    there; `custom_name` is the free-text fallback when the medicine isn't in the catalogue."""
    ACTIVE, STOPPED, COMPLETED = 'active', 'stopped', 'completed'
    STATUS_CHOICES = [(ACTIVE, 'Active'), (STOPPED, 'Stopped'), (COMPLETED, 'Completed')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='medicines')
    pharmacy_product = models.ForeignKey('marketplace.PharmacyProduct', on_delete=models.SET_NULL, null=True, blank=True)
    custom_name = models.CharField(max_length=200, blank=True)
    dosage = models.CharField(max_length=100, blank=True, help_text='e.g. 500 mg, 1 tablet')
    morning = models.BooleanField(default=False)
    afternoon = models.BooleanField(default=False)
    evening = models.BooleanField(default=False)
    night = models.BooleanField(default=False)
    instructions = models.CharField(max_length=255, blank=True, help_text='e.g. after food, with water')
    prescribed_by = models.CharField(max_length=150, blank=True)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)

    class Meta:
        ordering = ['status', 'custom_name', '-created_at']
        verbose_name_plural = 'Medicine entries'

    def __str__(self):
        return f'{self.display_name} - {self.patient}'

    @property
    def display_name(self):
        return self.pharmacy_product.name if self.pharmacy_product else self.custom_name

    @property
    def times_label(self):
        slots = [n for n, on in (('Morning', self.morning), ('Afternoon', self.afternoon), ('Evening', self.evening), ('Night', self.night)) if on]
        return ' · '.join(slots) or 'As needed'

    @property
    def effective_status(self):
        """Active medicines whose end date has passed read as completed - derived, nothing to schedule."""
        if self.status == self.ACTIVE and self.end_date and self.end_date < timezone.localdate():
            return self.COMPLETED
        return self.status


class NursingEntry(RecordedByMixin):
    """One nursing observation or task: vitals, wound care, medication given, mobility help..."""
    CATEGORY_CHOICES = [('vitals', 'Vitals check'), ('wound_care', 'Wound / dressing care'), ('catheter', 'Catheter / ostomy care'),
                        ('medication', 'Medication given'), ('mobility', 'Mobility / transfer'), ('hygiene', 'Hygiene / personal care'),
                        ('other', 'Other')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='nursing_entries')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='vitals')
    recorded_at = models.DateTimeField(default=timezone.now)
    bp_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Oxygen saturation %')
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-recorded_at', '-id']
        verbose_name_plural = 'Nursing entries'

    def __str__(self):
        return f'{self.get_category_display()} - {self.patient} ({self.recorded_at:%Y-%m-%d})'

    @property
    def vitals_summary(self):
        parts = []
        if self.bp_systolic and self.bp_diastolic:
            parts.append(f'BP {self.bp_systolic}/{self.bp_diastolic}')
        if self.pulse:
            parts.append(f'Pulse {self.pulse}')
        if self.temperature_c is not None:
            parts.append(f'Temp {self.temperature_c}°C')
        if self.spo2:
            parts.append(f'SpO₂ {self.spo2}%')
        if self.respiratory_rate:
            parts.append(f'RR {self.respiratory_rate}')
        if self.weight_kg is not None:
            parts.append(f'{self.weight_kg} kg')
        return ' · '.join(parts)

    @property
    def needs_attention(self):
        """Flags readings outside common adult ranges so the nurse sees them at a glance (a prompt, not a diagnosis)."""
        return bool(
            (self.bp_systolic and (self.bp_systolic >= 160 or self.bp_systolic < 90))
            or (self.bp_diastolic and self.bp_diastolic >= 100)
            or (self.pulse and (self.pulse > 120 or self.pulse < 50))
            or (self.temperature_c is not None and self.temperature_c >= 38)
            or (self.spo2 and self.spo2 < 92))


class AidEntry(RecordedByMixin):
    """A surgical or assistive aid issued to the patient: walker, crutches, brace, collar, wheelchair..."""
    CATEGORY_CHOICES = [('mobility', 'Walker / crutches / stick'), ('wheelchair', 'Wheelchair'), ('brace', 'Brace / support'),
                        ('collar', 'Collar / splint'), ('bed', 'Bed / mattress aid'), ('other', 'Other')]
    SIDE_CHOICES = [('', 'Not applicable'), ('left', 'Left'), ('right', 'Right'), ('both', 'Both')]
    IN_USE, RETURNED, LOST = 'in_use', 'returned', 'lost'
    STATUS_CHOICES = [(IN_USE, 'In use'), (RETURNED, 'Returned'), (LOST, 'Lost / damaged')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='aids')
    product = models.ForeignKey('marketplace.Product', on_delete=models.SET_NULL, null=True, blank=True)
    custom_name = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=12, choices=CATEGORY_CHOICES, default='mobility')
    side = models.CharField(max_length=5, choices=SIDE_CHOICES, blank=True)
    size = models.CharField(max_length=50, blank=True)
    issued_on = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=IN_USE)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['status', '-issued_on', '-id']

    def __str__(self):
        return f'{self.display_name} - {self.patient}'

    @property
    def display_name(self):
        return self.product.name if self.product else self.custom_name


class TherapyNote(RecordedByMixin):
    """A session note for occupational, speech or behavioural therapy. (Physiotherapy comes from the daily records.)"""
    OCCUPATIONAL, SPEECH, BEHAVIOURAL = 'occupational', 'speech', 'behavioural'
    THERAPY_CHOICES = [(OCCUPATIONAL, 'Occupational therapy'), (SPEECH, 'Speech therapy'), (BEHAVIOURAL, 'Behavioural therapy')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='therapy_notes')
    therapy = models.CharField(max_length=15, choices=THERAPY_CHOICES)
    session_date = models.DateField(default=timezone.localdate)
    goal = models.CharField(max_length=255, blank=True, help_text='What this session or period works towards')
    intervention = models.TextField(blank=True, help_text='What was done')
    response = models.TextField(blank=True, help_text='How the patient responded / progress seen')
    plan = models.TextField(blank=True, help_text='Next steps / home advice')

    class Meta:
        ordering = ['-session_date', '-id']

    def __str__(self):
        return f'{self.get_therapy_display()} - {self.patient} ({self.session_date})'


class LabEntry(RecordedByMixin):
    """A lab test (or panel) for the patient, from advised through to the result. `lab_test`/`lab_panel` link to the
    lab catalogue when picked from it; `custom_name` is the free-text fallback."""
    ADVISED, BOOKED, COLLECTED, RESULTED, CANCELLED = 'advised', 'booked', 'collected', 'resulted', 'cancelled'
    STATUS_CHOICES = [(ADVISED, 'Advised'), (BOOKED, 'Booked'), (COLLECTED, 'Sample collected'), (RESULTED, 'Result in'), (CANCELLED, 'Cancelled')]
    FLAG_CHOICES = [('', 'Not rated'), ('normal', 'Normal'), ('high', 'High'), ('low', 'Low'), ('critical', 'Critical')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='lab_entries')
    lab_test = models.ForeignKey('lab.LabTest', on_delete=models.SET_NULL, null=True, blank=True)
    lab_panel = models.ForeignKey('lab.LabTestPanel', on_delete=models.SET_NULL, null=True, blank=True)
    custom_name = models.CharField(max_length=200, blank=True)
    ordered_on = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ADVISED)
    notes = models.CharField(max_length=255, blank=True, help_text='e.g. repeat every 3 months')
    result_value = models.CharField(max_length=100, blank=True)
    result_unit = models.CharField(max_length=30, blank=True)
    reference_range = models.CharField(max_length=100, blank=True)
    flag = models.CharField(max_length=10, choices=FLAG_CHOICES, blank=True)
    resulted_on = models.DateField(null=True, blank=True)
    report = models.FileField(upload_to=_lab_report_path, storage=get_private_storage, blank=True)

    class Meta:
        ordering = ['-ordered_on', '-id']
        verbose_name_plural = 'Lab entries'

    def __str__(self):
        return f'{self.display_name} - {self.patient}'

    @property
    def display_name(self):
        if self.lab_panel:
            return self.lab_panel.name
        return self.lab_test.name if self.lab_test else self.custom_name
