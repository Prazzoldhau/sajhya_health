"""Who may do what with a clinic. Records of clinics a professional has nothing to do with answer 404."""
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.access import require_workspace

from .models import Clinic, ClinicMember, ClinicSubscription


def _plan_is_active():
    """Clinics whose owner's Clinic plan is active (and not past its expiry date)."""
    return Q(owner__clinic_subscription__status=ClinicSubscription.ACTIVE) & (
        Q(owner__clinic_subscription__expires_at__isnull=True) | Q(owner__clinic_subscription__expires_at__gte=timezone.localdate()))


def clinics_of(profile):
    """Usable clinics this professional owns or belongs to as an active physio (used for tagging patients)."""
    return Clinic.objects.filter(is_active=True).filter(_plan_is_active()).filter(
        Q(owner=profile) | Q(workspace=profile) | Q(members__physio=profile, members__status=ClinicMember.ACTIVE)).distinct()


def resolve_clinic(profile, value):
    """The clinic a posted id refers to, if this professional may use it; otherwise None (never trust the posted id)."""
    if not str(value or '').isdigit():
        return None
    return clinics_of(profile).filter(pk=int(value)).first()


def clinic_allowance(profile):
    """How many clinics this professional may have: the plan's limit once active; one pending registration before that."""
    sub = ClinicSubscription.objects.filter(professional=profile).first()
    return sub.clinic_limit if sub and sub.is_active else 1


def clinic_for_member(request, pk):
    """(profile, clinic, is_owner) for the owner or an active physio of the clinic; 404 for anyone else."""
    profile = require_workspace(request)
    clinic = get_object_or_404(Clinic, pk=pk)
    if clinic.owner_id == profile.pk or clinic.workspace_id == profile.pk:  # the clinic's own login runs the clinic like its owner
        return profile, clinic, True
    if clinic.is_active and clinic.members.filter(physio=profile, status=ClinicMember.ACTIVE).exists():
        return profile, clinic, False
    raise Http404


def clinic_for_owner(request, pk):
    profile = require_workspace(request)
    return profile, get_object_or_404(Clinic.objects.filter(Q(owner=profile) | Q(workspace=profile)), pk=pk)
