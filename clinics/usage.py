"""Monthly patient enrolment of a clinic and the charge for going over the cap.

A clinic may enrol `monthly_patient_cap` (default 400) new patients per calendar month. Each one above the cap is added as a due
(`overage_rate`, default NPR 200) that is collected before the clinic's next billing. "Enrolled" means a patient record registered
inside the clinic in that month (Patient.clinic is the clinic and created_at falls in the month, Nepal time).
Months are refreshed from the patient records until staff mark them paid; a paid month is frozen.
"""
import datetime

from django.utils import timezone

from accounts.models import Patient

from .models import ClinicMonthlyUsage, ClinicSubscription, default_cap, default_overage_rate


def first_of_month(day):
    return day.replace(day=1)


def previous_month(first):
    return (first - datetime.timedelta(days=1)).replace(day=1)


def next_month(first):
    return (first + datetime.timedelta(days=32)).replace(day=1)


def enrolled_in_month(clinic, first):
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.datetime.combine(first, datetime.time.min), tz)
    hi = timezone.make_aware(datetime.datetime.combine(next_month(first), datetime.time.min), tz)
    return Patient.objects.filter(clinic=clinic, created_at__gte=lo, created_at__lt=hi).count()


def refresh(clinic, first):
    """The (up to date) usage row for one month. Paid months are left exactly as they were."""
    usage, _ = ClinicMonthlyUsage.objects.get_or_create(clinic=clinic, month=first)
    if usage.status == ClinicMonthlyUsage.PAID:
        return usage
    sub = ClinicSubscription.objects.filter(professional_id=clinic.owner_id).first()
    usage.cap = sub.monthly_patient_cap if sub else default_cap()
    usage.rate = sub.overage_rate if sub else default_overage_rate()
    usage.enrolled = enrolled_in_month(clinic, first)
    usage.overage = max(0, usage.enrolled - usage.cap)
    usage.amount_due = usage.overage * usage.rate
    usage.status = ClinicMonthlyUsage.DUE if usage.overage else ClinicMonthlyUsage.OPEN
    usage.save()
    return usage


def summary(clinic, months=6):
    """This month plus the previous `months - 1`, newest first, and what is unpaid in total (never before the clinic existed)."""
    this = first_of_month(timezone.localdate())
    earliest = first_of_month(timezone.localtime(clinic.created_at).date())
    rows, cursor = [], this
    while len(rows) < months and cursor >= earliest:
        rows.append(refresh(clinic, cursor))
        cursor = previous_month(cursor)
    unpaid = ClinicMonthlyUsage.objects.filter(clinic=clinic, status=ClinicMonthlyUsage.DUE)
    # months older than the window that are still unpaid must not disappear from the total
    for usage in unpaid.exclude(month__in=[r.month for r in rows]):
        rows.append(refresh(clinic, usage.month))
    current = rows[0] if rows and rows[0].month == this else refresh(clinic, this)
    total_due = sum((r.amount_due for r in rows if r.status == ClinicMonthlyUsage.DUE), 0)
    return {'current': current, 'rows': rows, 'total_due': total_due,
            'percent': min(100, round(100 * current.enrolled / current.cap)) if current.cap else 0,
            'near_cap': current.cap and current.enrolled >= 0.9 * current.cap and not current.overage, 'over_cap': bool(current.overage)}
