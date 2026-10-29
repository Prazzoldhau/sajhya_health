"""The price list (services and add-ons) a practice bills from, and the line items a bill is made of.

A bill still has one service text and one amount, so everything that already reads bills keeps working. When the bill is made from the price
list, its lines are kept too, so the invoice can show "Basic Physiotherapy 400 + Needling 300" and reports can add up by service.
"""
import json
from decimal import Decimal, InvalidOperation

from .models import BillLine, ServiceItem

MAX_LINES = 15
# What many physiotherapy practices start from; the practice edits prices and names afterwards.
SUGGESTED = [('Basic Physiotherapy', 400, False), ('Consultation', 200, False), ('Manual therapy', 200, True), ('Needling', 300, True),
             ('Taping', 200, True), ('Cupping', 100, True), ('CPM', 200, True)]


# Starting points for the other departments of a clinic; every practice edits the names and prices to its own.
SUGGESTED_BY_KIND = {
    'physio': SUGGESTED,
    'ot': [('OT Assessment', 500, False), ('Occupational Therapy Session', 600, False), ('Sensory Integration Session', 700, False), ('Hand Therapy Session', 600, False),
           ('Splinting', 300, True), ('Home Programme Plan', 200, True)],
    'speech': [('Speech Assessment', 600, False), ('Speech Therapy Session', 600, False), ('Language Therapy Session', 600, False), ('Voice Therapy Session', 600, False),
               ('Swallowing Therapy Session', 700, False), ('Parent Counselling', 300, True)],
    'behaviour': [('Behaviour Assessment', 700, False), ('Behaviour Therapy Session', 800, False), ('Parent Training', 500, False), ('Social Skills Group', 400, False),
                  ('Home Visit', 500, True)],
    'audiology': [('Hearing Test (Audiometry)', 500, False), ('Tympanometry', 400, False), ('Hearing Aid Trial', 300, False), ('Hearing Aid Fitting', 800, False),
                  ('Ear Mould Impression', 500, True)],
}


def kind_of(department_name):
    """Which suggested list suits a department, by its name; None for a name we do not recognise."""
    name = (department_name or '').lower()
    for key, words in (('physio', ('physio', 'physical')), ('ot', ('occupational',)), ('speech', ('speech', 'language')), ('behaviour', ('behav',)),
                       ('audiology', ('audio', 'hearing'))):
        if any(w in name for w in words):
            return key
    return None


def catalog_for(profile):
    """The active price list as plain dicts (for the bill forms' service picker). dept is the department's id, or '' for a service every department offers."""
    return [{'id': s.pk, 'name': s.name, 'price': str(s.price), 'addon': s.is_addon, 'dept': s.department_id or '', 'dept_name': s.department.name if s.department_id else ''}
            for s in ServiceItem.objects.filter(professional=profile, active=True).select_related('department')]


def seed_suggested(profile, department=None):
    """Add the standard list to a practice that has none yet (no department), or a department's suggested services (skipping names already on the list).
    Returns how many were added."""
    if department is None:
        if ServiceItem.objects.filter(professional=profile).exists():
            return 0
        for order, (name, price, addon) in enumerate(SUGGESTED):
            ServiceItem.objects.create(professional=profile, name=name, price=Decimal(price), is_addon=addon, order=order)
        return len(SUGGESTED)
    suggested = SUGGESTED_BY_KIND.get(kind_of(department.name), [])
    have = {n.lower() for n in ServiceItem.objects.filter(professional=profile).values_list('name', flat=True)}
    order = ServiceItem.objects.filter(professional=profile).count()
    added = 0
    for name, price, addon in suggested:
        if name.lower() in have:
            continue
        ServiceItem.objects.create(professional=profile, department=department, name=name, price=Decimal(price), is_addon=addon, order=order + added)
        added += 1
    return added


def parse_lines(raw):
    """The lines posted by a bill form (a JSON list of {name, price}), cleaned: trimmed names, non-negative prices, no blanks, at most MAX_LINES."""
    try:
        rows = json.loads(raw or '[]')
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []
    lines = []
    for row in rows[:MAX_LINES]:
        if not isinstance(row, dict):
            continue
        name = str(row.get('name', '')).strip()[:150]
        try:
            price = Decimal(str(row.get('price', '0')))
        except InvalidOperation:
            continue
        if name and price >= 0 and price < Decimal('10000000'):
            lines.append((name, price.quantize(Decimal('0.01'))))
    return lines


def save_lines(entry, raw):
    """Keep the posted lines with a new bill. They are only a breakdown: the bill's own amount (which can be a discounted total) stays what counts."""
    for order, (name, price) in enumerate(parse_lines(raw)):
        BillLine.objects.create(entry=entry, name=name, price=price, order=order)
