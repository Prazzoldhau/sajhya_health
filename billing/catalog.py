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


def catalog_for(profile):
    """The active price list as plain dicts (for the bill forms' service picker)."""
    return [{'id': s.pk, 'name': s.name, 'price': str(s.price), 'addon': s.is_addon}
            for s in ServiceItem.objects.filter(professional=profile, active=True)]


def seed_suggested(profile):
    """Add the standard list to a practice that has none yet. Returns how many were added."""
    if ServiceItem.objects.filter(professional=profile).exists():
        return 0
    for order, (name, price, addon) in enumerate(SUGGESTED):
        ServiceItem.objects.create(professional=profile, name=name, price=Decimal(price), is_addon=addon, order=order)
    return len(SUGGESTED)


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
