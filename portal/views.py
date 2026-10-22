import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import own_patient
from accounts.models import Appointment, Patient, TreatmentPlan
from exercises.models import ExerciseFeedback, Prescription, PrescriptionExercise

from .models import MAX_ATTEMPTS_PER_INVITE, PatientLink, PortalInvite, hash_code

LINK_FAILURES, LINK_WINDOW = 6, 15 * 60  # per signed-in account: 6 wrong tries, then 15 minutes' pause
GENERIC_FAIL = 'That code and date of birth do not match, or the code has expired. Ask your physiotherapist for a new code.'


# ------------------------------------------------------------------ the patient's dashboard

SECTIONS = {'home': 'overview', 'plan': 'plan', 'exercises': 'exercises', 'advice': 'advice'}


def _page(request, section, template='portal/page.html', **extra):
    """Everything the dashboard shell needs: the account's linked records, the chosen one and (for treatment pages) its content.
    The patient is picked with ?p=<id> but only ever from this account's own links."""
    links = list(request.user.patient_links.select_related('patient', 'patient__clinic'))
    chosen = next((l.patient for l in links if str(l.patient_id) == request.GET.get('p')), links[0].patient if links else None)
    context = {'section': section, 'links': links, 'patient': chosen, 'today': timezone.localdate(), 'feedback_choices': ExerciseFeedback.FEEDBACK_CHOICES}
    if chosen and section in ('home', 'plan', 'exercises', 'advice'):
        plan = chosen.plans.filter(status=TreatmentPlan.ACTIVE).prefetch_related('phases__items', 'goals', 'measures__readings').first()
        prescription = chosen.prescriptions.filter(status=Prescription.ACTIVE).prefetch_related('exercises__exercise__step_images', 'exercises__feedback_logs').first()
        context.update({'plan': plan, 'prescription': prescription})
        if section == 'home':
            context['next_appointment'] = chosen.appointments.filter(kind=Appointment.APPOINTMENT, status=Appointment.SCHEDULED, start__gte=timezone.now()).order_by('start').first()
        if plan:
            phases = list(plan.phases.all())
            for phase in phases:
                phase.clinic_items = [i for i in phase.items.all() if i.kind == 'clinic']
                phase.hep_items = [i for i in phase.items.all() if i.kind == 'hep']
            context.update({'phases': phases, 'goals': list(plan.goals.all()), 'measures': list(plan.measures.all()), 'current_week': plan.current_week, 'total_weeks': plan.total_weeks})
    if section == 'home':
        from lab.models import LabTestRequest
        from marketplace.models import Order
        context['latest_order'] = Order.objects.filter(user=request.user).first()
        context['latest_booking'] = LabTestRequest.objects.filter(user=request.user).first()
    context.update(extra)
    return render(request, template, context)


@login_required
def home(request):
    old_tab = {'plan': 'portal:plan', 'exercises': 'portal:exercises', 'advice': 'portal:advice'}.get(request.GET.get('tab'))
    if old_tab:  # links from before the dashboard had its own pages
        return redirect(f"{reverse(old_tab)}?p={request.GET.get('p', '')}" if request.GET.get('p') else reverse(old_tab))
    return _page(request, 'home')


@login_required
def plan(request):
    return _page(request, 'plan')


@login_required
def exercises(request):
    return _page(request, 'exercises')


@login_required
def advice(request):
    return _page(request, 'advice')


@login_required
def services(request):
    return _page(request, 'services')


ORDER_STATUS_TONE = {'pending': 'warn', 'cancelled': 'bad', 'delivered': '', 'completed': '', 'confirmed': '', 'processing': '', 'shipped': '', 'sample_collected': ''}


@login_required
def orders(request):
    """Pharmacy and marketplace orders placed from this account."""
    from marketplace.catalogs import CATALOGS
    from marketplace.models import Order
    rows = [{'order': o, 'url': reverse(CATALOGS[o.order_type].urls['success'], args=[o.order_number]), 'items': list(o.items.all()),
             'tone': ORDER_STATUS_TONE.get(o.status, '')} for o in Order.objects.filter(user=request.user).prefetch_related('items')]
    return _page(request, 'orders', orders=rows)


@login_required
def lab_bookings(request):
    """Lab test bookings made from this account."""
    from lab.models import LabTestRequest
    rows = [{'booking': b, 'url': reverse('lab:order-success', args=[b.request_number]), 'items': list(b.items.all()),
             'tone': ORDER_STATUS_TONE.get(b.status, '')} for b in LabTestRequest.objects.filter(user=request.user).prefetch_related('items')]
    return _page(request, 'lab', bookings=rows)


@login_required
@require_POST
def claim(request):
    """Add an earlier guest order or lab booking to this account. Proof: the order number and the email it was placed with."""
    from lab.models import LabTestRequest
    from marketplace.models import Order
    kind, number, email = request.POST.get('kind'), request.POST.get('number', '').strip().lstrip('#'), request.POST.get('email', '').strip()
    back = 'portal:lab' if kind == 'lab' else 'portal:orders'
    key = f'portal-claim-fail:{request.user.pk}'
    if cache.get(key, 0) >= LINK_FAILURES:
        messages.error(request, 'Too many attempts. Please wait 15 minutes and try again.')
        return redirect(back)
    model, field = (LabTestRequest, 'request_number') if kind == 'lab' else (Order, 'order_number')
    found = model.objects.filter(**{field: number}, customer_email__iexact=email, user__isnull=True).first() if number and email else None
    if found is None:
        cache.set(key, cache.get(key, 0) + 1, LINK_WINDOW)
        messages.error(request, 'We could not find an unclaimed order with that number and email. Check both, or it may already belong to an account.')
    else:
        found.user = request.user
        found.save(update_fields=['user'])
        messages.success(request, f'#{number} was added to your account.')
    return redirect(back)


