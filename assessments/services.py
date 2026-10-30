"""Reading helpers: what the patient's Assessments tab and the detail page show."""
from collections import OrderedDict

from .models import AssessmentResult, AssessmentSession, ClinicalRecord
from .scoring import change


def sparkline(points, width=90, height=24, pad=3):
    """SVG polyline coordinates for a tiny trend line ('' when there is nothing to draw)."""
    if len(points) < 2:
        return ''
    low, high = min(points), max(points)
    span = (high - low) or 1
    step = (width - 2 * pad) / (len(points) - 1)
    return ' '.join(f'{pad + i * step:.1f},{height - pad - (v - low) / span * (height - 2 * pad):.1f}' for i, v in enumerate(points))


def patient_summary(patient, visible=None):
    """Sessions (newest first), filled clinical forms and one progress row per scale: first, latest and the change between them. `visible` limits them
    to the viewer's disciplines (plus general ones): an occupational therapist's assessments are not shown to a physiotherapist, and the other way round."""
    sessions = AssessmentSession.objects.filter(patient=patient)
    records = ClinicalRecord.objects.filter(patient=patient)
    if visible is not None:
        sessions, records = sessions.filter(discipline__in=visible), records.filter(discipline__in=visible)
    sessions = list(sessions.prefetch_related('results'))
    results = (AssessmentResult.objects.filter(session__in=sessions, score__isnull=False)
               .select_related('session').order_by('session__assessed_on', 'session_id', 'id'))
    by_scale = OrderedDict()
    for r in results:
        by_scale.setdefault(r.scale_code, []).append(r)
    progress = []
    for code, rows in by_scale.items():
        first, latest = rows[0], rows[-1]
        text, tone = change(latest, first) if len(rows) > 1 else ('First reading', 'ok')
        since_last, since_tone = change(latest, rows[-2]) if len(rows) > 2 else ('', '')
        progress.append({'code': code, 'name': latest.scale_name, 'count': len(rows), 'first': first, 'latest': latest,
                         'change': text, 'tone': tone, 'since_last': since_last, 'since_last_tone': since_tone,
                         'spark': sparkline([float(x.score) for x in rows])})
    progress.sort(key=lambda p: p['latest'].session.assessed_on, reverse=True)
    return {'sessions': sessions, 'progress': progress, 'records': list(records)}
