"""Clinic accounts: a verified professional upgrades their plan, creates clinics, adds verified physios (by invitation) and
staff, tags patients to a clinic and runs an on-site queue. See docs/CLINICS.md.

A clinic owner keeps their normal professional workspace. Patients stay private to the professional treating them; the
clinic only sees what it needs to run the front desk (queue) and aggregate counts.
"""
import secrets
import string

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from .modules import MODULES, PERMISSION_MODULES, default_modules


def default_cap():
    return settings.CLINIC_MONTHLY_PATIENT_CAP


def default_overage_rate():
    return Decimal(settings.CLINIC_OVERAGE_RATE)


class ClinicSubscription(models.Model):
    """A professional's upgrade to the Clinic plan. There is no online payment yet, so it is a request that staff
    activate (admin action) once payment is arranged."""
    REQUESTED, ACTIVE, REJECTED, CANCELLED = 'requested', 'active', 'rejected', 'cancelled'
    STATUS_CHOICES = [(REQUESTED, 'Requested - awaiting activation'), (ACTIVE, 'Active'), (REJECTED, 'Declined'), (CANCELLED, 'Cancelled')]

    professional = models.OneToOneField('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='clinic_subscription')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=REQUESTED)
    clinic_limit = models.PositiveSmallIntegerField(default=3, help_text='How many clinics this professional may create.')
    monthly_patient_cap = models.PositiveIntegerField(default=default_cap, help_text='New patients each clinic may enrol per calendar month before extra charges start.')
    overage_rate = models.DecimalField(max_digits=8, decimal_places=2, default=default_overage_rate, help_text='NPR per enrolled patient above the monthly cap.')
    contact_phone = models.CharField(max_length=20, blank=True)
    request_note = models.TextField(blank=True, help_text='What the professional wrote when asking to upgrade.')
    requested_at = models.DateTimeField(default=timezone.now)
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True, help_text='Leave empty for no expiry.')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    staff_note = models.CharField(max_length=255, blank=True, help_text='Shown to the professional, e.g. the reason for declining.')

    def __str__(self):
        return f'{self.professional} - {self.get_status_display()}'

    @property
    def is_active(self):
        return self.status == self.ACTIVE and (self.expires_at is None or self.expires_at >= timezone.localdate())

    @property
    def is_expired(self):
        return self.status == self.ACTIVE and not self.is_active


def make_clinic_code():
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = 'CLI-' + ''.join(secrets.choice(alphabet) for _ in range(6))
        if not Clinic.objects.filter(code=code).exists():
            return code


PROVINCES = ['Koshi', 'Madhesh', 'Bagmati', 'Gandaki', 'Lumbini', 'Karnali', 'Sudurpashchim']
SPECIALIZATIONS = [('musculoskeletal', 'Musculoskeletal'), ('sports', 'Sports rehab'), ('neurological', 'Neurological'),
                   ('pediatric', 'Pediatric'), ('geriatric', 'Geriatric'), ('cardiorespiratory', 'Cardiorespiratory')]
AMENITIES = [('wheelchair', 'Wheelchair accessible / ramp'), ('private_rooms', 'Private consultation rooms'), ('gym', 'Dedicated exercise gym area'),
             ('parking', 'Parking available'), ('digital_payment', 'Digital payment accepted (eSewa, Khalti, Fonepay)')]
WEEKDAYS = [('sunday', 'Sunday'), ('monday', 'Monday'), ('tuesday', 'Tuesday'), ('wednesday', 'Wednesday'), ('thursday', 'Thursday'),
            ('friday', 'Friday'), ('saturday', 'Saturday')]  # Nepal's week starts on Sunday
SLOT_CHOICES = [(15, '15 minutes'), (30, '30 minutes'), (45, '45 minutes'), (60, '60 minutes')]


