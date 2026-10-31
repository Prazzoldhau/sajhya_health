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
from billing import catalog
from clinics.login import set_clinic_login, set_staff_login
from clinics.models import Clinic, ClinicMember, ClinicSubscription, QueueEntry

CLINIC_NAME = 'Bhaktapur Speech and Hearing Center'
PREFIX = 'qa-bshc-'
MARK = 'QA seed'

# department, profession, title, name shown, username prefix, how many therapists. The first of each keeps the plain username (qa-bshc-ot), the rest are ot2, ot3...
TEAMS = [
    ('Occupational Therapy', 'occupational therapist', 'OT', 'Occupational Therapist', 'ot', 4),
    ('Speech Therapy', 'speech therapist', 'SLP', 'Speech Therapist', 'speech', 4),
    ('Physiotherapy', 'physiotherapist', 'PT', 'Physiotherapist', 'physio', 4),
    ('Behaviour Therapy', 'behaviour therapist', 'BT', 'Behaviour Therapist', 'behaviour', 1),
]
# (username suffix, profession, title, name shown, department)
THERAPISTS = [(prefix if i == 0 else f'{prefix}{i + 1}', profession, title, name if i == 0 else f'{name} {i + 1}', department)
              for department, profession, title, name, prefix, count in TEAMS for i in range(count)]
DEPARTMENTS = [team[0] for team in TEAMS]
PATIENTS = ['QA Patient Aarav', 'QA Patient Bina', 'QA Patient Chiran', 'QA Patient Dipa', 'QA Patient Eshan', 'QA Patient Fulmaya', 'QA Patient Gita', 'QA Patient Hari',
            'QA Patient Ishan', 'QA Patient Jamuna', 'QA Patient Kiran', 'QA Patient Laxmi']


def new_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            return value


class Command(BaseCommand):
    help = 'Create (or remove) the mock QA clinic: Bhaktapur Speech and Hearing Center, with 13 therapists (4 occupational, 4 speech, 4 physiotherapy, 1 behaviour), a clinic login, a receptionist and sample appointments.'

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
            departments = {name: Department.objects.get_or_create(professional=workspace, name=name)[0] for name in DEPARTMENTS}
            members = self.therapists(clinic)
            for name, team in members.items():  # each therapist works in their own department
                for member in team:
                    member.departments.set([departments[name]])
            for department in departments.values():  # and each department has its own services to bill from (starting prices, editable)
                catalog.seed_suggested(workspace, department)
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
        """The verified therapists, each a member of the clinic with a login of their own. Returns {department name: [ClinicMember, ...]}."""
        members = {name: [] for name in DEPARTMENTS}
        for number, (suffix, profession_name, title, role_name, department) in enumerate(THERAPISTS, start=1):
            user, _ = self.user(suffix, f'{role_name} (verified therapist)')
            profession = Profession.objects.get_or_create(name=profession_name)[0]
            profile = self.profile(user, profession, 'QA', role_name, title, '98000002' + str(number).zfill(2))
            member, _ = ClinicMember.objects.get_or_create(clinic=clinic, physio=profile, defaults={'role': ClinicMember.PHYSIO, 'status': ClinicMember.ACTIVE, 'joined_at': timezone.now()})
            if member.status != ClinicMember.ACTIVE:
                member.status = ClinicMember.ACTIVE
                member.save(update_fields=['status'])
            members[department].append(member)
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
            patient = workspace.workspace_patients().filter(name=name).first() or Patient.objects.create(
                professional=workspace, clinic=clinic, name=name, phone=f'98000004{i:02d}', gender='M' if i % 2 == 0 else 'F',
                date_of_birth=datetime.date(2016 - i, 3, 4), registered_by_name='QA seed', registered_by_role='Clinic login', status=Patient.ACTIVE)
            patients.append(patient)
        return patients

    def appointments(self, workspace, patients, departments, members):
        """Today and tomorrow for every therapist, plus 1:30 pm today shared by the first two of each department (and every department at once)."""
        Appointment.objects.filter(professional=workspace, notes=MARK).delete()
        today = timezone.localdate()
        n = 0

        def book(day_offset, hour, minute, department, member):
            nonlocal n
            start = timezone.make_aware(datetime.datetime.combine(today + datetime.timedelta(days=day_offset), datetime.time(hour, minute)))
            Appointment.objects.create(professional=workspace, patient=patients[n % len(patients)], start=start, end=start + datetime.timedelta(minutes=45),
                                       department=departments[department], practitioner=member, session_type='treatment', notes=MARK)
            patients[n % len(patients)].assigned.add(member)  # booked with them, so assigned to them
            n += 1

        for department, team in members.items():
            for j, member in enumerate(team):
                first = 9 * 60 + 75 * j  # 9:00, 10:15, 11:30, 12:45
                book(0, first // 60, first % 60, department, member)
                later = 10 * 60 + 60 * j  # tomorrow 10:00, 11:00, 12:00, 13:00
                book(1, later // 60, later % 60, department, member)
                if j < 2:
                    book(0, 13, 30, department, member)

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
        out('13 therapists: 4 occupational, 4 speech, 4 physiotherapy and 1 behaviour. Each opens "My schedule" for the appointments booked with them (today and tomorrow).')
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
