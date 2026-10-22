from django.core.management.base import BaseCommand
from django.utils import timezone

from clinics import usage
from clinics.models import Clinic


class Command(BaseCommand):
    help = ('Refresh every clinic\'s monthly patient-enrolment usage (this month and the previous one) and print what is due. '
            'Run it on the 1st of each month (cron) so the dues are ready before billing; it is safe to run any time.')

    def handle(self, *args, **options):
        this = usage.first_of_month(timezone.localdate())
        total = 0
        for clinic in Clinic.objects.filter(is_active=True).select_related('owner'):
            for month in (usage.previous_month(this), this):
                row = usage.refresh(clinic, month)
                if row.amount_due and row.status == row.DUE:
                    total += row.amount_due
                    self.stdout.write(f'{clinic.name} ({clinic.code}) {month:%Y-%m}: {row.enrolled} enrolled, {row.overage} over the cap of {row.cap} -> NPR {row.amount_due:.0f} due')
        self.stdout.write(f'Total due across clinics: NPR {total:.0f}')
