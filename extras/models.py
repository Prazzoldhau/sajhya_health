"""Tables of the live sajhya.com database that this project did not have yet, so its data can be loaded later without losing anything.

Each model mirrors one live table (see docs/LIVE_DATABASE.md and extras/live_map.py for the table-by-table mapping). The screens for most of
these features are not built yet; the tables exist so the data model is complete and a loader never has to improvise.
"""
import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone


class CareerVacancy(models.Model):
    """A job vacancy on the careers page.  (live table `careers_app_vacancy`)"""
    title = models.CharField(max_length=200, blank=True)
    department = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=150, blank=True)
    employment_type = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    is_active = models.BooleanField(default=False)
    posted_at = models.DateTimeField(default=timezone.now)
    closing_date = models.DateField(null=True, blank=True)
    organization = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return str(self.title) if self.title else f'CareerVacancy {self.pk}'


class CareerApplication(models.Model):
    """An application (with CV) for a vacancy.  (live table `careers_app_vacancyapplication`)"""
    full_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    resume = models.CharField(max_length=100, null=True, blank=True)
    cover_note = models.TextField(blank=True)
    status = models.CharField(max_length=20, blank=True)
    admin_notes = models.TextField(blank=True)
    applied_at = models.DateTimeField(default=timezone.now)
    vacancy = models.ForeignKey('CareerVacancy', on_delete=models.CASCADE, related_name='+')

    def __str__(self):
        return str(self.full_name) if self.full_name else f'CareerApplication {self.pk}'


class DeliveryZone(models.Model):
    """A delivery area.  (live table `delivery_app_zone`)"""
    name = models.CharField(max_length=100, blank=True, unique=True)

    def __str__(self):
        return str(self.name) if self.name else f'DeliveryZone {self.pk}'


class DeliveryRider(models.Model):
    """A delivery rider.  (live table `delivery_app_rider`)"""
    rider_code = models.CharField(max_length=15, blank=True, unique=True)
    vehicle_type = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=15, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    current_zone = models.ForeignKey('DeliveryZone', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.rider_code) if self.rider_code else f'DeliveryRider {self.pk}'


