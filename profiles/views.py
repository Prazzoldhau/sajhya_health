import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from accounts.access import first_error, own_patient, require_workspace
from marketplace.models import PharmacyProduct, Product

from . import forms
from .models import AidEntry, LabEntry, MedicineEntry, NursingEntry, PatientProfile, TherapyNote
from .rehab import physio_summary

# section key -> (model, form class, human name). One generic add/delete pair serves every section.
SECTIONS = {
    'medicine': (MedicineEntry, forms.MedicineForm, 'medicine'),
    'nursing': (NursingEntry, forms.NursingForm, 'nursing entry'),
    'aids': (AidEntry, forms.AidForm, 'aid'),
    'therapy': (TherapyNote, forms.TherapyForm, 'therapy note'),
    'labs': (LabEntry, forms.LabEntryForm, 'lab test'),
}
SECTION_ORDER = ['general', 'medicine', 'nursing', 'aids', 'rehab', 'labs']
THERAPY_TABS = [('physio', 'Physiotherapy'), ('occupational', 'Occupational'), ('speech', 'Speech'), ('behavioural', 'Behavioural')]


def _back(patient, section, therapy=None):
    url = f"{reverse('accounts:patient-detail', args=[patient.pk])}?tab=profile&section={'rehab' if section == 'therapy' else section}"
    return redirect(url + (f'&therapy={therapy}' if therapy else ''))


def profile_context(patient, section, therapy='physio'):
    """Everything the Profile tab of the patient page needs. Called by accounts.views.patient_detail."""
    section = section if section in SECTION_ORDER else 'general'
    info, _ = PatientProfile.objects.get_or_create(patient=patient)
    ctx = {
        'section': section, 'info': info, 'sections': [
            ('general', 'General', None), ('medicine', 'Medicine', patient.medicines.filter(status='active').count()),
            ('nursing', 'Nursing', patient.nursing_entries.count()), ('aids', 'Surgical aids', patient.aids.filter(status='in_use').count()),
            ('rehab', 'Rehab', None), ('labs', 'Lab tests', patient.lab_entries.count())],
        'standing_form': forms.StandingInfoForm(instance=info),
    }
    if section == 'medicine':
        ctx.update(medicines=patient.medicines.select_related('pharmacy_product'), form=forms.MedicineForm())
    elif section == 'nursing':
        ctx.update(nursing=patient.nursing_entries.all()[:60], form=forms.NursingForm(initial={'recorded_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M')}))
    elif section == 'aids':
        ctx.update(aids=patient.aids.all(), form=forms.AidForm())
    elif section == 'rehab':
        therapy = therapy if therapy in dict(THERAPY_TABS) else 'physio'
        ctx.update(therapy=therapy, therapy_tabs=THERAPY_TABS)
        if therapy == 'physio':
            ctx['physio'] = physio_summary(patient)
        else:
            ctx.update(therapy_notes=patient.therapy_notes.filter(therapy=therapy), form=forms.TherapyForm(initial={'therapy': therapy}),
                       therapy_label=dict(TherapyNote.THERAPY_CHOICES)[therapy])
    elif section == 'labs':
        ctx.update(labs=patient.lab_entries.select_related('lab_test', 'lab_panel'), form=forms.LabEntryForm(), result_form=forms.LabResultForm())
    return ctx


@login_required
def standing_save(request, pk):
    profile, patient = own_patient(request, pk)
    info, _ = PatientProfile.objects.get_or_create(patient=patient)
    if request.method == 'POST':
        form = forms.StandingInfoForm(request.POST, instance=info)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'Profile updated.')
    return _back(patient, 'general')


@login_required
def entry_add(request, pk, section):
    profile, patient = own_patient(request, pk)
    if section not in SECTIONS:
        raise Http404
    model, form_class, label = SECTIONS[section]
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.patient, entry.recorded_by = patient, request.user
            entry.save()
            messages.success(request, f'Added {label}.')
            return _back(patient, section, getattr(entry, 'therapy', None))
        messages.error(request, first_error(form))
    return _back(patient, section, request.POST.get('therapy'))


