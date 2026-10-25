from django import forms

from accounts.models import Patient
from accounts.widgets import date_widget

from .models import BillingEntry, PackagePayment, PatientPackage


class BillingEntryForm(forms.ModelForm):
    class Meta:
        model = BillingEntry
        fields = ['entry_date', 'patient', 'patient_name', 'age', 'sex', 'contact_number', 'service', 'rate', 'payment_mode', 'notes']
        widgets = {
            'entry_date': date_widget(),
            'patient': forms.HiddenInput(),
            'patient_name': forms.TextInput(attrs={'placeholder': 'Full name', 'autocomplete': 'off'}),
            'age': forms.NumberInput(attrs={'placeholder': 'Age', 'min': 0, 'max': 130}),
            'contact_number': forms.TextInput(attrs={'placeholder': 'Optional'}),
            'service': forms.TextInput(attrs={'placeholder': 'e.g. Physiotherapy'}),
            'rate': forms.NumberInput(attrs={'placeholder': 'Amount (NPR)', 'step': '0.01', 'min': 0}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional notes'}),
        }

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['patient'].queryset = Patient.objects.filter(professional=profile)
        self.fields['patient'].required = False

    def clean_patient_name(self):
        name = self.cleaned_data.get('patient_name', '').strip()
        if len(name) < 2:
            raise forms.ValidationError('Name must be at least 2 characters long.')
        return name

    def clean_rate(self):
        rate = self.cleaned_data.get('rate')
        if rate is not None and rate < 0:
            raise forms.ValidationError('Amount cannot be negative.')
        return rate


class PatientBillForm(forms.ModelForm):
    """A bill written from inside a patient's own Billing tab: the patient is already known, so only the money details are asked."""
    class Meta:
        model = BillingEntry
        fields = ['entry_date', 'service', 'rate', 'payment_mode', 'notes']
        widgets = {
            'entry_date': date_widget(),
            'service': forms.TextInput(attrs={'placeholder': 'e.g. Physiotherapy'}),
            'rate': forms.NumberInput(attrs={'placeholder': 'Amount (NPR)', 'step': '0.01', 'min': 0}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional notes'}),
        }

    clean_rate = BillingEntryForm.clean_rate


class PatientPackageForm(forms.ModelForm):
    patient = forms.ModelChoiceField(queryset=Patient.objects.none(), widget=forms.HiddenInput(), error_messages={'required': 'Choose a patient first.', 'invalid_choice': 'Choose a patient from the list.'})
    amount_paid_now = forms.DecimalField(
        required=False, min_value=0, initial=0, label='Amount paid now',
        widget=forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}),
        help_text='Leave at 0 if nothing is being paid today.')

    class Meta:
        model = PatientPackage
        fields = ['patient', 'duration', 'total_sessions', 'total_amount', 'start_date', 'notes']
        widgets = {
            'total_sessions': forms.NumberInput(attrs={'placeholder': 'e.g. 8', 'min': 1}),
            'total_amount': forms.NumberInput(attrs={'placeholder': 'Amount (NPR)', 'step': '0.01', 'min': 0}),
            'start_date': date_widget(),
            'notes': forms.TextInput(attrs={'placeholder': 'Optional notes'}),
        }

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['patient'].queryset = Patient.objects.filter(professional=profile)

    def clean_total_sessions(self):
        value = self.cleaned_data.get('total_sessions')
        if value is not None and value < 1:
            raise forms.ValidationError('A package needs at least 1 session.')
        return value

    def clean_total_amount(self):
        value = self.cleaned_data.get('total_amount')
        if value is not None and value < 0:
            raise forms.ValidationError('Amount cannot be negative.')
        return value

    def clean(self):
        data = super().clean()
        paid, total = data.get('amount_paid_now') or 0, data.get('total_amount')
        if total is not None and paid > total:
            self.add_error('amount_paid_now', 'Cannot be more than the package price.')
        return data


class PackagePaymentForm(forms.ModelForm):
    class Meta:
        model = PackagePayment
        fields = ['amount', 'payment_mode', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={'placeholder': 'Amount (NPR)', 'step': '0.01', 'min': 0.01}),
            'notes': forms.TextInput(attrs={'placeholder': 'Optional notes'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Enter an amount greater than zero.')
        return amount
