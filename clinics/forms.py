import datetime
import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from accounts.images import normalize_photo
from accounts.forms import AgeOrBirthDate
from accounts.models import Patient

from .models import AMENITIES, PROVINCES, SLOT_CHOICES, SPECIALIZATIONS, WEEKDAYS, Clinic, ClinicMember, ClinicSubscription


def clean_phone_number(value, required=True):
    value = (value or '').strip()
    if not value and not required:
        return ''
    stripped = value.replace(' ', '').replace('-', '').replace('+', '').replace('(', '').replace(')', '')
    if not stripped.isdigit() or not 7 <= len(stripped) <= 15:
        raise ValidationError('Enter a valid phone number (7 to 15 digits; spaces, dashes and + are fine).')
    return value


class UpgradeForm(forms.ModelForm):
    class Meta:
        model = ClinicSubscription
        fields = ('contact_phone', 'request_note')
        labels = {'contact_phone': 'Phone number we can reach you on', 'request_note': 'Anything we should know (number of clinics, branches, staff)'}
        widgets = {'request_note': forms.Textarea(attrs={'rows': 3})}

    def clean_contact_phone(self):
        return clean_phone_number(self.cleaned_data.get('contact_phone'))


class ClinicForm(forms.ModelForm):
    """The clinic profile. Only name, primary phone, province and district are required; the rest can be completed later."""
    specializations = forms.MultipleChoiceField(choices=SPECIALIZATIONS, widget=forms.CheckboxSelectMultiple, required=False, label='Primary specialisation')
    amenities = forms.MultipleChoiceField(choices=AMENITIES, widget=forms.CheckboxSelectMultiple, required=False, label='Amenities & facilities')
    province = forms.ChoiceField(choices=[('', 'Select province')] + [(p, p) for p in PROVINCES])
    slot_minutes = forms.TypedChoiceField(choices=SLOT_CHOICES, coerce=int, initial=30, label='Default appointment slot duration')

    class Meta:
        model = Clinic
        fields = ('name', 'short_bio', 'logo', 'banner', 'pan_number', 'facility_license', 'specializations', 'phone', 'phone_secondary', 'email', 'website',
                  'province', 'district', 'ward_street', 'map_link', 'slot_minutes', 'amenities')
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Apex Physiotherapy & Rehab'}),
            'short_bio': forms.Textarea(attrs={'rows': 3, 'maxlength': 500, 'placeholder': 'Tell patients about your clinic (max 500 characters)'}),
            'logo': forms.FileInput(attrs={'accept': '.jpg,.jpeg,.png'}), 'banner': forms.FileInput(attrs={'accept': '.jpg,.jpeg,.png'}),
            'pan_number': forms.TextInput(attrs={'placeholder': 'PAN / VAT or company registration no.'}),
            'facility_license': forms.TextInput(attrs={'placeholder': 'Ministry / Directorate licence no.'}),
            'phone': forms.TextInput(attrs={'type': 'tel'}), 'phone_secondary': forms.TextInput(attrs={'type': 'tel', 'placeholder': 'Optional'}),
            'email': forms.EmailInput(attrs={'placeholder': 'info@clinicname.com'}), 'website': forms.URLInput(attrs={'placeholder': 'https://'}),
            'district': forms.TextInput(attrs={'placeholder': 'e.g. Lalitpur'}), 'ward_street': forms.TextInput(attrs={'placeholder': 'e.g. Ward 3, Pulchowk'}),
            'map_link': forms.TextInput(attrs={'placeholder': 'Optional: Google Maps link or coordinates'}),
        }
        labels = {'phone': 'Primary phone number'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_files = {f: (getattr(self.instance, f).name if self.instance.pk and getattr(self.instance, f) else '') for f in ('logo', 'banner')}
        for name in ('name', 'phone', 'province', 'district'):
            self.fields[name].required = True
        saved = self.instance.hours if self.instance.pk else {day: ['10:00', '18:00'] for day, _ in WEEKDAYS[:6]}  # new clinic: Sunday-Friday
        for day, label in WEEKDAYS:
            self.fields[f'open_{day}'] = forms.BooleanField(required=False, label=label)
            self.fields[f'start_{day}'] = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'))
            self.fields[f'end_{day}'] = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'))
            if not self.is_bound:
                row = saved.get(day)
                self.initial[f'open_{day}'] = bool(row)
                self.initial[f'start_{day}'] = datetime.time.fromisoformat(row[0]) if row else datetime.time(10, 0)
                self.initial[f'end_{day}'] = datetime.time.fromisoformat(row[1]) if row else datetime.time(18, 0)

    @property
    def day_rows(self):
        """For the template: one row per weekday with its three fields."""
        return [{'label': label, 'open': self[f'open_{day}'], 'start': self[f'start_{day}'], 'end': self[f'end_{day}']} for day, label in WEEKDAYS]

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise ValidationError('Clinic name must be at least 2 characters.')
        return name

    def clean_phone(self):
        return clean_phone_number(self.cleaned_data.get('phone'))

    def clean_phone_secondary(self):
        return clean_phone_number(self.cleaned_data.get('phone_secondary'), required=False)

    def clean_pan_number(self):
        value = (self.cleaned_data.get('pan_number') or '').strip()
        if value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\-/ ]{2,29}', value):
            raise ValidationError('Use letters, digits, dashes or slashes (3-30 characters).')
        return value

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if isinstance(logo, UploadedFile):
            return normalize_photo(logo, 'logo', max_bytes=2 * 1024 * 1024, max_side=512)
        return logo

    def clean_banner(self):
        banner = self.cleaned_data.get('banner')
        if isinstance(banner, UploadedFile):
            return normalize_photo(banner, 'banner', max_bytes=4 * 1024 * 1024, fit=(1280, 720))  # cropped to 16:9
        return banner

    def clean(self):
        data = super().clean()
        hours = {}
        for day, label in WEEKDAYS:
            if not data.get(f'open_{day}'):
                continue
            start, end = data.get(f'start_{day}'), data.get(f'end_{day}')
            if not start or not end:
                self.add_error(f'end_{day}', f'Give {label} an opening and a closing time, or untick it.')
            elif end <= start:
                self.add_error(f'end_{day}', f'{label}: closing time must be after opening time.')
            else:
                hours[day] = [start.strftime('%H:%M'), end.strftime('%H:%M')]
        data['hours'] = hours
        return data

    def save(self, commit=True):
        self.instance.hours = self.cleaned_data.get('hours', {})
        clinic = super().save(commit=commit)
        if commit:
            for field, old in self._old_files.items():
                new = getattr(clinic, field).name if getattr(clinic, field) else ''
                if old and old != new:
                    clinic._meta.get_field(field).storage.delete(old)  # a replaced picture must not linger on disk
        return clinic


