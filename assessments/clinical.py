"""Turning a ClinicalForm definition into something to fill in, reading the posted answers back, and summarising them for display.

Posted names: f_<key> for a plain field (f_<key>__detail for a yes / no note, f_<key>__other for the "others" box of a tick list) and
g_<key>__<row number>__<column key> for a table cell. Answers are kept as plain JSON:
  text / textarea / date / choice -> "text"
  multi  -> {"values": [...], "other": "..."}      yesno -> {"value": "Yes", "detail": "..."}
  grid   -> [{"row": "Head control", "status": "Attained", "age": "3 months"}, ...] (only rows that have an answer)
"""
MAX_TEXT, MAX_AREA = 300, 5000


def prefilled(patient):
    return {'name': patient.name, 'age': '' if patient.age is None else str(patient.age), 'gender': patient.get_gender_display() if patient.gender else '',
            'diagnosis': patient.diagnosis}


def _options(options, chosen):
    chosen = chosen if isinstance(chosen, (list, tuple)) else [chosen]
    return [{'label': o, 'checked': o in chosen} for o in options]


def build(definition, answers=None, patient=None):
    """The sections and fields ready for the fill template, each with its input names and any current values."""
    answers = answers or {}
    pre = prefilled(patient) if patient is not None else {}
    sections = []
    for section in definition.get('sections', []):
        fields = []
        for f in section['fields']:
            key, kind, value = f['key'], f['type'], answers.get(f['key'])
            item = {**f, 'name': f'f_{key}', 'kind': kind}
            if kind in ('text', 'textarea', 'date'):
                item['value'] = value if value is not None else pre.get(f.get('prefill', ''), '')
            elif kind == 'choice':
                item['choices'] = _options(f['options'], value or '')
            elif kind == 'multi':
                value = value or {}
                item['choices'] = _options(f['options'], value.get('values', []))
                item['other_name'], item['other_value'] = f'f_{key}__other', value.get('other', '')
            elif kind == 'yesno':
                value = value or {}
                item['choices'] = _options(['Yes', 'No'], value.get('value', ''))
                item['detail_name'], item['detail_value'] = f'f_{key}__detail', value.get('detail', '')
            elif kind == 'grid':
                saved = {r['row']: r for r in (value or [])}
                rows = []
                for i, label in enumerate(f['rows']):
                    entry, cells = saved.get(label, {}), []
                    for col in f['cols']:
                        name = f'g_{key}__{i}__{col["key"]}'
                        current = entry.get(col['key'], '' if col['type'] != 'check' else [])
                        cell = {'col': col, 'name': name, 'type': col['type']}
                        if col['type'] == 'text':
                            cell['value'] = current
                        else:
                            cell['choices'] = _options(col['options'], current)
                        cells.append(cell)
                    rows.append({'label': label, 'cells': cells})
                item['rows'], item['columns'] = rows, f['cols']
            fields.append(item)
        sections.append({'title': section['title'], 'fields': fields})
    return sections


def parse(definition, data):
    """The answers in a posted form (a QueryDict), keeping only known options and trimming long text."""
    answers = {}
    for section in definition.get('sections', []):
        for f in section['fields']:
            key, kind, name = f['key'], f['type'], f'f_{f["key"]}'
            if kind in ('text', 'textarea', 'date'):
                text = data.get(name, '').strip()[:MAX_AREA if kind == 'textarea' else MAX_TEXT]
                if text:
                    answers[key] = text
            elif kind == 'choice':
                if data.get(name) in f['options']:
                    answers[key] = data.get(name)
            elif kind == 'multi':
                values = [v for v in data.getlist(name) if v in f['options']]
                other = data.get(f'{name}__other', '').strip()[:MAX_TEXT] if f.get('other') else ''
                if values or other:
                    answers[key] = {'values': values, 'other': other}
            elif kind == 'yesno':
                value = data.get(name) if data.get(name) in ('Yes', 'No') else ''
                detail = data.get(f'{name}__detail', '').strip()[:MAX_TEXT]
                if value or detail:
                    answers[key] = {'value': value, 'detail': detail}
            elif kind == 'grid':
                rows = []
                for i, label in enumerate(f['rows']):
                    entry = {}
                    for col in f['cols']:
                        cell = f'g_{key}__{i}__{col["key"]}'
                        if col['type'] == 'radio':
                            if data.get(cell) in col['options']:
                                entry[col['key']] = data.get(cell)
                        elif col['type'] == 'check':
                            picked = [v for v in data.getlist(cell) if v in col['options']]
                            if picked:
                                entry[col['key']] = picked
                        else:
                            text = data.get(cell, '').strip()[:MAX_TEXT]
                            if text:
                                entry[col['key']] = text
                    if entry:
                        rows.append({'row': label, **entry})
                if rows:
                    answers[key] = rows
    return answers


def has_real_answers(definition, answers):
    """True when something besides the boxes filled from the patient record was answered."""
    prefilled_keys = {f['key'] for s in definition.get('sections', []) for f in s['fields'] if f.get('prefill')}
    return any(k not in prefilled_keys for k in answers)


def _cell_text(value):
    return ', '.join(value) if isinstance(value, list) else value


def summary(definition, answers):
    """Only what was answered, section by section, for reading and printing."""
    sections = []
    for section in definition.get('sections', []):
        items = []
        for f in section['fields']:
            value = answers.get(f['key'])
            if not value:
                continue
            kind = f['type']
            if kind == 'multi':
                parts = list(value.get('values', [])) + ([f'{f.get("other", "Others")}: {value["other"]}'] if value.get('other') else [])
                items.append({'label': f['label'], 'text': ', '.join(parts)})
            elif kind == 'yesno':
                items.append({'label': f['label'], 'text': ' - '.join(x for x in (value.get('value'), value.get('detail')) if x)})
            elif kind == 'grid':
                headers = [f.get('row_label') or ''] + [c.get('label') or c['key'].title() for c in f['cols']]
                rows = [[r['row']] + [_cell_text(r.get(c['key'], '')) for c in f['cols']] for r in value]
                items.append({'label': f['label'], 'grid': {'headers': headers, 'rows': rows}})
            else:
                items.append({'label': f['label'], 'text': value, 'long': kind == 'textarea'})
        if items:
            sections.append({'title': section['title'], 'items': items})
    return sections
