from datetime import timedelta
from decimal import Decimal

from django.db import migrations
from django.utils import timezone

# Content and prices come from the package page of the original Sajhya project.
# The Clinic and Enterprise prices are not published there, so they are left as custom pricing; set them in the admin.
PLANS = [
    dict(code='client', name='Client', tagline='Free, Always', icon='user', price_monthly=Decimal('0'), trial_days=0, patient_limit=None, sort_order=1, features=[
        {'text': 'Book lab tests & appointments', 'included': True},
        {'text': 'Shop Marketplace & Pharmacy', 'included': True},
        {'text': 'Track prescriptions & exercises', 'included': True},
        {'text': 'Connect with your physio', 'included': True},
        {'text': 'No credit card needed', 'included': True},
    ]),
    dict(code='professional', name='Professional', tagline='For Solo Practitioners', icon='user-md', price_monthly=Decimal('1000'), trial_days=14, patient_limit=500, sort_order=2, features=[
        {'text': 'Personal appointment management', 'included': True},
        {'text': 'Patient records (up to 500)', 'included': True},
        {'text': 'Basic reporting & analytics', 'included': True},
        {'text': 'Mobile app access', 'included': True},
        {'text': 'Email & SMS reminders', 'included': True},
        {'text': 'Staff management', 'included': False},
        {'text': 'Multi-branch support', 'included': False},
    ]),
    dict(code='clinic', name='Clinic', tagline='For Growing Practices', icon='clinic-medical', price_monthly=None, trial_days=0, patient_limit=None, sort_order=3, features=[
        {'text': 'Everything in Professional +', 'included': True},
        {'text': 'Multi-doctor management', 'included': True},
        {'text': 'Staff roles & permissions', 'included': True},
        {'text': 'Room & resource scheduling', 'included': True},
        {'text': 'Pharmacy integration', 'included': True},
        {'text': 'Diagnostic lab integration', 'included': True},
        {'text': 'Unlimited patient records', 'included': True},
        {'text': 'Multi-branch support', 'included': False},
    ]),
    dict(code='enterprise', name='Enterprise', tagline='For Large Healthcare Groups', icon='building', price_monthly=None, trial_days=0, patient_limit=None, sort_order=4, features=[
        {'text': 'Everything in Clinic +', 'included': True},
        {'text': 'Multi-branch management', 'included': True},
        {'text': 'Enterprise-wide analytics', 'included': True},
        {'text': 'Advanced compliance & reporting', 'included': True},
        {'text': 'Corporate billing & insurance', 'included': True},
        {'text': 'API access for integrations', 'included': True},
        {'text': 'Dedicated account manager', 'included': True},
        {'text': '24/7 priority support', 'included': True},
    ]),
]


def seed(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    Subscription = apps.get_model('billing', 'Subscription')
    Account = apps.get_model('accounts', 'Account')
    for row in PLANS:
        Plan.objects.update_or_create(code=row['code'], defaults={k: v for k, v in row.items() if k != 'code'})
    # accounts that existed before plans: give them their plan (paid plans start a fresh trial)
    today = timezone.localdate()
    for account in Account.objects.filter(subscription__isnull=True):
        plan = Plan.objects.filter(code=account.account_type).first()
        if plan:
            Subscription.objects.create(account=account, plan=plan, started_on=today,
                                        trial_ends=today + timedelta(days=plan.trial_days) if plan.trial_days else None)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_account_plans'),
        ('accounts', '0012_treatment_plans'),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
