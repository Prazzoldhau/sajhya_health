import uuid
from decimal import Decimal

from django.db import models


class LabTest(models.Model):
    """A blood investigation people can book. The catalogue is managed in the admin so prices, wording and the
    list itself can change without a release. The starter prices came from the original project; review them
    before real use."""

    CATEGORY_CHOICES = [
        ('hematology', 'Hematology'), ('biochemistry', 'Biochemistry'), ('hormonal', 'Hormonal'),
        ('serology', 'Serology / Infection'), ('electrolytes', 'Electrolytes & Minerals'), ('urine', 'Urine'), ('other', 'Other'),
    ]

    name = models.CharField(max_length=150, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    sample_type = models.CharField(max_length=100, blank=True, help_text='e.g. "Blood - Venous"')
    prep_instructions = models.CharField(max_length=255, blank=True, help_text='e.g. "8-12 hours fasting required"')
    turnaround_time = models.CharField(max_length=100, blank=True, help_text='e.g. "Same day", "24 hours"')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name


class LabTestPanel(models.Model):
    """A bundle of tests sold together at one price, normally cheaper than buying each test alone."""

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    tests = models.ManyToManyField(LabTest, related_name='panels')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def a_la_carte_total(self):
        return sum((t.price for t in self.tests.all()), Decimal('0.00'))

    @property
    def savings(self):
        return self.a_la_carte_total - self.price


class LabTestRequest(models.Model):
    """A booking for one or more tests made on the public website (no login). Staff process it in the admin."""

    STATUS_CHOICES = [('pending', 'Pending'), ('sample_collected', 'Sample Collected'), ('completed', 'Completed'), ('cancelled', 'Cancelled')]

    request_number = models.CharField(max_length=20, unique=True, editable=False)
    patient = models.ForeignKey('accounts.Patient', null=True, blank=True, on_delete=models.SET_NULL, related_name='lab_requests',
                                help_text='The patient record the booking was made for (when a physio books for a patient).')
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='lab_requests',
                             help_text='The signed-in account that booked it (empty for a guest booking).')
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    collection_address = models.TextField(help_text='Where the sample should be collected from')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Lab request {self.request_number} - {self.customer_name}'

    def save(self, *args, **kwargs):
        if not self.request_number:
            self.request_number = f'LAB-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)


class LabTestRequestItem(models.Model):
    """One test or panel within a request. Name and price are copied at booking time so a later price change
    does not rewrite what was actually requested."""

    request = models.ForeignKey(LabTestRequest, on_delete=models.CASCADE, related_name='items')
    lab_test = models.ForeignKey(LabTest, on_delete=models.SET_NULL, null=True, blank=True)
    lab_panel = models.ForeignKey(LabTestPanel, on_delete=models.SET_NULL, null=True, blank=True)
    test_name = models.CharField(max_length=150)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.test_name
