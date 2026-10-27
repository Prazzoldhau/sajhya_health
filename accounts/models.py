import os
import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Profession(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'professions'
        ordering = ['id']

    def __str__(self):
        return self.name


class ClinicType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'clinic_types'
        ordering = ['id']

    def __str__(self):
        return self.name


class EnterpriseType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'enterprise'
        ordering = ['id']

    def __str__(self):
        return self.name


class Account(models.Model):
    CLIENT = 'client'
    PROFESSIONAL = 'professional'
    CLINIC = 'clinic'
    ENTERPRISE = 'enterprise'
    STAFF = 'staff'
    ACCOUNT_TYPES = [
        (CLIENT, 'Client'),
        (PROFESSIONAL, 'Professional'),
        (CLINIC, 'Clinic'),
        (ENTERPRISE, 'Enterprise'),
        (STAFF, 'Clinic staff'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account')
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    organization_name = models.CharField(max_length=150, blank=True)
    profession = models.ForeignKey(Profession, null=True, blank=True, on_delete=models.PROTECT)
    clinic_type = models.ForeignKey(ClinicType, null=True, blank=True, on_delete=models.PROTECT)
    enterprise_type = models.ForeignKey(EnterpriseType, null=True, blank=True, on_delete=models.PROTECT)
    personal_code = models.CharField(max_length=15, null=True, blank=True, unique=True, help_text='Short code of the person on the live site (physios shared it for pairing).')
    pairing_token = models.CharField(max_length=32, null=True, blank=True, unique=True, help_text='Token for pairing a patient app with this professional.')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user} ({self.account_type})'


def get_private_storage():
    """Credential documents live outside MEDIA_ROOT and static -- never
    served by URL, only through the permission-checked document view."""
    from django.core.files.storage import FileSystemStorage
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def document_path(instance, filename):
    return f'professional/{instance.account.user_id}/{filename}'


class ClinicalFocus(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'clinical_focus_areas'
        ordering = ['id']
        verbose_name_plural = 'Clinical focus areas'

    def __str__(self):
        return self.name


class ServiceType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'service_types'
        ordering = ['id']

    def __str__(self):
        return self.name


class ProfessionalProfile(models.Model):
    DRAFT, SUBMITTED, APPROVED, REJECTED = 'draft', 'submitted', 'approved', 'rejected'
    STATUS_CHOICES = [
        (DRAFT, 'Draft'), (SUBMITTED, 'Submitted - awaiting verification'),
        (APPROVED, 'Approved'), (REJECTED, 'Rejected'),
    ]
    DOCUMENT_FIELDS = ('id_document', 'license_document', 'degree_document')

    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name='profile')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    completed_step = models.PositiveSmallIntegerField(default=1)  # 1 = account step done
    submitted_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    # Step 1 - account & contact
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    mobile = models.CharField(max_length=20)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True)
    title = models.CharField(max_length=30, help_text='Professional title, e.g. PT, DPT, MSPT')

    # Step 2 - licensing
    license_number = models.CharField(max_length=100, blank=True)
    issuing_authority = models.CharField(max_length=200, blank=True)
    license_expiry = models.DateField(null=True, blank=True)

    # Step 3 - documents
    id_document = models.FileField(upload_to=document_path, storage=get_private_storage, blank=True)
    license_document = models.FileField(upload_to=document_path, storage=get_private_storage, blank=True)
    degree_document = models.FileField(upload_to=document_path, storage=get_private_storage, blank=True)

    # Step 4 - practice
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    focus_areas = models.ManyToManyField(ClinicalFocus, blank=True)
    services = models.ManyToManyField(ServiceType, blank=True)

    # Settings page: where the professional practises and how the workspace behaves
    practice_name = models.CharField(max_length=200, blank=True)
    practice_address = models.CharField(max_length=255, blank=True)
    practice_phone = models.CharField(max_length=20, blank=True)
    viber_number = models.CharField('Business Viber number', max_length=20, blank=True, help_text='Printed in messages next to the WhatsApp number when the practice uses Viber too.')
    whatsapp_number = models.CharField('Business WhatsApp number', max_length=20, blank=True,
                                       help_text='Printed in messages and on invoices so patients know where to reach the practice.')
    facility_code = models.CharField('Facility / HMIS code', max_length=40, blank=True,
                                     help_text='Registration number or HMIS organisation-unit code of the practice; printed on reports.')
    default_session_minutes = models.PositiveSmallIntegerField(default=30, help_text='Pre-filled length when booking an appointment.')

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.get_status_display()})'

    @property
    def full_name(self):
        return ' '.join(p for p in (self.first_name, self.middle_name, self.last_name) if p)

    def recent_patients(self, limit=5):
        """Patients added, opened or seen most recently, newest first. Empty only when there are no patients.
        Used by the dashboard and the patients page so both show the same list."""
        return self.workspace_patients().select_related('clinic').order_by(models.F('last_activity').desc(nulls_last=True), '-id')[:limit]

    def workspace_patients(self):
        """This workspace's patients: the ones registered under it, plus - for a clinic's own login - every patient of that clinic
        (including those the front desk registered on behalf of the owner)."""
        return Patient.objects.filter(models.Q(professional=self) | models.Q(clinic__workspace=self)).distinct()