class Clinic(models.Model):
    owner = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='owned_clinics')
    workspace = models.OneToOneField('accounts.ProfessionalProfile', null=True, blank=True, on_delete=models.SET_NULL, related_name='clinic_workspace',
                                     help_text="The clinic's own sign-in: a workspace profile with its own patients, appointments, billing and reports. Set by the owner.")
    code = models.CharField(max_length=14, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # 1. Basic information
    name = models.CharField(max_length=200)
    short_bio = models.CharField('Short bio / description', max_length=500, blank=True)
    logo = models.ImageField(upload_to='clinic_logos/', blank=True)
    banner = models.ImageField('Banner / cover image', upload_to='clinic_banners/', blank=True)

    # 2. Legal and registration
    pan_number = models.CharField('Business registration number (PAN / VAT / company reg.)', max_length=30, unique=True, null=True, blank=True)
    facility_license = models.CharField('Health facility licence number', max_length=60, blank=True)
    specializations = models.JSONField(default=list, blank=True)

    # 3. Contact and location
    phone = models.CharField('Primary phone', max_length=20)
    phone_secondary = models.CharField('Secondary phone', max_length=20, blank=True)
    email = models.EmailField('Official email', blank=True)
    website = models.URLField(blank=True)
    province = models.CharField(max_length=20, blank=True)
    district = models.CharField('District / city', max_length=80, blank=True)
    ward_street = models.CharField('Ward no. / street address', max_length=150, blank=True)
    map_link = models.CharField('Google Maps link / coordinates', max_length=500, blank=True)
    address = models.CharField(max_length=255, blank=True, editable=False, help_text='Built from the location fields.')

    # 4. Hours and slots   hours = {"sunday": ["10:00", "18:00"], ...}  (days not listed are closed)
    hours = models.JSONField(default=dict, blank=True)
    slot_minutes = models.PositiveSmallIntegerField(default=30)

    # 5. Amenities
    amenities = models.JSONField(default=list, blank=True)

    # 6. Plan: the parts of the workspace this clinic has switched on (set by staff in the admin)
    modules = models.JSONField(default=default_modules, blank=True, help_text='Parts of the workspace this clinic can use.')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.code})'

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = make_clinic_code()
        if not self.pan_number:
            self.pan_number = None  # several clinics may leave it blank; unique only when filled
        self.address = ', '.join(x for x in (self.ward_street, self.district, self.province) if x) or self.address
        super().save(*args, **kwargs)

    @property
    def is_usable(self):
        """Team, queue and patient tagging work once the owner's Clinic plan is active (staff activate it)."""
        sub = ClinicSubscription.objects.filter(professional_id=self.owner_id).first()
        return bool(sub and sub.is_active)

    @property
    def calendar_owner(self):
        """The workspace whose calendar holds the clinic's appointments: its own login when it has one, otherwise the owning physiotherapist."""
        return self.workspace or self.owner

    def has_module(self, key):
        return key in (self.modules or [])

    @property
    def module_rows(self):
        """(name, what it gives, switched on) for every module, for the owner's overview."""
        return [(name, what, key in (self.modules or [])) for key, name, what, _ in MODULES]

    @property
    def hours_rows(self):
        return [(label, self.hours.get(key)) for key, label in WEEKDAYS]

    @property
    def specialization_labels(self):
        names = dict(SPECIALIZATIONS)
        return [names[k] for k in self.specializations if k in names]

    @property
    def amenity_labels(self):
        names = dict(AMENITIES)
        return [names[k] for k in self.amenities if k in names]

    def completeness(self):
        """(percent, [labels of what is still missing]) - the optional parts of the profile can be completed later."""
        checks = [('Logo', self.logo), ('Banner image', self.banner), ('Short bio', self.short_bio), ('Registration number', self.pan_number),
                  ('Facility licence number', self.facility_license), ('Specialisations', self.specializations), ('Official email', self.email),
                  ('Website', self.website), ('Map location', self.map_link), ('Working hours', self.hours), ('Amenities', self.amenities)]
        missing = [label for label, value in checks if not value]
        return round(100 * (len(checks) - len(missing)) / len(checks)), missing


