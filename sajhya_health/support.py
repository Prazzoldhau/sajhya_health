"""The platform operator's support screens. They show how a clinic is doing (counts, dates, patient CODES, bill numbers and amounts) and never a patient's
name, phone number, address or any note text, so help can be given without reading anyone's records. Every page opened here is written to the clinic's access
log, and the clinic owner is e-mailed when their workspace is opened. Platform staff need two-step sign-in (REQUIRE_STAFF_MFA) to reach these pages."""
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from accounts import audit
from accounts.access import staff_required
from accounts.messaging import email_ready
from accounts.models import Patient, ProfessionalProfile

log = logging.getLogger('sajhya.support')


@login_required
@staff_required
def overview(request):
    audit.log_access(request, 'support', detail='opened the support overview', operator=True)
    workspaces = ProfessionalProfile.objects.annotate(n_patients=Count('patients', distinct=True)).order_by('-n_patients', 'id')[:200]
    rows = [{'id': p.pk, 'practice': p.practice_name or p.full_name, 'status': p.get_status_display(), 'patients': p.n_patients, 'clinic_login': getattr(p, 'clinic_workspace', None) is not None}
            for p in workspaces]
    return render(request, 'support/overview.html', {'rows': rows})


@login_required
@staff_required
def workspace(request, profile_id):
    profile = get_object_or_404(ProfessionalProfile, pk=profile_id)
    clinic = getattr(profile, 'clinic_workspace', None)
    row = audit.log_access(request, 'support', workspace=profile, clinic=clinic, detail='opened the support view of this workspace', operator=True, dedupe=True)
    if row is not None:  # a new line (not a repeat within ten minutes): tell the owner
        owner = clinic.owner if clinic is not None else profile
        address = getattr(getattr(getattr(owner, 'account', None), 'user', None), 'email', '')
        if address and email_ready():
            try:
                send_mail('Sajhya support opened your workspace overview',
                          f'Hello,\n\nA Sajhya Health support account opened the support overview of your workspace ({profile.practice_name or profile.full_name}) '
                          f'at {audit.now_text()}. It shows patient codes and counts only, never names or notes. You can see every access on the Access log page in Settings.\n\n'
                          'If you did not expect this, reply to this message.', settings.DEFAULT_FROM_EMAIL, [address], fail_silently=True)
            except Exception:  # noqa: BLE001
                log.exception('support notice e-mail failed')
    patients = (Patient.objects.filter(Q(professional=profile) | Q(clinic__workspace=profile))  # scope-ok: a support view of one workspace, codes and counts only
                .annotate(n_visits=Count('visits', distinct=True), n_notes=Count('soap_notes', distinct=True), n_bills=Count('billing_entries', distinct=True),
                          n_prescriptions=Count('prescriptions', distinct=True)).order_by('-created_at', '-id')[:300])
    rows = [{'code': p.patient_code or f'#{p.pk}', 'status': p.get_status_display(), 'created': p.created_at, 'last_visit': p.last_visit, 'visits': p.n_visits, 'notes': p.n_notes,
             'bills': p.n_bills, 'prescriptions': p.n_prescriptions} for p in patients]
    from billing.models import BillingEntry
    bills = [{'invoice': b.invoice_number, 'date': b.entry_date, 'amount': b.rate, 'paid': b.amount_paid, 'cancelled': b.is_cancelled}
             for b in BillingEntry.objects.filter(professional=profile).order_by('-entry_date', '-id')[:30]]
    return render(request, 'support/workspace.html', {'profile': profile, 'clinic': clinic, 'rows': rows, 'bills': bills})