def patient_photo_path(instance, filename):
    return f'patients/{instance.professional_id}/{uuid.uuid4().hex}.jpg'  # random name: not guessable, never user-supplied


class Patient(models.Model):
    ACTIVE, ON_HOLD, DISCHARGED = 'active', 'on_hold', 'discharged'
    STATUS_CHOICES = [(ACTIVE, 'Active'), (ON_HOLD, 'On Hold'), (DISCHARGED, 'Discharged')]
    GENDER_CHOICES = [('M', 'Male'), ('F', 'Female'), ('O', 'Other')]

    professional = models.ForeignKey(ProfessionalProfile, on_delete=models.CASCADE, related_name='patients')
    patient_code = models.CharField(max_length=30, unique=True, editable=False, blank=True, null=True)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    dob_is_estimate = models.BooleanField(default=False, help_text='The date of birth was worked out from an age the patient gave, so it is approximate.')
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    MESSAGING_CHOICES = [('whatsapp', 'WhatsApp'), ('viber', 'Viber'), ('sms', 'SMS (text message)')]
    messaging_app = models.CharField('Messages go by', max_length=10, choices=MESSAGING_CHOICES, default='whatsapp',
                                     help_text='The app this patient uses, so booking confirmations and notices open in it first.')
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    REFERRAL_CHOICES = [
        ('friend_family', 'Friend / Family'), ('doctor', 'Doctor referral'), ('social_media', 'Social media'),
        ('website', 'Website'), ('walk_in', 'Walk-in'), ('other', 'Other'),
    ]
    referral_source = models.CharField('How did you hear about us?', max_length=20, choices=REFERRAL_CHOICES, blank=True)
    notes = models.TextField(blank=True)
    photo = models.ImageField(upload_to=patient_photo_path, storage=get_private_storage, blank=True)
    diagnosis = models.CharField(max_length=200, blank=True)
    icd10_code = models.CharField('ICD-10 code', max_length=20, blank=True)
    insurance = models.CharField(max_length=100, blank=True)
    next_appointment = models.DateField(null=True, blank=True)
    condition = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    clinic = models.ForeignKey('clinics.Clinic', null=True, blank=True, on_delete=models.SET_NULL, related_name='patients',
                               help_text='The clinic this patient was registered under (optional).')
    # Carried over from the live site's patient record (see docs/LIVE_DATABASE.md); not used by the screens yet.
    qr_code = models.CharField(max_length=200, blank=True, help_text='Path of the patient QR image on the live site.')
    qr_token = models.CharField(max_length=32, null=True, blank=True, unique=True, help_text='Token behind the patient QR code (pairing by scan).')
    legacy_username = models.CharField(max_length=50, null=True, blank=True, unique=True, help_text='Username the patient used to sign in to the old patient app.')
    legacy_password_hash = models.CharField(max_length=128, blank=True, help_text='Old patient-app password hash (never shown). New sign-in uses the portal code flow.')
    activation_expires_at = models.DateTimeField(null=True, blank=True, help_text='When the old patient-app activation ended.')
    enterprise = models.ForeignKey('extras.Enterprise', null=True, blank=True, on_delete=models.SET_NULL, related_name='patients',
                                   help_text='The hospital / enterprise this patient was registered under (optional).')
    registered_by_name = models.CharField(max_length=200, blank=True, help_text='Who entered this patient (the physiotherapist, the clinic login or a staff member).')
    registered_by_role = models.CharField(max_length=40, blank=True)
    last_visit = models.DateField(null=True, blank=True)
    last_activity = models.DateTimeField(null=True, blank=True, help_text='Last time the patient was added, opened or seen; drives "Recent patients".')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.patient_code})'

    def touch(self):
        """Mark the patient as just used (opened, edited, visit recorded) so they head the Recent list."""
        self.last_activity = timezone.now()
        Patient.objects.filter(pk=self.pk).update(last_activity=self.last_activity)

    def save(self, *args, **kwargs):
        if self.pk is None and self.last_activity is None:
            self.last_activity = timezone.now()
        super().save(*args, **kwargs)
        if not self.patient_code:
            self.patient_code = f'PAT-{self.created_at:%Y%m%d}-{self.pk:04d}'
            super().save(update_fields=['patient_code'])

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @property
    def age_label(self):
        """'35 years', or '35 years (approx.)' when it came from an age rather than a date of birth."""
        if self.age is None:
            return ''
        return f'{self.age} years' + (' (approx.)' if self.dob_is_estimate else '')

    @property
    def registered_by_label(self):
        """Who registered the patient, for lists: the person recorded at the time, else the owning physiotherapist."""
        name = self.registered_by_name or self.professional.full_name
        return f'{name} ({self.registered_by_role})' if self.registered_by_name and self.registered_by_role else name

    @property
    def initials(self):
        return ''.join(w[0] for w in self.name.split()[:2]).upper()

    @property
    def photo_url(self):
        """Permission-checked URL of the picture ('' if none). The file name in the path only busts the browser cache."""
        if not self.photo:
            return ''
        return reverse('accounts:patient-photo', args=[self.pk, os.path.basename(self.photo.name)])