class StaffForm(forms.ModelForm):
    role = forms.ChoiceField(choices=ClinicMember.STAFF_ROLES)

    class Meta:
        model = ClinicMember
        fields = ('name', 'role', 'specialty', 'department', 'departments', 'phone', 'email')
        widgets = {'departments': forms.CheckboxSelectMultiple}
        labels = {'departments': 'Works in these departments'}

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = False  # a department login is named after its department
        self.fields['department'].required = False
        self.fields['department'].empty_label = 'Only for a department login'
        owned = clinic.calendar_owner.departments.all() if clinic is not None else self.fields['department'].queryset.none()
        self.fields['department'].queryset = owned
        self.fields['departments'].queryset = owned
        self.fields['departments'].required = False

    def clean(self):
        data = super().clean()
        if data.get('role') == ClinicMember.DEPARTMENT:
            if not data.get('department'):
                self.add_error('department', 'Choose the department this login is for. Add departments under Appointments first.')
            else:
                data['name'] = data['department'].name
        else:
            data['department'] = None
            if data.get('role') != ClinicMember.CLINICIAN:
                data['specialty'] = ''
            if not (data.get('name') or '').strip():
                self.add_error('name', 'Type the name.')
        return data

    def clean_name(self):
        return self.cleaned_data['name'].strip()