class Delivery(models.Model):
    """Delivery of a shop order (cash on delivery tracking).  (live table `delivery_app_delivery`)"""
    status = models.CharField(max_length=15, blank=True)
    cod_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cod_collected = models.BooleanField(default=False)
    cod_collected_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    order = models.OneToOneField('marketplace.Order', on_delete=models.CASCADE, related_name='+')
    rider = models.ForeignKey('DeliveryRider', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    drop_zone = models.ForeignKey('DeliveryZone', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    pickup_zone = models.ForeignKey('DeliveryZone', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.status) if self.status else f'Delivery {self.pk}'


class DonatableCategory(models.Model):
    """A kind of item people can donate.  (live table `donate_app_donatablecategory`)"""
    name = models.CharField(max_length=100, blank=True, unique=True)
    description = models.CharField(max_length=255, blank=True)
    image = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return str(self.name) if self.name else f'DonatableCategory {self.pk}'


class DonationPledge(models.Model):
    """A donor's pledge.  (live table `donate_app_donationpledge`)"""
    pledge_number = models.CharField(max_length=20, blank=True, unique=True)
    donor_name = models.CharField(max_length=200, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    items = models.ManyToManyField('DonatableCategory', blank=True, related_name='+')

    def __str__(self):
        return str(self.pledge_number) if self.pledge_number else f'DonationPledge {self.pk}'


class Enterprise(models.Model):
    """A hospital / large organisation account.  (live table `enterprise_account_enterprise`)"""
    enterprise_name = models.CharField(max_length=255, blank=True)
    enterprise_code = models.CharField(max_length=14, blank=True, unique=True)
    pan_number = models.CharField(max_length=30, null=True, blank=True, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')

    def __str__(self):
        return str(self.enterprise_name) if self.enterprise_name else f'Enterprise {self.pk}'


class EnterpriseStaff(models.Model):
    """A physio working for an enterprise.  (live table `enterprise_account_enterprisestaff`)"""
    joined_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=False)
    enterprise = models.ForeignKey('Enterprise', on_delete=models.CASCADE, related_name='+')
    physio = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('enterprise', 'physio')]

    def __str__(self):
        return f'EnterpriseStaff {self.pk}'


class EnterpriseWard(models.Model):
    """A ward of an enterprise (nurses raise physio requests from it).  (live table `enterprise_account_ward`)"""
    ward_type = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    enterprise = models.ForeignKey('Enterprise', on_delete=models.CASCADE, related_name='+')
    access_token = models.CharField(max_length=24, blank=True, unique=True)
    pin = models.CharField(max_length=10, blank=True)
    pin_hash = models.CharField(max_length=128, blank=True)

    class Meta:
        unique_together = [('enterprise', 'ward_type')]

    def __str__(self):
        return str(self.ward_type) if self.ward_type else f'EnterpriseWard {self.pk}'


class PhysioRequest(models.Model):
    """A request for a physio visit raised from a ward.  (live table `enterprise_account_physiorequest`)"""
    patient_name = models.CharField(max_length=100, blank=True)
    bed_number = models.CharField(max_length=20, blank=True)
    reason = models.CharField(max_length=20, blank=True)
    urgency = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    status_updated_at = models.DateTimeField(null=True, blank=True)
    ward = models.ForeignKey('EnterpriseWard', on_delete=models.CASCADE, related_name='+')
    physio_message = models.TextField(blank=True)
    status_updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.patient_name) if self.patient_name else f'PhysioRequest {self.pk}'


class Specialization(models.Model):
    """A physio specialisation shown in the public directory.  (live table `find_physio_app_specialization`)"""
    name = models.CharField(max_length=100, blank=True, unique=True)
    slug = models.CharField(max_length=50, blank=True, unique=True)

    def __str__(self):
        return str(self.name) if self.name else f'Specialization {self.pk}'


class PhysioListing(models.Model):
    """A physio's public directory profile (fees, bio, rating).  (live table `find_physio_app_physioprofile`)"""
    bio = models.TextField(blank=True)
    photo = models.CharField(max_length=100, null=True, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=200, blank=True)
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    home_visit_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    travel_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_home_visit = models.BooleanField(default=False)
    is_clinic_visit = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_reviews = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    physio = models.OneToOneField('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='+')
    specializations = models.ManyToManyField('Specialization', blank=True, related_name='+')

    def __str__(self):
        return str(self.bio) if self.bio else f'PhysioListing {self.pk}'


class PhysioAvailability(models.Model):
    """A weekly availability slot of a directory physio.  (live table `find_physio_app_physioavailability`)"""
    day_of_week = models.IntegerField(default=0)
    start_time = models.TimeField(default=datetime.time(0, 0))
    end_time = models.TimeField(default=datetime.time(0, 0))
    is_home = models.BooleanField(default=False)
    physio = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('physio', 'day_of_week', 'is_home')]

    def __str__(self):
        return f'PhysioAvailability {self.pk}'


class BookingRequest(models.Model):
    """A visitor's request to book a directory physio.  (live table `find_physio_app_bookingrequest`)"""
    patient_name = models.CharField(max_length=100, blank=True)
    patient_contact = models.CharField(max_length=20, blank=True)
    patient_email = models.EmailField(blank=True)
    condition = models.CharField(max_length=300, blank=True)
    preferred_date = models.DateField(default=timezone.localdate)
    preferred_time = models.TimeField(null=True, blank=True)
    booking_type = models.CharField(max_length=10, blank=True)
    address = models.TextField(blank=True)
    status = models.CharField(max_length=15, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    physio = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='+')

    def __str__(self):
        return str(self.patient_name) if self.patient_name else f'BookingRequest {self.pk}'


class PhysioReview(models.Model):
    """A review of a directory physio.  (live table `find_physio_app_physioreview`)"""
    reviewer_name = models.CharField(max_length=100, blank=True)
    rating = models.IntegerField(default=0)
    comment = models.TextField(blank=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    booking = models.ForeignKey('BookingRequest', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    physio = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='+')

    def __str__(self):
        return str(self.reviewer_name) if self.reviewer_name else f'PhysioReview {self.pk}'


class Commission(models.Model):
    """Commission owed to a physio for a recommended shop order.  (live table `marketplace_app_commission`)"""
    patient_code = models.CharField(max_length=20, blank=True)
    order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    order = models.OneToOneField('marketplace.Order', on_delete=models.CASCADE, related_name='+')
    physio = models.ForeignKey('accounts.ProfessionalProfile', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.patient_code) if self.patient_code else f'Commission {self.pk}'


class CommissionRate(models.Model):
    """A physio's own commission rate.  (live table `marketplace_app_commissionrate`)"""
    rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    physio = models.OneToOneField('accounts.ProfessionalProfile', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return f'CommissionRate {self.pk}'


class DiagnosisProductMap(models.Model):
    """Which shop products to suggest for a diagnosis keyword.  (live table `marketplace_app_diagnosisproductmap`)"""
    keyword = models.CharField(max_length=100, blank=True, unique=True)
    label = models.CharField(max_length=150, blank=True)
    products = models.ManyToManyField('marketplace.Product', blank=True, related_name='+')

    def __str__(self):
        return str(self.keyword) if self.keyword else f'DiagnosisProductMap {self.pk}'


class ProductRecommendation(models.Model):
    """A product a physio recommended to a patient.  (live table `marketplace_app_patientproductrecommendation`)"""
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE, related_name='+')
    recommended_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        unique_together = [('patient', 'product')]

    def __str__(self):
        return str(self.note) if self.note else f'ProductRecommendation {self.pk}'


class AppOpenEvent(models.Model):
    """Patient mobile app opened on a day (analytics).  (live table `patient_app_appopenevent`)"""
    opened_on = models.DateField(default=timezone.localdate)
    first_opened_at = models.DateTimeField(default=timezone.now)
    ping_count = models.PositiveIntegerField(default=0)
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('patient', 'opened_on')]

    def __str__(self):
        return f'AppOpenEvent {self.pk}'


class PushSubscription(models.Model):
    """A patient device's web-push subscription.  (live table `patient_app_pushsubscription`)"""
    endpoint = models.CharField(max_length=500, blank=True)
    p256dh = models.CharField(max_length=255, blank=True)
    auth = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('patient', 'endpoint')]

    def __str__(self):
        return str(self.endpoint) if self.endpoint else f'PushSubscription {self.pk}'


