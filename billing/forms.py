from decimal import Decimal

from django import forms

from accounts.models import Patient
from accounts.widgets import date_widget

from .models import BillingEntry, EntryPayment, PackagePayment, PatientAdvance, PatientPackage


class PaymentStatusMixin(forms.Form):
    """New bills can be paid in full, part paid, or left on credit (due) - many patients settle at the end of the week.
    The payment mode is the mode of what is received now. Editing a bill never changes what was already received."""
    payment_status = forms.ChoiceField(choices=[('paid', 'Paid in full'), ('partial', 'Part paid'), ('due', 'Not paid yet (credit)'), ('advance', 'Use advance balance'), ('advance_cash', 'Advance + pay the rest now')], initial='paid', required=False, label='Payment')
    amount_received = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label='Received now (NPR)',
                                         widget=forms.NumberInput(attrs={'placeholder': 'Amount received now', 'step': '0.01', 'min': 0}))

    amount_given = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label='Cash handed over (NPR)',
                                      widget=forms.NumberInput(attrs={'placeholder': 'Only if more than the bill', 'step': '0.01', 'min': 0}),
                                      help_text='No change to give back? Enter what the patient handed over: the extra is carried over to their next session.')
    patient_linked = False  # the patient-tab form always knows the patient; the book form does once one is picked

    def clean_rate(self):
        rate = self.cleaned_data.get('rate')
        if rate is not None and rate < 0:
            raise forms.ValidationError('Amount cannot be negative.')
        if rate is not None and self.instance.pk and rate < self.instance.amount_paid:
            raise forms.ValidationError(f'NPR {self.instance.amount_paid:g} has already been received, so the amount cannot be lower than that.')
        return rate

    def clean(self):
        data = super().clean()
        if self.instance.pk:
            return data
        status, rate, got = data.get('payment_status') or 'paid', data.get('rate'), data.get('amount_received')
        given = data.get('amount_given')
        if status in ('paid', 'advance_cash') and given is not None and rate is not None:
            if status == 'paid' and given < rate:
                self.add_error('amount_given', 'That is less than the bill: choose "Part paid" instead.')
            elif given > rate and not (self.patient_linked or data.get('patient')):
                self.add_error('amount_given', 'The extra can only be carried over for a registered patient. Pick the patient, or enter the exact amount.')
        if status == 'partial' and rate is not None:
            if got is None or got <= 0:
                self.add_error('amount_received', 'Enter how much was received now.')
            elif got >= rate:
                self.add_error('amount_received', 'That is the full amount: choose "Paid in full" instead.')
        return data

    def apply_payment(self, entry, user=None):
        """After a new bill is saved: record what was received with it (nothing at all when it is left on credit)."""
        status = self.cleaned_data.get('payment_status') or 'paid'
        self.carried = Decimal('0')
        if status == 'advance':
            return entry.use_advance(user)
        if status in ('paid', 'advance_cash'):
            if status == 'advance_cash':
                entry.use_advance(user)
            owed = entry.amount_due
            given = self.cleaned_data.get('amount_given')
            given = owed if given is None else given
            paid = entry.record_payment(min(given, owed), entry.payment_mode, paid_on=entry.entry_date, user=user)
            extra = given - (paid.amount if paid else 0) if owed > 0 else given
            if extra > 0 and entry.patient_id:  # no change given back: the extra is carried over as the patient's advance
                entry.carry_over(extra, entry.payment_mode, user=user, paid_on=entry.entry_date)
                self.carried = extra
            return
        amount = self.cleaned_data.get('amount_received') if status == 'partial' else 0
        entry.record_payment(amount, entry.payment_mode, paid_on=entry.entry_date, user=user)


class BillingEntryForm(PaymentStatusMixin, forms.ModelForm):
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

class PatientBillForm(PaymentStatusMixin, forms.ModelForm):
    patient_linked = True
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



class BillCorrectionForm(forms.ModelForm):
    """Fix a bill: what was charged and how it was paid (cash, credit, part paid), never the patient's own details."""
    payment_status = forms.ChoiceField(choices=[('paid', 'Paid in full'), ('partial', 'Part paid'), ('due', 'Not paid yet (credit)')], label='Payment')
    amount_received = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label='Total received so far (NPR)',
                                         widget=forms.NumberInput(attrs={'step': '0.01', 'min': 0}))

    class Meta:
        model = BillingEntry
        fields = ['entry_date', 'service', 'rate', 'payment_mode', 'notes']
        widgets = {
            'entry_date': date_widget(),
            'service': forms.TextInput(attrs={'placeholder': 'e.g. Physiotherapy'}),
            'rate': forms.NumberInput(attrs={'placeholder': 'Amount (NPR)', 'step': '0.01', 'min': 0}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional notes'}),
        }

    def clean_rate(self):
        rate = self.cleaned_data.get('rate')
        if rate is not None and rate < 0:
            raise forms.ValidationError('Amount cannot be negative.')
        return rate

    def clean(self):
        data = super().clean()
        rate, got = data.get('rate'), data.get('amount_received')
        if data.get('payment_status') == 'partial' and rate is not None:
            if got is None or got <= 0:
                self.add_error('amount_received', 'Enter how much has been received in total.')
            elif got >= rate:
                self.add_error('amount_received', 'That is the full amount: choose "Paid in full" instead.')
        return data

    def received_total(self):
        status = self.cleaned_data['payment_status']
        return self.cleaned_data['rate'] if status == 'paid' else self.cleaned_data.get('amount_received') if status == 'partial' else 0


class AdvanceForm(forms.ModelForm):
    """Money a patient pays ahead of their sessions."""
    class Meta:
        model = PatientAdvance
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

    def clean_payment_mode(self):
        return self.cleaned_data.get('payment_mode') or 'cash'


class EntryPaymentForm(forms.ModelForm):
    class Meta:
        model = EntryPayment
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
