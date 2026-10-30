from django.core.management.base import BaseCommand

from assessments import clinical_forms
from assessments.models import ClinicalForm


class Command(BaseCommand):
    help = 'Add the shipped clinical assessment forms (such as the paediatric occupational therapy assessment), or update them when their questions changed. Filled-in records are never touched.'

    def handle(self, *args, **options):
        clinical_forms.sync(ClinicalForm)
        self.stdout.write(self.style.SUCCESS(f'{ClinicalForm.objects.count()} clinical form(s) available.'))