class VideoClickEvent(models.Model):
    """A patient played an exercise video (analytics).  (live table `patient_app_videoclickevent`)"""
    exercise_id_in_library = models.IntegerField(default=0)
    exercise_name = models.CharField(max_length=200, blank=True)
    clicked_at = models.DateTimeField(default=timezone.now)
    prescription_exercise = models.ForeignKey('exercises.PrescriptionExercise', on_delete=models.CASCADE, related_name='+')

    def __str__(self):
        return str(self.exercise_name) if self.exercise_name else f'VideoClickEvent {self.pk}'


class ActivationCard(models.Model):
    """A printed card with a code that activates app access.  (live table `personal_account_activationcard`)"""
    code = models.CharField(max_length=20, blank=True, unique=True)
    qr_code = models.CharField(max_length=200, null=True, blank=True)
    duration_days = models.PositiveIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.code) if self.code else f'ActivationCard {self.pk}'


class PatientPhysioPairing(models.Model):
    """A patient paired with a physio (by QR, clinic or enterprise).  (live table `personal_account_patientphysiopairing`)"""
    source = models.CharField(max_length=20, blank=True)
    paired_at = models.DateTimeField(default=timezone.now)
    clinic = models.ForeignKey('clinics.Clinic', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    enterprise = models.ForeignKey('Enterprise', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')
    physio = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('patient', 'physio')]

    def __str__(self):
        return str(self.source) if self.source else f'PatientPhysioPairing {self.pk}'


class PatientConsultation(models.Model):
    """A doctor consultation noted on the patient's profile.  (live table `personal_account_patientconsultation`)"""
    doctor_name = models.CharField(max_length=255, blank=True)
    visit_date = models.DateField(default=timezone.localdate)
    notes = models.CharField(max_length=500, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.doctor_name) if self.doctor_name else f'PatientConsultation {self.pk}'


class PatientDietEntry(models.Model):
    """A diet / meal entry on the patient's profile.  (live table `personal_account_patientdietentry`)"""
    meal_time = models.CharField(max_length=10, blank=True)
    food_item = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.meal_time) if self.meal_time else f'PatientDietEntry {self.pk}'


class PatientSavedExercise(models.Model):
    """An exercise the patient saved for themselves.  (live table `personal_account_patientexercise`)"""
    created_at = models.DateTimeField(default=timezone.now)
    exercise = models.ForeignKey('exercises.ExerciseMain', on_delete=models.CASCADE, related_name='+')
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('patient', 'exercise')]

    def __str__(self):
        return f'PatientSavedExercise {self.pk}'


class PatientTestEntry(models.Model):
    """A special test reference attached to a patient.  (live table `personal_account_patientassessmententry`)"""
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')
    reference = models.ForeignKey('SpecialTestReference', on_delete=models.CASCADE, related_name='+')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        unique_together = [('patient', 'reference')]

    def __str__(self):
        return str(self.notes) if self.notes else f'PatientTestEntry {self.pk}'