class Visit(models.Model):
    INITIAL, TREATMENT, FOLLOW_UP = 'initial', 'treatment', 'follow_up'
    SESSION_CHOICES = [(INITIAL, 'Initial Assessment'), (TREATMENT, 'Treatment'), (FOLLOW_UP, 'Follow-up')]
    PROGRESS_CHOICES = [('', '-'), ('improving', 'Improving'), ('stable', 'Stable'), ('declined', 'Declined')]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='visits')
    date = models.DateField(default=timezone.localdate)
    therapist = models.CharField(max_length=200)
    session_type = models.CharField(max_length=20, choices=SESSION_CHOICES, default=TREATMENT)
    progress = models.CharField(max_length=20, choices=PROGRESS_CHOICES, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.patient.name} - {self.date}'


class VisitTreatment(models.Model):
    """One treatment given during a session: an electrotherapy / clinical intervention, or an exercise from the library."""
    CLINICAL, EXERCISE = 'clinical', 'exercise'
    KIND_CHOICES = [(CLINICAL, 'Clinical / electrotherapy'), (EXERCISE, 'Exercise')]

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='treatments')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=CLINICAL)
    name = models.CharField(max_length=200)
    dosage = models.CharField(max_length=100, blank=True)  # e.g. "15 min", "10 reps x 3 sets"
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.name} ({self.visit})'


class Icd10Code(models.Model):
    """WHO ICD-10 reference list, searched when a clinician records a diagnosis.
    Loaded with `manage.py load_icd10`."""
    code = models.CharField(max_length=10, unique=True)
    title = models.CharField(max_length=300)

    class Meta:
        ordering = ['code']
        verbose_name = 'ICD-10 code'

    def __str__(self):
        return f'{self.code} - {self.title}'


class Appointment(models.Model):
    APPOINTMENT, UNAVAILABLE, AVAILABLE = 'appointment', 'unavailable', 'available'
    KIND_CHOICES = [(APPOINTMENT, 'Appointment'), (UNAVAILABLE, 'Unavailable block'), (AVAILABLE, 'One-off availability')]
    SCHEDULED, ATTENDED, CANCELLED = 'scheduled', 'attended', 'cancelled'
    STATUS_CHOICES = [(SCHEDULED, 'Scheduled'), (ATTENDED, 'Attended'), (CANCELLED, 'Cancelled')]

    professional = models.ForeignKey(ProfessionalProfile, on_delete=models.CASCADE, related_name='appointments')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=APPOINTMENT)
    patient = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name='appointments')
    title = models.CharField(max_length=150, blank=True)  # label for blocks
    start = models.DateTimeField()
    end = models.DateTimeField()
    session_type = models.CharField(max_length=20, choices=Visit.SESSION_CHOICES, default=Visit.TREATMENT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=SCHEDULED)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start']

    def __str__(self):
        return f'{self.patient or self.title} @ {self.start:%Y-%m-%d %H:%M}'


class MessageTemplate(models.Model):
    """This professional's own wording of a WhatsApp message (a built-in one they changed, or a notice they wrote). Placeholders like
    {patient} and {date} are filled in per patient - see accounts/messaging.py."""
    professional = models.ForeignKey(ProfessionalProfile, on_delete=models.CASCADE, related_name='message_templates')
    key = models.CharField(max_length=60, help_text='A built-in message name, or custom-xxxxxxxx for a notice the professional wrote.')
    title = models.CharField(max_length=100, blank=True)
    body = models.TextField(max_length=1000)
    is_custom = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('professional', 'key')]

    def __str__(self):
        return f'{self.title or self.key} ({self.professional})'


