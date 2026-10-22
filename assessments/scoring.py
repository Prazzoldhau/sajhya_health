"""Scoring engine: turns submitted answers into a score and an interpretation. Pure functions, no database writes."""
from decimal import Decimal, InvalidOperation


def parse_options(text):
    """'4|Independent\n3|Needs help' -> [{'value': Decimal('4'), 'label': 'Independent'}, ...] (blank/bad lines are skipped)."""
    options = []
    for line in (text or '').splitlines():
        if '|' not in line:
            continue
        raw, label = line.split('|', 1)
        try:
            options.append({'value': Decimal(raw.strip()), 'label': label.strip()})
        except InvalidOperation:
            continue
    return options


def _item_max(item):
    if item.input_type == item.CHOICE:
        values = [o['value'] for o in item.options]
        return max(values) if values else None
    return item.max_value


def max_score(scale):
    from .models import AssessmentScale
    if scale.scoring == AssessmentScale.PERCENT:
        return Decimal(100)
    items = list(scale.items.all())
    if not items:
        return None
    if scale.scoring == AssessmentScale.SINGLE:
        return _item_max(items[0])
    maxima = [_item_max(i) for i in items]
    return None if any(m is None for m in maxima) else sum(maxima, Decimal(0))


def fmt(value):
    """Decimal -> '4', '1.5' (no trailing zeros)."""
    if value is None:
        return ''
    text = f'{value:f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


def score_answers(scale, raw):
    """raw: {item_id (int): submitted string}. Returns (result, errors).
    result is None when nothing was answered (the scale is simply skipped); otherwise a dict with answers/score/max_score."""
    from .models import AssessmentScale
    answers, errors, got = [], [], {}
    for item in scale.items.all():
        text = (raw.get(item.pk) or '').strip()
        if not text:
            if item.required:
                errors.append(item)
            continue
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None, [f'"{item.label}": enter a number.']
        if item.input_type == item.CHOICE:
            match = next((o for o in item.options if o['value'] == value), None)
            if match is None:
                return None, [f'"{item.label}": pick one of the listed options.']
            value_label = match['label']
        else:
            if (item.min_value is not None and value < item.min_value) or (item.max_value is not None and value > item.max_value):
                return None, [f'"{item.label}": must be between {fmt(item.min_value)} and {fmt(item.max_value)}.']
            value_label = ''
        got[item.pk] = (item, value)
        answers.append({'code': item.code, 'label': item.label, 'value': fmt(value), 'value_label': value_label})
    if not answers:
        return None, []
    if errors:
        names = ', '.join(f'"{i.label}"' for i in errors[:3]) + ('...' if len(errors) > 3 else '')
        return None, [f'{scale.short_name}: please answer every question (missing {names}), or clear the whole scale to skip it.']

    values = [v for _, v in got.values()]
    if scale.scoring == AssessmentScale.SINGLE:
        score, top = values[0], _item_max(next(iter(got.values()))[0])
    elif scale.scoring == AssessmentScale.PERCENT:
        possible = sum((_item_max(i) or Decimal(0) for i, _ in got.values()), Decimal(0))
        score, top = (round(sum(values, Decimal(0)) / possible * 100, 1) if possible else Decimal(0)), Decimal(100)
    else:
        score, top = sum(values, Decimal(0)), max_score(scale)
    return {'answers': answers, 'score': score, 'max_score': top}, []


def interpret(scale, score):
    """(label, tone) of the band holding the score, or ('', '')."""
    for band in scale.bands.all():
        if band.min_score <= score <= band.max_score:
            return band.label, band.tone
    return '', ''


def change(latest, earlier):
    """How a result compares with an earlier one for the same scale: (text, tone). Uses the scale's direction and MCID."""
    if latest is None or earlier is None or latest.score is None or earlier.score is None:
        return '', ''
    diff = latest.score - earlier.score
    if diff == 0:
        return 'No change', 'ok'
    better = (diff > 0) == latest.higher_is_better
    meaningful = latest.mcid is None or abs(diff) >= latest.mcid
    sign = '+' if diff > 0 else '-'
    word = 'Improved' if better else 'Worse'
    note = '' if meaningful else ' (below the minimal important change)'
    return f'{word} {sign}{fmt(abs(diff))}{note}', ('good' if better else 'bad') if meaningful else 'ok'