@login_required
def entry_delete(request, pk, section, entry_id):
    profile, patient = own_patient(request, pk)
    if section not in SECTIONS:
        raise Http404
    entry = get_object_or_404(SECTIONS[section][0], pk=entry_id, patient=patient)
    therapy = getattr(entry, 'therapy', None)
    if request.method == 'POST':
        if section == 'labs' and entry.report:
            entry._meta.get_field('report').storage.delete(entry.report.name)  # do not leave the report file behind
        entry.delete()
        messages.success(request, 'Removed.')
    return _back(patient, section, therapy)


@login_required
def medicine_status(request, pk, entry_id):
    profile, patient = own_patient(request, pk)
    entry = get_object_or_404(MedicineEntry, pk=entry_id, patient=patient)
    new = request.POST.get('status')
    if request.method == 'POST' and new in dict(MedicineEntry.STATUS_CHOICES):
        entry.status = new
        if new != MedicineEntry.ACTIVE and not entry.end_date:
            entry.end_date = timezone.localdate()
        if new == MedicineEntry.ACTIVE:
            entry.end_date = None
        entry.save(update_fields=['status', 'end_date'])
    return _back(patient, 'medicine')


@login_required
def aid_status(request, pk, entry_id):
    profile, patient = own_patient(request, pk)
    entry = get_object_or_404(AidEntry, pk=entry_id, patient=patient)
    new = request.POST.get('status')
    if request.method == 'POST' and new in dict(AidEntry.STATUS_CHOICES):
        entry.status = new
        entry.save(update_fields=['status'])
    return _back(patient, 'aids')


@login_required
def lab_result(request, pk, entry_id):
    """Record the result of a lab test: value, unit, range, flag, date and an optional report file."""
    profile, patient = own_patient(request, pk)
    entry = get_object_or_404(LabEntry, pk=entry_id, patient=patient)
    if request.method == 'POST':
        old = entry.report.name if entry.report else ''
        form = forms.LabResultForm(request.POST, request.FILES, instance=entry)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.status = LabEntry.RESULTED
            obj.resulted_on = obj.resulted_on or timezone.localdate()
            obj.save()
            if old and old != (obj.report.name if obj.report else ''):
                obj._meta.get_field('report').storage.delete(old)  # a replaced report must not linger
            messages.success(request, 'Result saved.')
        else:
            messages.error(request, first_error(form))
    return _back(patient, 'labs')


@login_required
def lab_status(request, pk, entry_id):
    profile, patient = own_patient(request, pk)
    entry = get_object_or_404(LabEntry, pk=entry_id, patient=patient)
    new = request.POST.get('status')
    if request.method == 'POST' and new in (LabEntry.BOOKED, LabEntry.COLLECTED, LabEntry.CANCELLED, LabEntry.ADVISED):
        entry.status = new
        entry.save(update_fields=['status'])
    return _back(patient, 'labs')


@login_required
def lab_report(request, pk, entry_id):
    """Lab reports are private: only the owning professional can open them."""
    profile, patient = own_patient(request, pk)
    entry = get_object_or_404(LabEntry, pk=entry_id, patient=patient)
    if not entry.report:
        raise Http404
    return FileResponse(entry.report.open('rb'), content_type=mimetypes.guess_type(entry.report.name)[0] or 'application/octet-stream')


@login_required
def aid_search(request):
    """Type-ahead for the aids form: marketplace products (the pharmacy is a separate catalogue and is not included)."""
    require_workspace(request)
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    found = Product.objects.filter(name__icontains=q).select_related('category').order_by('name')[:10]
    return JsonResponse({'results': [{'id': p.pk, 'name': p.name, 'detail': p.category.name if p.category else ''} for p in found]})


@login_required
def medicine_search(request):
    """Type-ahead for the medicine form: pharmacy catalogue matches by name."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    found = PharmacyProduct.objects.filter(name__icontains=q).order_by('name')[:10]
    return JsonResponse({'results': [{'id': p.pk, 'name': p.name, 'detail': p.category or ('Rx required' if p.requires_prescription else '')} for p in found]})
