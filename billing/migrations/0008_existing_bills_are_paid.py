from django.db import migrations


def mark_existing_paid(apps, schema_editor):
    """Before credit existed every bill was taken in full, so each old bill gets one payment on its own date."""
    Entry, Payment = apps.get_model('billing', 'BillingEntry'), apps.get_model('billing', 'EntryPayment')
    for entry in Entry.objects.filter(amount_paid=0).iterator():
        Payment.objects.create(entry=entry, amount=entry.rate, payment_mode=entry.payment_mode, paid_on=entry.entry_date)
        Entry.objects.filter(pk=entry.pk).update(amount_paid=entry.rate)


class Migration(migrations.Migration):
    dependencies = [('billing', '0007_entry_credit')]
    operations = [migrations.RunPython(mark_existing_paid, migrations.RunPython.noop)]