@login_required
def settings_page(request):
    """Account settings of the patient account: where a treatment record is linked, plus email and password."""
    from accounts.forms import SettingsEmailForm
    form = SettingsEmailForm(request.POST or None, user=request.user) if request.POST.get('form') == 'email' else SettingsEmailForm(user=request.user)
    if request.method == 'POST' and request.POST.get('form') == 'email':
        if form.is_valid():
            request.user.email = form.cleaned_data['email']
            request.user.save(update_fields=['email'])
            messages.success(request, 'Email saved.')
            return redirect('portal:settings')
        messages.error(request, form.errors['email'][0])
    return _page(request, 'settings', email_form=form, max_attempts=MAX_ATTEMPTS_PER_INVITE)


@login_required
def link(request):
    """Link this account to a treatment record: one-time code from the physio + the patient's date of birth."""
    if request.method != 'POST':
        return redirect('portal:settings')
    key = f'portal-link-fail:{request.user.pk}'
    if cache.get(key, 0) >= LINK_FAILURES:
        messages.error(request, 'Too many wrong attempts. Please wait 15 minutes and try again.')
        return redirect('portal:settings')
    invite = PortalInvite.objects.filter(code_hash=hash_code(request.POST.get('code', ''))).select_related('patient').first()
    try:
        born = datetime.date.fromisoformat(request.POST.get('dob', ''))
    except ValueError:
        born = None
    ok = bool(invite and invite.is_open and born and invite.patient.date_of_birth == born and not PatientLink.objects.filter(patient=invite.patient).exists())
    if not ok:
        cache.set(key, cache.get(key, 0) + 1, LINK_WINDOW)
        if invite and invite.is_open:
            invite.failed_attempts += 1  # a known code with a wrong birth date counts against the code itself
            invite.save(update_fields=['failed_attempts'])
        messages.error(request, GENERIC_FAIL)
        return redirect('portal:settings')
    PatientLink.objects.create(user=request.user, patient=invite.patient)
    invite.used_at = timezone.now()
    invite.save(update_fields=['used_at'])
    cache.delete(key)
    messages.success(request, 'Linked. Your treatment shared by your physiotherapist is now on your dashboard.')
    return redirect(f"{reverse('portal:home')}?p={invite.patient_id}")


def _linked_patient(request, pk):
    return get_object_or_404(Patient.objects.select_related('clinic'), pk=pk, portal_link__user=request.user)


def _back(patient, section):
    return redirect(f"{reverse('portal:' + section)}?p={patient.pk}")


@login_required
@require_POST
def exercise_done(request, pk, item_id):
    patient = _linked_patient(request, pk)
    item = get_object_or_404(PrescriptionExercise, pk=item_id, prescription__patient=patient, prescription__status=Prescription.ACTIVE)
    item.is_completed = not item.is_completed
    item.completed_at = timezone.now() if item.is_completed else None
    item.save(update_fields=['is_completed', 'completed_at'])
    return _back(patient, 'exercises')


@login_required
@require_POST
def exercise_feedback(request, pk, item_id):
    patient = _linked_patient(request, pk)
    item = get_object_or_404(PrescriptionExercise, pk=item_id, prescription__patient=patient, prescription__status=Prescription.ACTIVE)
    kind = request.POST.get('feedback_type')
    if kind not in dict(ExerciseFeedback.FEEDBACK_CHOICES):
        messages.error(request, 'Choose how the exercise felt.')
    else:
        ExerciseFeedback.objects.create(prescription_exercise=item, feedback_type=kind, note=request.POST.get('note', '').strip()[:300])
        messages.success(request, 'Thank you - your physiotherapist will see this.' if kind in ('normal', 'hard') else
                         'Noted. If the pain or symptoms are getting worse, stop the exercise and contact your physiotherapist.')
    return _back(patient, 'exercises')


@login_required
@require_POST
def unlink(request, pk):
    patient = _linked_patient(request, pk)
    patient.portal_link.delete()
    messages.success(request, 'This record is no longer linked to your account. Your physiotherapist can give you a new code if you want to link it again.')
    return redirect('portal:settings')


# ------------------------------------------------------------------ the professional's side

@login_required
@require_POST
def invite(request, pk):
    """Create a one-time code for a patient. The code is shown on this page only (it is stored hashed, so it cannot be shown again)."""
    profile, patient = own_patient(request, pk)
    if patient.date_of_birth is None:
        messages.error(request, 'Add the patient\'s date of birth first: it is part of how they confirm it is their record.')
        return redirect(f"{reverse('accounts:patient-edit', args=[patient.pk])}")
    if hasattr(patient, 'portal_link'):
        messages.info(request, 'This patient already has a portal account. Remove access first if they need to link a different one.')
        return redirect(f"{reverse('accounts:patient-detail', args=[patient.pk])}")
    invite_obj, code = PortalInvite.issue(patient, profile)
    from accounts.access import workspace_context
    context = workspace_context(request.user, profile)
    context.update({'active': 'patients', 'patient': patient, 'code': code, 'invite': invite_obj, 'link_url': request.build_absolute_uri(reverse('portal:settings')),
                    'signup_url': request.build_absolute_uri(reverse('accounts:signup-client'))})
    response = render(request, 'portal/invite.html', context)
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_POST
def revoke(request, pk):
    profile, patient = own_patient(request, pk)
    PatientLink.objects.filter(patient=patient).delete()
    PortalInvite.objects.filter(patient=patient, used_at__isnull=True).delete()
    messages.success(request, 'Portal access removed.')
    return redirect(f"{reverse('accounts:patient-detail', args=[patient.pk])}")