class ClinicLoginForm(forms.Form):
    """The owner chooses the sign-in the clinic itself uses (a shared front-desk login), separate from their own."""
    username = forms.CharField(max_length=150, label='Clinic username', help_text='Letters, digits and @ . + - _ only. The clinic signs in with this.')
    password1 = forms.CharField(label='Clinic password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), strip=False)
    password2 = forms.CharField(label='Repeat the password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), strip=False)

    def __init__(self, *args, clinic, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic
        self.current_user = clinic.workspace.account.user if clinic.workspace_id else None
        if self.current_user:
            self.fields['username'].initial = self.current_user.get_username()

    def clean_username(self):
        from django.contrib.auth.models import User
        from django.contrib.auth.validators import UnicodeUsernameValidator
        username = self.cleaned_data['username'].strip()
        UnicodeUsernameValidator()(username)
        taken = User.objects.filter(username__iexact=username)
        if self.current_user:
            taken = taken.exclude(pk=self.current_user.pk)
        if taken.exists():
            raise ValidationError('That username is already taken. Choose another.')
        return username

    def clean(self):
        data = super().clean()
        if data.get('password1') and data['password1'] != data.get('password2'):
            self.add_error('password2', 'The two passwords do not match.')
        elif data.get('password1'):
            from django.contrib.auth.models import User
            from django.contrib.auth.password_validation import validate_password
            candidate = User(username=data.get('username', ''))
            try:
                validate_password(data['password1'], candidate)
            except ValidationError as exc:
                self.add_error('password1', exc)
        return data


class StaffLoginForm(ClinicLoginForm):
    """The owner chooses the sign-in of one staff member (their own username and password, with the role's limited access)."""
    username = forms.CharField(max_length=150, label='Username', help_text='Letters, digits and @ . + - _ only.')
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), strip=False)

    def __init__(self, *args, member, **kwargs):
        super().__init__(*args, clinic=member.clinic, **kwargs)
        self.member = member
        self.current_user = member.user  # keeping the same username while changing the password is fine
        self.fields['username'].initial = member.user.get_username() if member.user_id else ''


class DepartmentLoginForm(StaffLoginForm):
    """A department's sign-in only shows that department's appointments, so its password may be short and simple (4 characters or more).
    Repeated wrong guesses still lock the sign-in out."""
    MIN_LENGTH = 4

    def clean(self):
        data = forms.Form.clean(self)  # skips the strict password rules on purpose
        password = data.get('password1')
        if password and password != data.get('password2'):
            self.add_error('password2', 'The two passwords do not match.')
        elif password and len(password) < self.MIN_LENGTH:
            self.add_error('password1', f'Use at least {self.MIN_LENGTH} characters.')
        elif password and password.lower() == (data.get('username') or '').lower():
            self.add_error('password1', 'The password cannot be the same as the username.')
        return data
        self.current_user = member.user
        if member.user_id:
            self.fields['username'].initial = member.user.get_username()


class FrontDeskPatientForm(AgeOrBirthDate, forms.ModelForm):
    """What a receptionist or manager records when a patient walks in: identity and contact only, no clinical notes."""
    class Meta:
        model = Patient
        fields = ('name', 'date_of_birth', 'gender', 'phone', 'messaging_app', 'email', 'address', 'occupation', 'referral_source')
        widgets = {'date_of_birth': forms.DateInput(attrs={'type': 'date'}), 'address': forms.Textarea(attrs={'rows': 2})}
        labels = {'name': 'Full name', 'date_of_birth': 'Date of birth', 'phone': 'Phone number', 'messaging_app': 'Messages go by'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['messaging_app'].required = False

    def clean_messaging_app(self):
        return self.cleaned_data.get('messaging_app') or 'whatsapp'

    def clean_date_of_birth(self):
        from accounts.forms import PatientForm
        return PatientForm.clean_date_of_birth(self)

    def clean(self):
        data = super().clean()  # age or date of birth
        if not (data.get('phone') or '').strip():
            self.add_error('phone', 'Enter a phone number.')
        return data
