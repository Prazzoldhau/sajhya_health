import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assessments.models import AssessmentForm, AssessmentScale, FormScale, ScaleItem, ScoreBand

SCALE_FIELDS = ('name', 'abbreviation', 'category', 'description', 'instructions', 'scoring', 'unit', 'higher_is_better', 'mcid', 'reference')


class Command(BaseCommand):
    help = ('Load assessment scales and forms from a JSON file (default: assessments/fixtures/scales.json). '
            'Safe to re-run: scales that already exist are left alone (so edits made in the admin survive) unless --update is given, '
            'which replaces their questions and bands with the ones in the file. Recorded results are never touched.')

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', help='A JSON file in the same format (see docs/ASSESSMENTS.md)')
        parser.add_argument('--update', action='store_true', help='Overwrite scales that already exist with the version in the file')

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options['path']) if options.get('path') else Path(__file__).resolve().parents[2] / 'fixtures' / 'scales.json'
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'Cannot read {path}: {exc}')

        for s in data.get('scales', []):
            scale, created = AssessmentScale.objects.get_or_create(code=s['code'], defaults={k: s[k] for k in SCALE_FIELDS if k in s})
            if not created and not options['update']:
                continue
            if not created:
                changed = False
                for k in SCALE_FIELDS:
                    if k in s and getattr(scale, k) != s[k]:
                        setattr(scale, k, s[k])
                        changed = True
                if changed:
                    scale.save()
            scale.items.all().delete()
            ScaleItem.objects.bulk_create([ScaleItem(scale=scale, **{k: v for k, v in item.items() if k != 'scale'}) for item in s.get('items', [])])
            scale.bands.all().delete()
            ScoreBand.objects.bulk_create([ScoreBand(scale=scale, **b) for b in s.get('bands', [])])

        for f in data.get('forms', []):
            form, created = AssessmentForm.objects.get_or_create(name=f['name'], defaults={'category': f.get('category', 'other'), 'description': f.get('description', '')})
            if not created and not options['update']:
                continue
            form.formscale_set.all().delete()
            for order, code in enumerate(f.get('scales', []), 1):
                scale = AssessmentScale.objects.filter(code=code).first()
                if scale is None:
                    raise CommandError(f'Form "{f["name"]}" lists unknown scale "{code}".')
                FormScale.objects.create(form=form, scale=scale, order=order)
        if options['verbosity']:
            self.stdout.write(f'{AssessmentScale.objects.count()} scales, {AssessmentForm.objects.count()} forms')
