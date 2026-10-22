from django.contrib import admin

from .models import LabTest, LabTestPanel, LabTestRequest, LabTestRequestItem


@admin.register(LabTest)
class LabTestAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'turnaround_time', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    list_editable = ('price', 'is_active')


@admin.register(LabTestPanel)
class LabTestPanelAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'is_featured', 'is_active')
    filter_horizontal = ('tests',)


class ItemInline(admin.TabularInline):
    model = LabTestRequestItem
    extra = 0


@admin.register(LabTestRequest)
class LabTestRequestAdmin(admin.ModelAdmin):
    list_display = ('request_number', 'customer_name', 'customer_phone', 'status', 'total_amount', 'created_at')
    list_filter = ('status',)
    search_fields = ('request_number', 'customer_name', 'customer_phone')
    inlines = [ItemInline]