class MedicineRx(models.Model):
    """A medicine prescription issued to a patient.  (live table `personal_account_rx`)"""
    custom_name = models.CharField(max_length=200, blank=True)
    dosage = models.CharField(max_length=100, blank=True)
    time_of_day = models.CharField(max_length=10, blank=True)
    start_date = models.DateField(default=timezone.localdate)
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=15, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')
    pharmacy_product = models.ForeignKey('marketplace.PharmacyProduct', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.custom_name) if self.custom_name else f'MedicineRx {self.pk}'


class RegionalAssessment(models.Model):
    """A body-region clinical assessment (observation, ROM, special tests).  (live table `assessment_app_regionalassessment`)"""
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    region = models.CharField(max_length=20, blank=True)
    chief_complaint = models.TextField(blank=True)
    observation = models.TextField(blank=True)
    range_of_motion = models.TextField(blank=True)
    palpation = models.TextField(blank=True)
    special_tests = models.TextField(blank=True)
    neurovascular_screen = models.TextField(blank=True)
    clinical_impression = models.TextField(blank=True)
    plan = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')

    def __str__(self):
        return str(self.region) if self.region else f'RegionalAssessment {self.pk}'


class SpecialTestReference(models.Model):
    """Reference card of an orthopaedic special test.  (live table `assessment_app_specialtestreference`)"""
    region = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=150, blank=True)
    purpose = models.CharField(max_length=255, blank=True)
    procedure = models.TextField(blank=True)
    positive_sign = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return str(self.region) if self.region else f'SpecialTestReference {self.pk}'


class TreatmentModality(models.Model):
    """A physical agent / modality (ultrasound, TENS...).  (live table `prescription_app_modality`)"""
    name = models.CharField(max_length=100, blank=True, unique=True)
    category = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return str(self.name) if self.name else f'TreatmentModality {self.pk}'


class TreatmentSession(models.Model):
    """A treatment session log (numbered, with response).  (live table `prescription_app_treatmentsession`)"""
    session_number = models.PositiveIntegerField(default=0)
    session_date = models.DateTimeField(default=timezone.now)
    pre_notes = models.TextField(null=True, blank=True)
    treatment_response = models.CharField(max_length=20, null=True, blank=True)
    session_note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('patient', 'session_number')]

    def __str__(self):
        return str(self.pre_notes) if self.pre_notes else f'TreatmentSession {self.pk}'


class TreatmentSessionModality(models.Model):
    """A modality used in a treatment session, with its parameters.  (live table `prescription_app_treatmentsessionmodality`)"""
    parameters = models.TextField(blank=True)
    modality = models.ForeignKey('TreatmentModality', on_delete=models.CASCADE, related_name='+')
    session = models.ForeignKey('TreatmentSession', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('session', 'modality')]

    def __str__(self):
        return str(self.parameters) if self.parameters else f'TreatmentSessionModality {self.pk}'


