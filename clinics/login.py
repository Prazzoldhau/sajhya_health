"""The clinic's own sign-in. A clinic login is a normal user whose workspace profile belongs to the clinic, so every
workspace screen (patients, appointments, billing, plans, assessments, reports) works for it unchanged. The owning
physiotherapist chooses the username and password and can change them at any time."""
from django.contrib.auth.models import User
from django.db import transaction

from accounts.models import Account, ProfessionalProfile


@transaction.atomic
def set_clinic_login(clinic, username, password):
    """Create the clinic's sign-in, or change its username and password. Returns the user."""
    if clinic.workspace_id:
        user = clinic.workspace.account.user
        user.username = username
        user.set_password(password)
        user.is_active = True
        user.save()
        return user
    user = User.objects.create_user(username=username, password=password)
    account = Account.objects.create(user=user, account_type=Account.CLINIC, organization_name=clinic.name)
    profile = ProfessionalProfile.objects.create(
        account=account, status=ProfessionalProfile.APPROVED, completed_step=5, first_name=clinic.name[:100], last_name='',
        mobile=clinic.phone, title='Clinic', practice_name=clinic.name, practice_address=clinic.address, practice_phone=clinic.phone)
    clinic.workspace = profile
    clinic.save(update_fields=['workspace'])
    return user


@transaction.atomic
def set_staff_login(member, username, password):
    """Give a staff member a sign-in, or change its username and password. Returns the user."""
    if member.user_id:
        user = member.user
        user.username = username
        user.set_password(password)
        user.is_active = True
        user.save()
        return user
    user = User.objects.create_user(username=username, password=password)
    Account.objects.create(user=user, account_type=Account.STAFF, organization_name=member.clinic.name)
    member.user = user
    member.save(update_fields=['user'])
    return user


def close_staff_login(member):
    """Removing someone from the team also stops them signing in."""
    if member.user_id:
        member.user.is_active = False
        member.user.save(update_fields=['is_active'])