class ClinicMember(models.Model):
    """A physio (a verified professional, joins by accepting an invitation) or a staff member (a record without a login)."""
    PHYSIO, MANAGER, RECEPTIONIST, ASSISTANT, OTHER, DEPARTMENT = 'physio', 'manager', 'receptionist', 'assistant', 'other', 'department'
    ROLE_CHOICES = [(PHYSIO, 'Physiotherapist'), (MANAGER, 'Manager'), (RECEPTIONIST, 'Receptionist'), (ASSISTANT, 'Therapy assistant'), (OTHER, 'Other staff'),
                    (DEPARTMENT, 'Department login')]
    STAFF_ROLES = ROLE_CHOICES[1:]  # everything except physio
    INVITED, ACTIVE, DECLINED, LEFT = 'invited', 'active', 'declined', 'left'
    STATUS_CHOICES = [(INVITED, 'Invited'), (ACTIVE, 'Active'), (DECLINED, 'Declined'), (LEFT, 'Left / removed')]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='members')
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default=PHYSIO)
    physio = models.ForeignKey('accounts.ProfessionalProfile', null=True, blank=True, on_delete=models.CASCADE, related_name='clinic_memberships')
    user = models.OneToOneField('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='clinic_staff',
                                help_text='Staff only: the sign-in the owner gave this person.')
    department = models.ForeignKey('accounts.Department', null=True, blank=True, on_delete=models.SET_NULL, related_name='logins',
                                   help_text='Department login only: the department whose schedule this sign-in shows.')
    name = models.CharField(max_length=150, blank=True, help_text='Staff only; physios use their profile name.')
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    invited_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['role', 'id']
        unique_together = [('clinic', 'physio')]

    def __str__(self):
        return f'{self.display_name} @ {self.clinic.name}'

    @property
    def display_name(self):
        return self.physio.full_name if self.physio_id else self.name

    @property
    def is_physio(self):
        return self.role == self.PHYSIO

    # what each staff role may do at the front desk (clinical records are never part of it)
    PERMISSIONS = {
        MANAGER: {'overview', 'patients', 'contact', 'register', 'queue', 'queue_manage', 'billing', 'team', 'schedule'},
        RECEPTIONIST: {'patients', 'contact', 'register', 'queue', 'queue_manage', 'billing', 'schedule'},
        ASSISTANT: {'patients', 'queue', 'queue_manage', 'record_session', 'schedule'},
        OTHER: {'queue'},
        DEPARTMENT: {'schedule'},  # a department's screen shows its own appointments and nothing else
    }

    def can(self, permission):
        module = PERMISSION_MODULES.get(permission)
        if module and not self.clinic.has_module(module):
            return False  # that part is not in the clinic's plan
        return permission in self.PERMISSIONS.get(self.role, ())


class QueueEntry(models.Model):
    """One patient's place in a clinic's on-site queue for the day."""
    WAITING, CALLED, COMPLETED, CANCELLED = 'waiting', 'called', 'completed', 'cancelled'
    STATUS_CHOICES = [(WAITING, 'Waiting'), (CALLED, 'In session'), (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled')]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='queue_entries')
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='queue_entries')
    added_by = models.ForeignKey('accounts.ProfessionalProfile', null=True, on_delete=models.SET_NULL, related_name='+')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=WAITING)
    joined_at = models.DateTimeField(default=timezone.now)
    called_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['joined_at', 'id']

    def __str__(self):
        return f'{self.patient} @ {self.clinic} ({self.status})'


class ClinicMonthlyUsage(models.Model):
    """How many patients a clinic enrolled in one calendar month, and what is due when that goes over the cap.
    Rows are refreshed from the patient records until they are marked paid (see clinics/usage.py)."""
    OPEN, DUE, PAID = 'open', 'due', 'paid'
    STATUS_CHOICES = [(OPEN, 'Within the cap'), (DUE, 'Due before next billing'), (PAID, 'Paid')]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='usage')
    month = models.DateField(help_text='First day of the month.')
    enrolled = models.PositiveIntegerField(default=0)
    cap = models.PositiveIntegerField(default=default_cap)
    rate = models.DecimalField(max_digits=8, decimal_places=2, default=default_overage_rate)
    overage = models.PositiveIntegerField(default=0)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=5, choices=STATUS_CHOICES, default=OPEN)
    paid_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, help_text='Payment reference.')

    class Meta:
        ordering = ['-month']
        unique_together = [('clinic', 'month')]
        verbose_name_plural = 'Clinic monthly usage'

    def __str__(self):
        return f'{self.clinic.name} {self.month:%Y-%m}: {self.enrolled}/{self.cap}'

    @property
    def is_current(self):
        return self.month == timezone.localdate().replace(day=1)
