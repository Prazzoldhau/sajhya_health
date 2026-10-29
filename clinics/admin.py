import datetime

from django.contrib import admin, messages
from django.utils import timezone

from django import forms

from .modules import MODULES
from .models import Clinic, ClinicMember, ClinicMonthlyUsage, ClinicSubscription, QueueEntry


@admin.register(ClinicSubscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('professional', 'status', 'clinic_limit', 'requested_at', 'activated_at', 'expires_at')
    list_filter = ('status',)
    search_fields = ('professional__first_name', 'professional__last_name', 'professional__account__user__username')
    actions = ['activate_one_year', 'activate_no_expiry', 'decline']

    def _activate(self, request, queryset, expires):
        for sub in queryset:
            sub.status, sub.activated_at, sub.expires_at, sub.reviewed_by, sub.staff_note = ClinicSubscription.ACTIVE, timezone.now(), expires, request.user, ''
            sub.save()
        self.message_user(request, f'{queryset.count()} Clinic plan(s) activated.', messages.SUCCESS)

    @admin.action(description='Activate Clinic plan for 1 year')
    def activate_one_year(self, request, queryset):
        self._activate(request, queryset, timezone.localdate() + datetime.timedelta(days=365))

    @admin.action(description='Activate Clinic plan with no expiry')
    def activate_no_expiry(self, request, queryset):
        self._activate(request, queryset, None)

    @admin.action(description='Decline request (add the reason in "Staff note" first if you like)')
    def decline(self, request, queryset):
        queryset.update(status=ClinicSubscription.REJECTED, reviewed_by=request.user)


class MemberInline(admin.TabularInline):
    model = ClinicMember
    extra = 0


class ClinicAdminForm(forms.ModelForm):
    modules = forms.MultipleChoiceField(choices=[(key, f'{name} - {what}') for key, name, what, _ in MODULES], widget=forms.CheckboxSelectMultiple, required=False,
                                        help_text='Tick the parts of the workspace this clinic has in its plan. Patients, queue, team and settings are always included.')

    class Meta:
        model = Clinic
        fields = '__all__'


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    form = ClinicAdminForm
    list_display = ('name', 'code', 'owner', 'phone', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code', 'pan_number')
    inlines = [MemberInline]


admin.site.register(QueueEntry)


@admin.register(ClinicMonthlyUsage)
class UsageAdmin(admin.ModelAdmin):
    list_display = ('clinic', 'month', 'enrolled', 'cap', 'overage', 'amount_due', 'status')
    list_filter = ('status', 'month')
    search_fields = ('clinic__name', 'clinic__code')
    actions = ['mark_paid']

    @admin.action(description='Mark as paid (freezes the month)')
    def mark_paid(self, request, queryset):
        from django.utils import timezone
        done = queryset.filter(status=ClinicMonthlyUsage.DUE).update(status=ClinicMonthlyUsage.PAID, paid_at=timezone.now())
        self.message_user(request, f'{done} month(s) marked paid.', messages.SUCCESS)
