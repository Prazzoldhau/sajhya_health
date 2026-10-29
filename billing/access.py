"""Who is billing: a professional in their own workspace, or a front-desk staff member (reception, manager) billing for their clinic.

The same billing screens serve both. For front-desk staff the "workspace" is the clinic's own workspace (its bills and money), they may only
work with patients registered under that clinic, every bill is stamped with their name and role, and they see the front-desk menu instead of
the clinical one. Hard deletes and the price list are for managers only; the plan must be active before anything is changed.
"""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse

from accounts.access import own_patient, require_workspace, workspace_context, workspace_profile
from accounts.models import Account
from clinics.models import ClinicMember


def staff_member(request):
    """The signed-in front-desk staff member, or None when the user is a professional (or anyone else)."""
    if hasattr(request, '_billing_staff'):
        return request._billing_staff
    member = None
    account = getattr(request.user, 'account', None)
    if account is not None and account.account_type == Account.STAFF:
        member = ClinicMember.objects.filter(user=request.user, physio__isnull=True, status=ClinicMember.ACTIVE).select_related('clinic', 'clinic__workspace').first()
    request._billing_staff = member
    return member


def _desk_profile(request, member):
    clinic = member.clinic
    if not clinic.is_active or not member.can('billing') or clinic.workspace_id is None:
        raise Http404
    if request.method not in ('GET', 'HEAD') and not clinic.is_usable:
        raise PermissionDenied("The clinic's plan is not active, so billing is paused.")
    return clinic.workspace


def billing_profile(request):
    """The workspace whose bills this page shows (None until a professional is approved)."""
    member = staff_member(request)
    return _desk_profile(request, member) if member else workspace_profile(request)


def billing_require(request):
    member = staff_member(request)
    return _desk_profile(request, member) if member else require_workspace(request)


def billing_patient(request, pk):
    """(workspace, patient) for a patient the signed-in person may bill: their own or the clinic's, and for staff only the clinic's."""
    member = staff_member(request)
    if member:
        return _desk_profile(request, member), get_object_or_404(member.clinic.patients.select_related('clinic'), pk=pk)
    return own_patient(request, pk)


def billing_manager(request):
    """Deleting bills and editing the price list: professionals, and the clinic's manager, but not other staff."""
    member = staff_member(request)
    if member is not None and not member.can('team'):
        raise Http404


def billing_context(request, profile):
    """The template context of every billing page: the workspace context, plus the front-desk layout for staff."""
    from clinics.desk import TABS
    context = workspace_context(request.user, profile)
    member = staff_member(request)
    context['patient_search_url'] = reverse('accounts:appointment-patient-search')
    if member is not None:
        name = member.name or request.user.get_username()
        context.update({
            'staff_mode': True, 'base_template': 'clinics/desk_shell.html', 'display_name': name, 'initials': ''.join(w[0] for w in name.split()[:2]).upper() or 'ST',
            'role': member.get_role_display(), 'desk_member': member, 'desk_tabs': [(key, label) for key, label, perm in TABS if member.can(perm)],
            'patient_search_url': reverse('clinics:desk-patient-search'), 'hide_prices': not member.can('team'), 'workspace_clinic': None,
        })
    return context