class Task(models.Model):
    professional = models.ForeignKey(ProfessionalProfile, on_delete=models.CASCADE, related_name='tasks')
    text = models.CharField(max_length=200)
    due = models.DateTimeField(null=True, blank=True)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['done', 'due', 'id']

    def __str__(self):
        return self.text


class TreatmentPlan(models.Model):
    DRAFT, ACTIVE, COMPLETED, DISCONTINUED = 'draft', 'active', 'completed', 'discontinued'
    STATUS_CHOICES = [(DRAFT, 'Draft'), (ACTIVE, 'Active'), (COMPLETED, 'Completed'), (DISCONTINUED, 'Discontinued')]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='plans')
    professional = models.ForeignKey(ProfessionalProfile, on_delete=models.CASCADE, related_name='plans')
    title = models.CharField(max_length=200, default='Treatment Plan')
    diagnosis = models.CharField(max_length=200, blank=True)
    icd10_code = models.CharField('ICD-10 code', max_length=20, blank=True)
    onset_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    precautions = models.TextField(blank=True)
    education = models.TextField('Patient education / notes', blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} - {self.patient.name}'

    @property
    def total_weeks(self):
        return max((ph.week_end for ph in self.phases.all()), default=0)

    @property
    def current_week(self):
        if not self.total_weeks:
            return 0
        week = (timezone.localdate() - self.start_date).days // 7 + 1
        return max(0, min(week, self.total_weeks))


class PlanGoal(models.Model):
    SHORT, LONG = 'short', 'long'
    TERM_CHOICES = [(SHORT, 'Short-term'), (LONG, 'Long-term')]

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name='goals')
    text = models.CharField(max_length=300)
    term = models.CharField(max_length=10, choices=TERM_CHOICES, default=SHORT)
    target_date = models.DateField(null=True, blank=True)
    achieved = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']


class PlanMeasure(models.Model):
    """A baseline metric (pain score, ROM, strength...) with a target; readings track progress."""
    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name='measures')
    name = models.CharField(max_length=150)
    unit = models.CharField(max_length=20, blank=True)
    baseline = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    target = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    @property
    def latest(self):
        readings = sorted(self.readings.all(), key=lambda r: (r.date, r.id))  # uses prefetched rows when available
        return readings[-1].value if readings else self.baseline

    @property
    def progress_pct(self):
        """How far the latest value has moved from baseline towards target (works for 'lower is better' too)."""
        if self.baseline is None or self.target is None or self.baseline == self.target:
            return None
        current = self.latest
        pct = (current - self.baseline) / (self.target - self.baseline) * 100
        return int(max(0, min(100, pct)))


class PlanReading(models.Model):
    measure = models.ForeignKey(PlanMeasure, on_delete=models.CASCADE, related_name='readings')
    date = models.DateField(default=timezone.localdate)
    value = models.DecimalField(max_digits=8, decimal_places=2)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['date', 'id']


class PlanPhase(models.Model):
    UPCOMING, CURRENT, COMPLETED = 'upcoming', 'current', 'completed'
    STATUS_CHOICES = [(UPCOMING, 'Upcoming'), (CURRENT, 'In progress'), (COMPLETED, 'Completed')]

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name='phases')
    name = models.CharField(max_length=100)
    week_start = models.PositiveSmallIntegerField(default=1)
    week_end = models.PositiveSmallIntegerField(default=2)
    frequency_per_week = models.PositiveSmallIntegerField(default=2)
    frequency_note = models.CharField(max_length=50, blank=True, default='Clinic')
    goal = models.CharField('Phase goal / progression criteria', max_length=300, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=UPCOMING)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    @property
    def weeks_label(self):
        return f'Week {self.week_start}' if self.week_start == self.week_end else f'Weeks {self.week_start}-{self.week_end}'


class PlanItem(models.Model):
    CLINIC, HEP = 'clinic', 'hep'
    KIND_CHOICES = [(CLINIC, 'In-clinic intervention'), (HEP, 'Home exercise')]

    phase = models.ForeignKey(PlanPhase, on_delete=models.CASCADE, related_name='items')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    text = models.CharField(max_length=200)
    dosage = models.CharField(max_length=100, blank=True)  # e.g. "3x/day", "10 reps, 3 sets"
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
