"""Who may see what - the helpers every workspace view uses, in one place.

Rules, so they are applied the same way everywhere:
- Only the signed-in professional who owns a record may open or change it. Anything else answers 404 (not 403), so
  the response does not reveal that the record exists.
- Exception: patients registered under a clinic (patient.clinic) are shared by that clinic's team (the owner and its
  active physios). Their contact details (phone, email, address) are visible to the clinic owner only - see can_see_contact().
- A professional whose credentials are not APPROVED (draft, submitted or rejected) has no workspace: workspace_profile()
  is None and require_workspace() answers 403. accounts/middleware.py enforces the same rule on whole URL prefixes.
"""
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Patient, ProfessionalProfile

staff_required = user_passes_test(lambda u: u.is_active and u.is_staff, login_url='accounts:login')


def own_profile(request):
    """The signed-in user's professional profile; 404 for accounts that have none (clients, clinics...)."""
    profile = getattr(getattr(request.user, 'account', None), 'profile', None)
    if profile is None:
        raise Http404
    return profile


def workspace_profile(request):
    """The profile if the professional is APPROVED, else None (the caller redirects to the welcome page, which
    shows where they are in the verification process)."""
    profile = own_profile(request)
    return profile if profile.status == ProfessionalProfile.APPROVED else None


def require_workspace(request):
    """Like workspace_profile but for JSON/POST endpoints and anything that cannot redirect: 403 until approved."""
    profile = own_profile(request)
    if profile.status != ProfessionalProfile.APPROVED:
        raise PermissionDenied('Credentials not verified yet.')
    return profile


def accessible_patients(profile):
    """Patients this professional may open: their own plus those of the clinics they own or work at."""
    from clinics.access import clinics_of
    return Patient.objects.filter(Q(professional=profile) | Q(clinic__in=clinics_of(profile))).distinct()


def own_patient(request, pk):
    """(profile, patient) for a patient the signed-in professional may open (their own, or their clinic's), else 404."""
    profile = require_workspace(request)
    return profile, get_object_or_404(accessible_patients(profile).select_related('clinic'), pk=pk)


def can_see_contact(profile, patient):
    """Phone, email and address of a clinic-registered patient are for the clinic owner only; everyone else sees them
    only on patients that are not tied to a clinic."""
    return patient.clinic_id is None or profile.pk in (patient.clinic.owner_id, patient.clinic.workspace_id)


def first_error(form, default='Please check the form.'):
    """The first validation message of a form, for showing in a single flash message."""
    for errors in form.errors.values():
        return errors[0]
    return default


def workspace_context(user, profile):
    """Template context shared by every page of the workspace (name, initials, role for the header)."""
    display_name = profile.full_name or user.get_username()
    initials = ''.join(p[0] for p in (profile.first_name, profile.last_name) if p).upper() or user.get_username()[:2].upper()
    from clinics.models import ClinicMember
    return {'workspace_clinic': getattr(profile, 'clinic_workspace', None), 'profile': profile, 'display_name': display_name, 'first_name': profile.first_name,
            'initials': initials, 'role': profile.account.profession or profile.title,
            'clinic_invites': ClinicMember.objects.filter(physio=profile, status=ClinicMember.INVITED).count()}
