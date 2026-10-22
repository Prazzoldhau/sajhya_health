from django.contrib import admin

from .models import PatientLink, PortalInvite


@admin.register(PatientLink)
class PatientLinkAdmin(admin.ModelAdmin):
    list_display = ('user', 'patient', 'linked_at')
    search_fields = ('user__username', 'patient__name')


@admin.register(PortalInvite)
class PortalInviteAdmin(admin.ModelAdmin):
    list_display = ('patient', 'created_by', 'created_at', 'expires_at', 'used_at', 'failed_attempts')
    readonly_fields = ('code_hash',)
