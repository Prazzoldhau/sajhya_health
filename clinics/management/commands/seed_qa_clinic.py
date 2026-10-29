"""Set up a mock clinic for QA, or remove it again.

    python manage.py seed_qa_clinic              create (or top up) the mock clinic and print the sign-ins
    python manage.py seed_qa_clinic --reset-passwords   also give every QA sign-in a new password
    python manage.py seed_qa_clinic --remove     delete everything this command created (only the qa-bshc-* sign-ins and their clinic)

Safe to run again: nothing is duplicated, passwords are left alone unless --reset-passwords is given, and the sample appointments are
moved to today and tomorrow. Passwords are generated here and printed once; they are not stored anywhere else.
"""
import datetime
import secrets
import string

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Account, Appointment, Department, Patient, Profession, ProfessionalProfile
from clinics.login import set_clinic_login, set_staff_login
from clinics.models import Clinic, ClinicMember, ClinicSubscription, QueueEntry

CLINIC_NAME = 'Bhaktapur Speech and Hearing Center'
PREFIX = 'qa-bshc-'
MARK = 'QA seed'

# username suffix, profession, title, last name shown, department they work in
THERAPISTS = [
    ('ot', 'occupational therapist', 'OT', 'Occupational Therapist', 'Occupational Therapy'),
    ('speech', 'speech therapist', 'SLP', 'Speech Therapist', 'Speech Therapy'),
    ('physio', 'physiotherapist', 'PT', 'Physiotherapist', 'Physiotherapy'),
    ('behaviour', 'behaviour therapist', 'BT', 'Behaviour Therapist', 'Behaviour Therapy'),
]
PATIENTS = ['QA Patient Aarav', 'QA Patient Bina', 'QA Patient Chiran', 'QA Patient Dipa', 'QA Patient Eshan', 'QA Patient Fulmaya', 'QA Patient Gita', 'QA Patient Hari']


def new_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            return value


