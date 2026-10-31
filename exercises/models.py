from urllib.parse import quote

from django.db import models
from django.utils import timezone

from assessments.disciplines import DISCIPLINE_CHOICES


class Region(models.Model):
    region_name = models.CharField(max_length=100)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.region_name

    @property
    def label(self):
        return self.region_name.replace('_', ' ')


class SubRegion(models.Model):
    region_fk = models.ForeignKey(Region, verbose_name='Region', on_delete=models.CASCADE, related_name='subregions')
    sub_region_name = models.CharField(max_length=100)

    class Meta:
        ordering = ['sub_region_name']

    def __str__(self):
        return self.sub_region_name


class DifficultyLevel(models.IntegerChoices):
    BEGINNER = 1, 'Beginner'
    INTERMEDIATE = 2, 'Intermediate'
    ADVANCED = 3, 'Advanced'
    SUPER = 4, 'Super Level'


class ExerciseMain(models.Model):
    """The exercise library entry. exercise_type is free text: the imported catalogue uses
    ~60 descriptive types ("Active-Assisted", "Gait Training", ...) rather than a fixed list."""
    sub_region_fk = models.ForeignKey(SubRegion, verbose_name='Sub-region', on_delete=models.CASCADE, related_name='exercises')
    discipline = models.CharField(max_length=10, choices=DISCIPLINE_CHOICES, default='physio', db_index=True,
                                  help_text='Which department\'s library this belongs to. Physiotherapists see physiotherapy and general exercises, occupational therapists occupational therapy and general ones, and so on.')
    exercise_name = models.CharField(max_length=100)
    exercise_type = models.CharField(max_length=50, db_index=True)
    difficulty_level = models.IntegerField(choices=DifficultyLevel.choices)

    default_sets = models.IntegerField()
    default_reps = models.IntegerField()
    hold_time_sec = models.IntegerField()
    default_rest_time_sec = models.IntegerField(default=60)

    exercise_description = models.TextField(blank=True, default='')
    exercise_description_nepali = models.TextField(blank=True, default='')
    exercise_url = models.CharField('Image path', max_length=300, blank=True, default='',
                                    help_text='Static path of the main image, e.g. /static/exercises/knee/lunge.png')
    youtube_url = models.URLField(blank=True, default='', help_text='Link to a YouTube demonstration')
    hosted_video_url = models.URLField(blank=True, default='',
                                       help_text='Direct video file URL played embedded; takes priority over the YouTube link')

    class Meta:
        ordering = ['exercise_name']
        indexes = [models.Index(fields=['sub_region_fk', 'exercise_name'])]

    def __str__(self):
        return self.exercise_name

    @property
    def images(self):
        """Ordered image URLs: the step-by-step sequence if there is one, else the single main image."""
        steps = [s.image_url for s in self.step_images.all()]
        if steps:
            return [quote(u, safe='/:') for u in steps]
        return [quote(self.exercise_url, safe='/:')] if self.exercise_url else []

    @property
    def cover(self):
        images = self.images
        return images[0] if images else ''

    @property
    def dose_label(self):
        parts = [f'{self.default_sets} sets × {self.default_reps} reps']
        if self.hold_time_sec:
            parts.append(f'hold {self.hold_time_sec}s')
        return ', '.join(parts)


class ExerciseStepImage(models.Model):
    """One frame of an exercise's step-by-step image sequence (starting position -> end position)."""
    exercise = models.ForeignKey(ExerciseMain, on_delete=models.CASCADE, related_name='step_images')
    order = models.PositiveSmallIntegerField(help_text='1-based step number')
    image_url = models.CharField(max_length=300)
    label = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        ordering = ['order', 'id']
        unique_together = ['exercise', 'order']

    def __str__(self):
        return f'{self.exercise.exercise_name} - step {self.order}'


class Prescription(models.Model):
    """A set of exercises a professional prescribes to one patient."""
    ACTIVE, COMPLETED, CANCELLED, SUPERSEDED = 'active', 'completed', 'cancelled', 'superseded'
    STATUS_CHOICES = [(ACTIVE, 'Active'), (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled'), (SUPERSEDED, 'Superseded')]

    patient = models.ForeignKey('accounts.Patient', on_delete=models.CASCADE, related_name='prescriptions')
    professional = models.ForeignKey('accounts.ProfessionalProfile', on_delete=models.CASCADE, related_name='prescriptions')
    condition_label = models.CharField(max_length=100, blank=True,
                                       help_text='Condition / body part this prescription is for, e.g. "Post-op knee"')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    prescription_date = models.DateTimeField(null=True, blank=True, help_text='The date printed on the prescription (live site).')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Prescription #{self.pk} - {self.patient.name}'

    def save(self, *args, **kwargs):
        """A new prescription supersedes the patient's earlier active ones (kept, not deleted, for history)."""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and self.status == self.ACTIVE:
            Prescription.objects.filter(patient_id=self.patient_id, status=self.ACTIVE).exclude(pk=self.pk).update(status=self.SUPERSEDED)

    @property
    def total_exercises(self):
        return self.exercises.count()

    @property
    def completion_percentage(self):
        total = self.exercises.count()
        return round(self.exercises.filter(is_completed=True).count() / total * 100) if total else 0

    @property
    def is_expired(self):
        return bool(self.end_date and self.status == self.ACTIVE and timezone.localdate() > self.end_date)


class PrescriptionExercise(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name='exercises')
    exercise = models.ForeignKey(ExerciseMain, on_delete=models.SET_NULL, null=True, blank=True, related_name='prescription_exercises')
    # snapshot, so the prescription still reads correctly if the library entry changes or is removed
    exercise_name = models.CharField(max_length=200)
    difficulty_level = models.IntegerField(choices=DifficultyLevel.choices, default=1)
    sets = models.PositiveSmallIntegerField(default=3)
    reps = models.PositiveSmallIntegerField(default=10)
    hold_time_sec = models.PositiveSmallIntegerField(default=0)
    rest_time_sec = models.PositiveSmallIntegerField(default=60)
    order = models.PositiveSmallIntegerField(default=0)
    schedule_morning = models.BooleanField(default=True)
    schedule_day = models.BooleanField(default=False)
    schedule_evening = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    library_exercise_id = models.IntegerField(null=True, blank=True, help_text='Id of the library exercise at the time (live site kept it as a plain number).')
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['order', 'id']

    @property
    def cover(self):
        """Thumbnail URL from the live library entry ('' if it was removed or has no picture)."""
        return self.exercise.cover if self.exercise_id else ''

    def __str__(self):
        return self.exercise_name

    @property
    def dose_label(self):
        label = f'{self.sets} × {self.reps}'
        return f'{label}, hold {self.hold_time_sec}s' if self.hold_time_sec else label

    @property
    def schedule_label(self):
        slots = [name for name, on in (('Morning', self.schedule_morning), ('Day', self.schedule_day), ('Evening', self.schedule_evening)) if on]
        return ' · '.join(slots) or 'Any time'


class ExerciseFeedback(models.Model):
    FEEDBACK_CHOICES = [('normal', 'Normal'), ('hard', 'Hard'), ('painful', 'Painful'), ('increased_symptom', 'Increased symptom')]

    prescription_exercise = models.ForeignKey(PrescriptionExercise, on_delete=models.CASCADE, related_name='feedback_logs')
    feedback_type = models.CharField(max_length=30, choices=FEEDBACK_CHOICES)
    note = models.CharField(max_length=300, blank=True, default='')
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-logged_at']

    def __str__(self):
        return f'{self.prescription_exercise.exercise_name} - {self.feedback_type}'
