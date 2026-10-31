from django.contrib import admin

from .models import (ExerciseFeedback, ExerciseMain, ExerciseStepImage, Prescription, PrescriptionExercise,
                     Region, SubRegion)


class StepImageInline(admin.TabularInline):
    model = ExerciseStepImage
    extra = 0


@admin.register(ExerciseMain)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('exercise_name', 'discipline', 'sub_region_fk', 'exercise_type', 'difficulty_level', 'default_sets', 'default_reps')
    list_filter = ('discipline', 'sub_region_fk__region_fk', 'sub_region_fk', 'difficulty_level')
    search_fields = ('exercise_name', 'exercise_type')
    inlines = [StepImageInline]


class PrescriptionExerciseInline(admin.TabularInline):
    model = PrescriptionExercise
    extra = 0


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'condition_label', 'status', 'created_at')
    list_filter = ('status',)
    inlines = [PrescriptionExerciseInline]


admin.site.register(Region)
admin.site.register(SubRegion)
admin.site.register(ExerciseFeedback)
