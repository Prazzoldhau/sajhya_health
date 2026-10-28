"""Check that the money figures agree with the ledger behind them, and report anything that does not.

    python manage.py check_money

Every bill keeps a running "received" total and a list of payments; every package the same; every patient's advance is the sum of its moves.
They are updated together, so they should always match. If a crash, a manual edit in the admin or an old bug ever made them drift, this lists
exactly which rows to look at (it changes nothing). Exit status is 1 when something is wrong, so it can be run on a schedule.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from billing.models import BillingEntry, PatientAdvance, PatientPackage


class Command(BaseCommand):
    help = 'List bills, packages and advances whose totals do not match their payments (changes nothing).'

    def handle(self, *args, **options):
        problems = []
        for entry in BillingEntry.objects.annotate(ledger=Sum('payments__amount')).iterator():
            ledger = entry.ledger or Decimal('0')
            if ledger != entry.amount_paid:
                problems.append(f'Bill {entry.invoice_number}: received total {entry.amount_paid} but its payments add up to {ledger}')
            if entry.amount_paid > entry.rate:
                problems.append(f'Bill {entry.invoice_number}: received {entry.amount_paid} is more than the bill ({entry.rate})')
        for package in PatientPackage.objects.select_related('patient').annotate(ledger=Sum('payments__amount')).iterator():
            ledger = package.ledger or Decimal('0')
            if ledger != package.amount_paid:
                problems.append(f'Package #{package.pk} ({package.patient.name}): paid total {package.amount_paid} but its payments add up to {ledger}')
        for row in PatientAdvance.objects.values('patient_id', 'patient__name').annotate(total=Sum('amount')):
            if row['total'] < 0:
                problems.append(f"Advance of {row['patient__name']} (patient #{row['patient_id']}) is negative: {row['total']}")
        for line in problems:
            self.stdout.write(self.style.ERROR(line))
        if problems:
            raise CommandError(f'{len(problems)} money problem(s) found. Nothing was changed.')
        self.stdout.write(self.style.SUCCESS('Money checks out: every bill, package and advance matches its payments.'))
