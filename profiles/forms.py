from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from accounts.forms import validate_document
from accounts.widgets import date_widget, datetime_widget
from lab.models import LabTest, LabTestPanel
from marketplace.models import PharmacyProduct, Product

from .models import AidEntry, LabEntry, MedicineEntry, NursingEntry, PatientProfile, TherapyNote



class StandingInfoForm(forms.ModelForm):
    class Meta:
        model = PatientProfile
        fields = ('allergies', 'medical_history', 'wound_catheter_care', 'mobility_assistance')
        widgets = {f: forms.Textarea(attrs={'rows': 3}) for f in fields}
        labels = {'wound_catheter_care': 'Wound / catheter / ostomy care', 'mobility_assistance': 'Mobility assistance'}


class MedicineForm(forms.ModelForm):
    pharmacy_product = forms.ModelChoiceField(queryset=PharmacyProduct.objects.all(), required=False, widget=forms.HiddenInput())

    class Meta:
        model = MedicineEntry
        fields = ('pharmacy_product', 'custom_name', 'dosage', 'morning', 'afternoon', 'evening', 'night', 'instructions', 'prescribed_by', 'start_date', 'end_date')
        widgets = {'start_date': date_widget(), 'end_date': date_widget(), 'custom_name': forms.TextInput(attrs={'placeholder': 'Search the pharmacy, or type a name'}),
                   'dosage': forms.TextInput(attrs={'placeholder': 'e.g. 500 mg, 1 tablet'}), 'instructions': forms.TextInput(attrs={'placeholder': 'e.g. after food'})}

    def clean(self):
        data = super().clean()
        if not data.get('pharmacy_product') and not (data.get('custom_name') or '').strip():
            raise ValidationError('Search the pharmacy for the medicine, or type its name.')
        if data.get('start_date') and data.get('end_date') and data['end_date'] < data['start_date']:
            self.add_error('end_date', 'The end date cannot be before the start date.')
        return data


class NursingForm(forms.ModelForm):
    class Meta:
        model = NursingEntry
        fields = ('category', 'recorded_at', 'bp_systolic', 'bp_diastolic', 'pulse', 'temperature_c', 'spo2', 'respiratory_rate', 'weight_kg', 'notes')
        widgets = {'recorded_at': datetime_widget(),
                   'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'What was done or observed'}),
                   'temperature_c': forms.NumberInput(attrs={'step': '0.1'}), 'weight_kg': forms.NumberInput(attrs={'step': '0.1'})}
        labels = {'bp_systolic': 'BP systolic', 'bp_diastolic': 'BP diastolic', 'temperature_c': 'Temp (°C)', 'spo2': 'SpO₂ %', 'respiratory_rate': 'Resp. rate', 'weight_kg': 'Weight (kg)'}

    def clean(self):
        data = super().clean()
        vitals = ('bp_systolic', 'bp_diastolic', 'pulse', 'temperature_c', 'spo2', 'respiratory_rate', 'weight_kg')
        if not (data.get('notes') or '').strip() and all(data.get(f) in (None, '') for f in vitals):
            raise ValidationError('Enter at least one vital sign or a note.')
        if bool(data.get('bp_systolic')) != bool(data.get('bp_diastolic')):
            raise ValidationError('Enter both blood pressure numbers (systolic and diastolic).')
        return data


class AidForm(forms.ModelForm):
    product = forms.ModelChoiceField(queryset=Product.objects.all(), required=False, widget=forms.HiddenInput())

    class Meta:
        model = AidEntry
        fields = ('product', 'custom_name', 'category', 'side', 'size', 'issued_on', 'notes')
        widgets = {'issued_on': date_widget(), 'custom_name': forms.TextInput(attrs={'placeholder': 'Search the marketplace, or type a name'}), 'size': forms.TextInput(attrs={'placeholder': 'e.g. M, 32 cm'})}
        labels = {'custom_name': 'Aid'}

    def clean(self):
        data = super().clean()
        data['custom_name'] = (data.get('custom_name') or '').strip()
        if not data.get('product') and not data['custom_name']:
            raise ValidationError('Search the marketplace for the aid, or type its name.')
        if data.get('product') and not data['custom_name']:
            data['custom_name'] = data['product'].name
        return data


class TherapyForm(forms.ModelForm):
    class Meta:
        model = TherapyNote
        fields = ('therapy', 'session_date', 'goal', 'intervention', 'response', 'plan')
        widgets = {'session_date': date_widget(), 'intervention': forms.Textarea(attrs={'rows': 2}), 'response': forms.Textarea(attrs={'rows': 2}), 'plan': forms.Textarea(attrs={'rows': 2})}

    def clean(self):
        data = super().clean()
        if not any((data.get(f) or '').strip() for f in ('goal', 'intervention', 'response', 'plan')):
            raise ValidationError('Fill in at least the goal, what was done, the response or the plan.')
        return data


class LabEntryForm(forms.ModelForm):
    lab_test = forms.ModelChoiceField(queryset=LabTest.objects.all(), required=False, widget=forms.HiddenInput())
    lab_panel = forms.ModelChoiceField(queryset=LabTestPanel.objects.all(), required=False, widget=forms.HiddenInput())

    class Meta:
        model = LabEntry
        fields = ('lab_test', 'lab_panel', 'custom_name', 'ordered_on', 'status', 'notes')
        widgets = {'ordered_on': date_widget(), 'custom_name': forms.TextInput(attrs={'placeholder': 'Search the lab catalogue, or type a name'}),
                   'notes': forms.TextInput(attrs={'placeholder': 'e.g. repeat every 3 months'})}
        labels = {'custom_name': 'Test'}

    def clean(self):
        data = super().clean()
        if not (data.get('lab_test') or data.get('lab_panel') or (data.get('custom_name') or '').strip()):
            raise ValidationError('Search the lab catalogue for the test, or type its name.')
        return data


class LabResultForm(forms.ModelForm):
    class Meta:
        model = LabEntry
        fields = ('result_value', 'result_unit', 'reference_range', 'flag', 'resulted_on', 'report')
        widgets = {'resulted_on': date_widget(), 'report': forms.FileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png'}),
                   'result_value': forms.TextInput(attrs={'placeholder': 'e.g. 5.4'}), 'result_unit': forms.TextInput(attrs={'placeholder': 'mmol/L'}),
                   'reference_range': forms.TextInput(attrs={'placeholder': '4.0 - 6.0'})}

    def clean_report(self):
        report = self.cleaned_data.get('report')
        if isinstance(report, UploadedFile):
            validate_document(report)  # PDF / JPEG / PNG up to 5 MB, content checked against the extension
        return report

    def clean(self):
        data = super().clean()
        if not (data.get('result_value') or '').strip() and not data.get('report') and not self.instance.report:
            raise ValidationError('Enter the result value, or attach the report.')
        return data
