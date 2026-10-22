from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (Account, TreatmentPlan, Appointment, Task, Icd10Code, Patient, Visit, ClinicalFocus, ClinicType, EnterpriseType, ProfessionalProfile,
                     Profession, ServiceType)

admin.site.register(Profession)
admin.site.register(ClinicType)
admin.site.register(EnterpriseType)
admin.site.register(ClinicalFocus)
admin.site.register(ServiceType)
admin.site.register(Account)
admin.site.register(Patient)
admin.site.register(Visit)


@admin.register(ProfessionalProfile)
class ProfessionalProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'title', 'license_number', 'license_expiry', 'status', 'submitted_at')
    list_filter = ('status',)
    search_fields = ('first_name', 'last_name', 'license_number', 'mobile')
    readonly_fields = ('document_links',)

    @admin.display(description='Uploaded documents')
    def document_links(self, obj):
        links = []
        for field in ProfessionalProfile.DOCUMENT_FIELDS:
            if getattr(obj, field):
                url = reverse('accounts:professional-document-staff', args=[obj.pk, field])
                links.append(format_html('<a href="{}" target="_blank">{}</a>', url, field.replace('_', ' ')))
        return format_html(' | '.join(['{}'] * len(links)), *links) if links else '-'


@admin.register(Icd10Code)
class Icd10CodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'title')
    search_fields = ('code', 'title')

admin.site.register(Appointment)
admin.site.register(Task)

admin.site.register(TreatmentPlan)