class Referral(models.Model):
    """A referral of a patient to another physio or clinic.  (live table `referral_app_referral`)"""
    referral_code = models.CharField(max_length=14, blank=True, unique=True)
    patient_name = models.CharField(max_length=100, blank=True)
    patient_contact = models.CharField(max_length=20, blank=True)
    patient_diagnosis = models.CharField(max_length=200, blank=True)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    patient = models.ForeignKey('accounts.Patient', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    referred_to = models.ForeignKey('accounts.ProfessionalProfile', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    referred_to_clinic = models.ForeignKey('clinics.Clinic', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    referred_by = models.ForeignKey('accounts.ProfessionalProfile', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return str(self.referral_code) if self.referral_code else f'Referral {self.pk}'


class SummitTable(models.Model):
    """A table at a training summit (facilitator PIN).  (live table `summit_app_table`)"""
    number = models.PositiveSmallIntegerField(default=0, unique=True)
    label = models.CharField(max_length=50, blank=True)
    pin_hash = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    claimed_at = models.DateTimeField(null=True, blank=True)
    is_claimed = models.BooleanField(default=False)
    pin = models.CharField(max_length=10, blank=True)

    def __str__(self):
        return str(self.label) if self.label else f'SummitTable {self.pk}'


class SummitSession(models.Model):
    """A summit table's submission.  (live table `summit_app_sessionsubmission`)"""
    session_key = models.CharField(max_length=20, blank=True)
    facilitator_name = models.CharField(max_length=100, blank=True)
    data = models.TextField(blank=True)
    current_step = models.PositiveSmallIntegerField(default=0)
    is_complete = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    table = models.ForeignKey('SummitTable', on_delete=models.CASCADE, related_name='+')

    class Meta:
        unique_together = [('table', 'session_key')]

    def __str__(self):
        return str(self.session_key) if self.session_key else f'SummitSession {self.pk}'


class ApkRelease(models.Model):
    """A published Android app build.  (live table `upload_app_apkrelease`)"""
    version = models.CharField(max_length=20, blank=True)
    file = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now)
    is_latest = models.BooleanField(default=False)
    release_notes = models.TextField(blank=True)

    def __str__(self):
        return str(self.version) if self.version else f'ApkRelease {self.pk}'


class VisitNote(models.Model):
    """The live site's detailed visit note (70 fields).  (live table `visit_notes_app_visitnote`)"""
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    chief_complaint_today = models.TextField(blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    pain_at_rest = models.BooleanField(default=False)
    pain_with_activity = models.BooleanField(default=False)
    pain_worst_24hr = models.BooleanField(default=False)
    pain_quality_location = models.TextField(blank=True)
    hep_adherence = models.CharField(max_length=3, blank=True)
    hep_adherence_reason = models.CharField(max_length=255, blank=True)
    changes_since_last_visit = models.CharField(max_length=10, blank=True)
    changes_description = models.TextField(blank=True)
    current_function_adls = models.TextField(blank=True)
    medication_changes = models.TextField(blank=True)
    new_concerns_alerts = models.TextField(blank=True)
    vitals_hr = models.CharField(max_length=20, blank=True)
    vitals_bp = models.CharField(max_length=20, blank=True)
    vitals_rr = models.CharField(max_length=20, blank=True)
    rom_active = models.TextField(blank=True)
    rom_passive = models.TextField(blank=True)
    strength_mmt = models.TextField(blank=True)
    palpation_swelling = models.TextField(blank=True)
    special_tests = models.TextField(blank=True)
    functional_test_baseline = models.TextField(blank=True)
    outcome_measure = models.CharField(max_length=255, blank=True)
    primary_impairment_today = models.TextField(blank=True)
    contraindications_precautions = models.TextField(blank=True)
    patient_goals_session = models.TextField(blank=True)
    post_pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    post_rom = models.TextField(blank=True)
    post_strength = models.TextField(blank=True)
    post_functional_test = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='+')
    case_type = models.CharField(max_length=10, blank=True)
    geri_appetite = models.CharField(max_length=100, blank=True)
    geri_bp_seated = models.CharField(max_length=30, blank=True)
    geri_bp_standing_post = models.CharField(max_length=30, blank=True)
    geri_bp_standing_pre = models.CharField(max_length=30, blank=True)
    geri_cognition = models.CharField(max_length=100, blank=True)
    geri_dyspnea_borg_post = models.CharField(max_length=10, blank=True)
    geri_dyspnea_borg_pre = models.CharField(max_length=10, blank=True)
    geri_new_medications = models.TextField(blank=True)
    geri_orthostatic_dizziness_post = models.BooleanField(default=False)
    geri_orthostatic_dizziness_pre = models.BooleanField(default=False)
    geri_patient_report_post = models.TextField(blank=True)
    geri_recovery_vitals = models.CharField(max_length=100, blank=True)
    geri_skin_check_pre = models.TextField(blank=True)
    geri_spo2_post = models.CharField(max_length=10, blank=True)
    geri_spo2_pre = models.CharField(max_length=10, blank=True)
    geri_tug_post = models.CharField(max_length=20, blank=True)
    geri_tug_pre = models.CharField(max_length=20, blank=True)
    neuro_balance_sitting = models.CharField(max_length=100, blank=True)
    neuro_balance_standing = models.CharField(max_length=100, blank=True)
    neuro_bladder_bowel_status = models.TextField(blank=True)
    neuro_fatigue_level = models.PositiveSmallIntegerField(null=True, blank=True)
    neuro_fatigue_post = models.PositiveSmallIntegerField(null=True, blank=True)
    neuro_gait_post = models.TextField(blank=True)
    neuro_gait_pre = models.TextField(blank=True)
    neuro_motor_control = models.TextField(blank=True)
    neuro_sensation = models.TextField(blank=True)
    neuro_skin_check_post = models.TextField(blank=True)
    neuro_skin_check_pre = models.TextField(blank=True)
    neuro_spasm_frequency = models.TextField(blank=True)
    neuro_tone_post = models.TextField(blank=True)
    neuro_tone_pre = models.TextField(blank=True)
    treatment_provided = models.TextField(blank=True)

    def __str__(self):
        return str(self.chief_complaint_today) if self.chief_complaint_today else f'VisitNote {self.pk}'
