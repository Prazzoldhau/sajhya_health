from django.contrib import admin

from .models import SoapAddendum, SoapNote


class AddendumInline(admin.TabularInline):
    model = SoapAddendum
    extra = 0
    readonly_fields = ('author_name', 'created_at')


@admin.register(SoapNote)
class SoapNoteAdmin(admin.ModelAdmin):
    list_display = ('patient', 'note_type', 'note_date', 'status', 'author_name')
    list_filter = ('status', 'note_type')
    search_fields = ('patient__name', 'chief_complaint', 'author_name')
    inlines = [AddendumInline]
