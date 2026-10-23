import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

PAYMENT_MODE_CHOICES = [('cash', 'Cash'), ('card', 'Card'), ('online', 'Online'), ('other', 'Other')]


class BillingEntry(models.Model):
    """One billing line a professional logs for their daily record - the digital version of the paper
    invoice book (patient, service, rate, payment mode). Deliberately simple: no insurance or tax lines.
    `patient` is optional so walk-ins who aren't registered can still be billed; when it is set,
    the name/age/sex/contact fields are filled from the record."""

    SEX_CHOICES = [('M', 'Male'), ('F', 'Female'), ('O', 'Other')]

    invoice_number = models.CharField(max_length=20, unique=True, editable=False)
    professional = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='billing_entries')
    patient = models.ForeignKey('accounts.Patient', null=True, blank=True, on_delete=models.SET_NULL, related_name='billing_entries')
    entry_date = models.DateField(default=timezone.localdate)
    patient_name = models.CharField(max_length=200)
    age = models.PositiveIntegerField(null=True, blank=True)
    sex = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    service = models.CharField(max_length=150, default='Physiotherapy')
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODE_CHOICES, default='cash')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-entry_date', '-created_at']
        verbose_name_plural = 'Billing entries'

    def __str__(self):
        return f'{self.invoice_number} - {self.patient_name} ({self.entry_date})'

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = f'BILL-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)


class Plan(models.Model):
    """What an account type gets and what it costs - the content of the package page (Client / Professional /
    Clinic / Enterprise). Editable in the admin."""

    code = models.CharField(max_length=20, unique=True, help_text='Matches the account type: client, professional, clinic, enterprise')
    name = models.CharField(max_length=60)
    tagline = models.CharField(max_length=80, blank=True)
    icon = models.CharField(max_length=40, blank=True, help_text='Font Awesome icon name, e.g. user-md')
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                        help_text='NPR per month. 0 = free. Leave empty for custom (negotiated) pricing.')
    patient_limit = models.PositiveIntegerField(null=True, blank=True, help_text='Maximum patient records. Empty = unlimited.')
    price_note = models.CharField(max_length=120, blank=True, help_text='Small print under the price, e.g. "first 10 patients free, then NPR 200 per patient".')
    features = models.JSONField(default=list, blank=True, help_text='List of {"text": "...", "included": true}')
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name

    @property
    def is_free(self):
        return self.price_monthly is not None and self.price_monthly == 0

    @property
    def is_custom(self):
        return self.price_monthly is None

    @property
    def price_label(self):
        if self.is_custom:
            return 'Custom pricing'
        if self.is_free:
            return 'Free'
        return f'NPR {self.price_monthly:,.0f} / month'


class PatientPackage(models.Model):
    """A prepaid session package a professional sells a patient: 1, 2, 3 or 4 weeks, a set number of sessions
    and a flat price. Sessions are counted against the package whenever a visit is recorded for the patient.
    Money is a separate paid-vs-due ledger (PackagePayment), since packages are often paid off in instalments."""

    DURATION_CHOICES = [('1_week', '1 Week'), ('2_week', '2 Weeks'), ('3_week', '3 Weeks'), ('4_week', '4 Weeks')]
    DURATION_DAYS = {'1_week': 7, '2_week': 14, '3_week': 21, '4_week': 28}
    ACTIVE, COMPLETED, CANCELLED = 'active', 'completed', 'cancelled'
    STATUS_CHOICES = [(ACTIVE, 'Active'), (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='packages')
    professional = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='patient_packages')
    duration = models.CharField(max_length=10, choices=DURATION_CHOICES)
    total_sessions = models.PositiveIntegerField(help_text='How many sessions this package covers')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sessions_used = models.PositiveIntegerField(default=0)
    start_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    notes = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_duration_display()} package - {self.patient.name} ({self.sessions_used}/{self.total_sessions})'

    @property
    def end_date(self):
        return self.start_date + timedelta(days=self.DURATION_DAYS[self.duration])

    @property
    def sessions_remaining(self):
        return max(0, self.total_sessions - self.sessions_used)

    @property
    def is_expired(self):
        return self.status == self.ACTIVE and timezone.localdate() > self.end_date

    @property
    def effective_status(self):
        """status, but showing completed/expired once the stored value is stale - derived, not scheduled."""
        if self.status == self.ACTIVE and self.sessions_used >= self.total_sessions:
            return 'completed'
        if self.is_expired:
            return 'expired'
        return self.status

    @property
    def effective_status_display(self):
        return 'Expired' if self.effective_status == 'expired' else dict(self.STATUS_CHOICES).get(self.effective_status, self.effective_status)

    @property
    def amount_due(self):
        return max(Decimal('0'), self.total_amount - self.amount_paid)

    @property
    def is_fully_paid(self):
        return self.amount_due <= 0

    @property
    def usage_pct(self):
        return min(100, round(self.sessions_used / self.total_sessions * 100)) if self.total_sessions else 0

    @property
    def per_session(self):
        return self.total_amount / self.total_sessions if self.total_sessions else Decimal('0')

    def record_session(self):
        """Use up one session. No-op (False) unless the package is actually active."""
        if self.effective_status != 'active':
            return False
        self.sessions_used += 1
        if self.sessions_used >= self.total_sessions:
            self.status = self.COMPLETED
        self.save()
        return True

    def record_payment(self, amount, payment_mode='cash', notes=''):
        """Log one payment, capped at what is still owed. Returns the PackagePayment, or None if nothing was recorded."""
        if amount is None or amount <= 0 or self.is_fully_paid:
            return None
        amount = min(Decimal(amount), self.amount_due)
        payment = PackagePayment.objects.create(package=self, amount=amount, payment_mode=payment_mode, notes=notes)
        self.amount_paid += amount
        self.save()
        return payment


