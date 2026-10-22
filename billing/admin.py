from django.contrib import admin

from django.contrib import messages

from .models import BillingEntry, PackagePayment, PatientAllowance, PatientPackage, Plan, SlotOrder


@admin.register(BillingEntry)
class BillingEntryAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'patient_name', 'service', 'rate', 'payment_mode', 'entry_date')
    list_filter = ('payment_mode', 'entry_date')
    search_fields = ('invoice_number', 'patient_name')


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'price_monthly', 'price_note', 'patient_limit', 'sort_order')
    list_editable = ('price_monthly', 'patient_limit', 'sort_order')


class PaymentInline(admin.TabularInline):
    model = PackagePayment
    extra = 0


@admin.register(PatientPackage)
class PatientPackageAdmin(admin.ModelAdmin):
    list_display = ('patient', 'duration', 'sessions_used', 'total_sessions', 'total_amount', 'amount_paid', 'status')
    list_filter = ('status', 'duration')
    inlines = [PaymentInline]


@admin.register(PatientAllowance)
class PatientAllowanceAdmin(admin.ModelAdmin):
    list_display = ('professional', 'free_limit', 'paid_slots', 'rate')
    search_fields = ('professional__first_name', 'professional__last_name', 'professional__account__user__username')


@admin.register(SlotOrder)
class SlotOrderAdmin(admin.ModelAdmin):
    list_display = ('professional', 'quantity', 'amount', 'status', 'requested_at', 'paid_at')
    list_filter = ('status',)
    search_fields = ('professional__first_name', 'professional__last_name', 'professional__account__user__username')
    actions = ['mark_paid']

    @admin.action(description='Mark paid and add the slots to the professional')
    def mark_paid(self, request, queryset):
        done = sum(1 for order in queryset.exclude(status=SlotOrder.CANCELLED) if order.mark_paid(request.user))
        self.message_user(request, f'{done} order(s) marked paid; slots added.', messages.SUCCESS)