class Command(BaseCommand):
    help = 'Create (or remove) the mock QA clinic: Bhaktapur Speech and Hearing Center, with four therapists, a clinic login, a receptionist and sample appointments.'

    def add_arguments(self, parser):
        parser.add_argument('--remove', action='store_true', help='Delete everything this command created.')
        parser.add_argument('--reset-passwords', action='store_true', help='Give every QA sign-in a new password (printed once).')

    def handle(self, *args, **options):
        if options['remove']:
            return self.remove()
        self.passwords = {}
        self.reset = options['reset_passwords']
        with transaction.atomic():
            owner = self.owner()
            clinic = self.clinic(owner)
            self.clinic_login(clinic)
            workspace = clinic.workspace
            departments = {name: Department.objects.get_or_create(professional=workspace, name=name)[0] for *_, name in THERAPISTS}
            members = self.therapists(clinic)
            self.receptionist(clinic)
            patients = self.patients(clinic, workspace)
            self.appointments(workspace, patients, departments, members)
        self.report(clinic)

    # ------------------------------------------------------------ people
    def user(self, suffix, label):
        """(user, created); a new password is set when the user is new or --reset-passwords was given."""
        username = PREFIX + suffix
        user, created = User.objects.get_or_create(username=username, defaults={'email': f'{username}@example.invalid', 'is_active': True})
        if created or self.reset:
            password = new_password()
            user.set_password(password)
            user.is_active = True
            user.save()
            self.passwords[username] = (label, password)
        else:
            self.passwords.setdefault(username, (label, None))
        return user, created

    def profile(self, user, profession, first, last, title, mobile):
        account, _ = Account.objects.get_or_create(user=user, defaults={'account_type': Account.PROFESSIONAL})
        account.profession = profession
        account.save()
        profile, _ = ProfessionalProfile.objects.get_or_create(account=account, defaults=dict(
            first_name=first, last_name=last, mobile=mobile, title=title, status=ProfessionalProfile.APPROVED, completed_step=5,
            license_number='QA-0000', issuing_authority='QA (not a real licence)'))
        if profile.status != ProfessionalProfile.APPROVED:
            profile.status = ProfessionalProfile.APPROVED
            profile.save(update_fields=['status'])
        return profile

    def owner(self):
        user, _ = self.user('owner', 'Clinic owner (a physiotherapist)')
        profession = Profession.objects.get_or_create(name='physiotherapist')[0]
        profile = self.profile(user, profession, 'QA', 'Clinic Owner', 'PT', '9800000100')
        ClinicSubscription.objects.update_or_create(professional=profile, defaults={
            'status': ClinicSubscription.ACTIVE, 'clinic_limit': 3, 'expires_at': None, 'request_note': 'QA clinic', 'activated_at': timezone.now()})
        return profile

    def clinic(self, owner):
        clinic, _ = Clinic.objects.get_or_create(owner=owner, name=CLINIC_NAME, defaults=dict(
            phone='9800000101', province='Bagmati', district='Bhaktapur', ward_street='QA test clinic, not a real address', slot_minutes=30,
            short_bio='Mock clinic for QA. Not a real clinic.', hours={day: ['09:00', '17:00'] for day in ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday')}))
        return clinic

    def clinic_login(self, clinic):
        """The clinic's own sign-in (its workspace: appointments, billing, patients)."""
        username, label = PREFIX + 'clinic', 'The clinic itself (appointments, billing, patients)'
        if clinic.workspace_id and not self.reset:
            self.passwords[username] = (label, None)
            return
        password = new_password()
        set_clinic_login(clinic, username, password)
        clinic.refresh_from_db()
        self.passwords[username] = (label, password)

    def therapists(self, clinic):
        """The four verified therapists, each a member of the clinic with a login of their own. Returns {department name: ClinicMember}."""
        members = {}
        for suffix, profession_name, title, role_name, department in THERAPISTS:
            user, _ = self.user(suffix, f'{role_name} (verified therapist)')
            profession = Profession.objects.get_or_create(name=profession_name)[0]
            profile = self.profile(user, profession, 'QA', role_name, title, '98000002' + str(len(members) + 1).zfill(2))
            member, _ = ClinicMember.objects.get_or_create(clinic=clinic, physio=profile, defaults={'role': ClinicMember.PHYSIO, 'status': ClinicMember.ACTIVE, 'joined_at': timezone.now()})
            if member.status != ClinicMember.ACTIVE:
                member.status = ClinicMember.ACTIVE
                member.save(update_fields=['status'])
            members[department] = member
        return members

    def receptionist(self, clinic):
        member, _ = ClinicMember.objects.get_or_create(clinic=clinic, role=ClinicMember.RECEPTIONIST, name='QA Receptionist',
                                                       defaults={'status': ClinicMember.ACTIVE, 'phone': '9800000300', 'joined_at': timezone.now()})
        username, label = PREFIX + 'reception', 'Receptionist (front desk)'
        if member.user_id and not self.reset:
            self.passwords[username] = (label, None)
            return
        password = new_password()
        set_staff_login(member, username, password)
        self.passwords[username] = (label, password)

    # ------------------------------------------------------------ sample data
    def patients(self, clinic, workspace):
        patients = []
        for i, name in enumerate(PATIENTS):
            patient = Patient.objects.filter(professional=workspace, name=name).first() or Patient.objects.create(
                professional=workspace, clinic=clinic, name=name, phone=f'98000004{i:02d}', gender='M' if i % 2 == 0 else 'F',
                date_of_birth=datetime.date(2016 - i, 3, 4), registered_by_name='QA seed', registered_by_role='Clinic login', status=Patient.ACTIVE)
            patients.append(patient)
        return patients

    def appointments(self, workspace, patients, departments, members):
        """Today and tomorrow, two or three per therapist, and one time (1:30 pm) shared by all four departments."""
        Appointment.objects.filter(professional=workspace, notes=MARK).delete()
        today = timezone.localdate()
        order = [d for *_, d in THERAPISTS]
        slots = [(0, '13:30', 0), (0, '13:30', 1), (0, '13:30', 2), (0, '13:30', 3), (0, '10:00', 0), (0, '11:00', 1), (0, '15:00', 2), (0, '16:00', 3),
                 (1, '10:30', 0), (1, '11:30', 1), (1, '12:00', 2), (1, '14:00', 3)]
        for n, (day_offset, hhmm, who) in enumerate(slots):
            department = order[who]
            start = timezone.make_aware(datetime.datetime.combine(today + datetime.timedelta(days=day_offset), datetime.time.fromisoformat(hhmm)))
            Appointment.objects.create(professional=workspace, patient=patients[n % len(patients)], start=start, end=start + datetime.timedelta(minutes=45),
                                       department=departments[department], practitioner=members[department], session_type='treatment', notes=MARK)

    # ------------------------------------------------------------ output
    def report(self, clinic):
        out = self.stdout.write
        out('')
        out(self.style.SUCCESS(f'{CLINIC_NAME} is ready (code {clinic.code}).'))
        out('')
        out('Sign in at the normal login page with:')
        for username, (label, password) in sorted(self.passwords.items()):
            out(f'  {username:<22} {password or "(unchanged: use --reset-passwords for a new one)":<16} {label}')
        out('')
        out('Each therapist opens "My schedule" for the appointments booked with them (today and tomorrow).')
        out('The clinic login opens Appointments to book, edit and see all four departments.')
        out(f'Remove everything later with:  python manage.py seed_qa_clinic --remove')

    def remove(self):
        with transaction.atomic():
            clinics = Clinic.objects.filter(name=CLINIC_NAME, owner__account__user__username__startswith=PREFIX)
            names = list(clinics.values_list('name', flat=True))
            users = User.objects.filter(username__startswith=PREFIX)
            count = users.count()
            clinics.delete()
            users.delete()
        self.stdout.write(self.style.SUCCESS(f'Removed {len(names)} QA clinic and {count} QA sign-in(s), with their patients, appointments and bills.'))