class PackagePayment(models.Model):
    package = models.ForeignKey(PatientPackage, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODE_CHOICES, default='cash')
    notes = models.CharField(max_length=255, blank=True, default='')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'NPR {self.amount} - {self.package}'


def use_package_session(patient):
    """Called when a visit is recorded: counts one session against the patient's active package, if any."""
    package = patient.packages.filter(status=PatientPackage.ACTIVE).order_by('created_at').first()
    return package.record_session() if package else False


# ---------------------------------------------------------------- patient allowance (Professional pricing)

def default_free_limit():
    return settings.FREE_PATIENT_LIMIT


def default_slot_rate():
    return Decimal(settings.PATIENT_SLOT_RATE)


class PatientAllowance(models.Model):
    """How many patients a professional may register: `free_limit` free, plus `paid_slots` bought at `rate` each.
    Patients registered inside a clinic are not counted here (the clinic plan covers them, see clinics.usage)."""
    professional = models.OneToOneField('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='allowance')
    free_limit = models.PositiveIntegerField(default=default_free_limit)
    paid_slots = models.PositiveIntegerField(default=0, help_text='Extra patients paid for. Staff add these when a slot order is marked paid.')
    rate = models.DecimalField(max_digits=8, decimal_places=2, default=default_slot_rate, help_text='NPR per extra patient.')

    def __str__(self):
        return f'{self.professional}: {self.used}/{self.allowed}'

    @classmethod
    def for_profile(cls, profile):
        return cls.objects.get_or_create(professional=profile)[0]

    @property
    def allowed(self):
        return self.free_limit + self.paid_slots

    @property
    def used(self):
        return self.professional.patients.filter(clinic__isnull=True).count()

    @property
    def remaining(self):
        return max(0, self.allowed - self.used)

    @property
    def can_add(self):
        return self.used < self.allowed

    @property
    def over_free(self):
        return max(0, self.used - self.free_limit)


class SlotOrder(models.Model):
    """A request to buy extra patient slots. There is no online payment yet: staff mark it paid in the admin, which adds the slots."""
    REQUESTED, PAID, CANCELLED = 'requested', 'paid', 'cancelled'
    STATUS_CHOICES = [(REQUESTED, 'Requested - awaiting payment'), (PAID, 'Paid - slots added'), (CANCELLED, 'Cancelled')]

    professional = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='slot_orders')
    quantity = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=8, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    note = models.CharField(max_length=255, blank=True, help_text='Payment reference or a message for the professional.')

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f'{self.quantity} slots for {self.professional} ({self.get_status_display()})'

    def mark_paid(self, user):
        """Add the slots (once) and close the order."""
        if self.status == self.PAID:
            return False
        allowance = PatientAllowance.for_profile(self.professional)
        allowance.paid_slots += self.quantity
        allowance.save(update_fields=['paid_slots'])
        self.status, self.paid_at, self.reviewed_by = self.PAID, timezone.now(), user
        self.save(update_fields=['status', 'paid_at', 'reviewed_by'])
        return True
