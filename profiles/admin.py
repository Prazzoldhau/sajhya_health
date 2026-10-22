from django.contrib import admin

from .models import AidEntry, LabEntry, MedicineEntry, NursingEntry, PatientProfile, TherapyNote

for model in (PatientProfile, MedicineEntry, NursingEntry, AidEntry, TherapyNote, LabEntry):
    admin.site.register(model)
