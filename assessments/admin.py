from django.contrib import admin

from .models import AssessmentForm, AssessmentResult, AssessmentScale, AssessmentSession, FormScale, ScaleItem, ScoreBand


class ItemInline(admin.StackedInline):
    model = ScaleItem
    extra = 0
    fields = ('order', 'code', 'section', 'label', 'help_text', 'input_type', 'options_text', ('min_value', 'max_value'), 'required')


class BandInline(admin.TabularInline):
    model = ScoreBand
    extra = 0


@admin.register(AssessmentScale)
class ScaleAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation', 'category', 'scoring', 'version', 'is_active')
    list_filter = ('category', 'scoring', 'is_active')
    search_fields = ('name', 'abbreviation', 'code')
    prepopulated_fields = {'code': ('abbreviation',)}
    inlines = [BandInline, ItemInline]


class FormScaleInline(admin.TabularInline):
    model = FormScale
    extra = 1


@admin.register(AssessmentForm)
class FormAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active')
    inlines = [FormScaleInline]


class ResultInline(admin.TabularInline):
    model = AssessmentResult
    extra = 0
    readonly_fields = ('scale_name', 'score', 'max_score', 'interpretation')
    fields = readonly_fields
    can_delete = False


@admin.register(AssessmentSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('patient', 'form_name', 'assessed_on', 'assessor')
    date_hierarchy = 'assessed_on'
    inlines = [ResultInline]
