import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from exercises.models import ExerciseMain, ExerciseStepImage, Region, SubRegion


class Command(BaseCommand):
    help = 'Load the exercise library (regions, sub-regions, exercises, step images) from fixtures/library.json'

    def add_arguments(self, parser):
        parser.add_argument('--prune', action='store_true', help='Also delete library exercises (and their step images) that are not in the fixture. '
                            'Prescriptions keep the exercise name they were written with. Use it once when moving from an older library.')

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / 'fixtures' / 'library.json'
        data = json.loads(path.read_text(encoding='utf-8'))

        for r in data['regions']:
            Region.objects.update_or_create(id=r['id'], defaults={'region_name': r['region_name']})
        for s in data['subregions']:
            SubRegion.objects.update_or_create(id=s['id'], defaults={'region_fk_id': s['region_id'], 'sub_region_name': s['sub_region_name']})

        static_dirs = [Path(d) for d in getattr(settings, 'STATICFILES_DIRS', [])]
        missing_images = 0
        for e in data['exercises']:
            fields = {k: v for k, v in e.items() if k not in ('id', 'sub_region_id')}
            # an image path whose file didn't come across is dropped rather than shown broken
            url = fields.get('exercise_url') or ''
            if url and static_dirs and not any((d / url.removeprefix('/static/')).exists() for d in static_dirs):
                fields['exercise_url'] = ''
                missing_images += 1
            ExerciseMain.objects.update_or_create(id=e['id'], defaults={**fields, 'sub_region_fk_id': e['sub_region_id']})

        steps = missing_steps = 0
        for s in data['step_images']:
            url = s.get('image_url') or ''
            if url and static_dirs and not any((d / url.removeprefix('/static/')).exists() for d in static_dirs):
                missing_steps += 1  # the picture file did not come across: skip the frame rather than show a broken image
                continue
            if ExerciseMain.objects.filter(pk=s['exercise_id']).exists():
                ExerciseStepImage.objects.update_or_create(
                    exercise_id=s['exercise_id'], order=s['order'],
                    defaults={'image_url': s['image_url'], 'label': s['label']})
                steps += 1
        if options['prune']:
            stale = ExerciseMain.objects.exclude(pk__in=[e['id'] for e in data['exercises']])
            removed = stale.count()
            stale.delete()
            SubRegion.objects.exclude(pk__in=[x['id'] for x in data['subregions']]).filter(exercises__isnull=True).delete()
            Region.objects.exclude(pk__in=[x['id'] for x in data['regions']]).filter(subregions__isnull=True).delete()
            self.stdout.write(f'Pruned {removed} exercises that are not in the fixture.')
        self.stdout.write(self.style.SUCCESS(
            f"{len(data['regions'])} regions, {len(data['subregions'])} sub-regions, {len(data['exercises'])} exercises, "
            f"{steps} step images ({missing_images} missing main images and {missing_steps} missing step images skipped); "
            f"{sum(1 for e in data['exercises'] if e.get('youtube_url'))} YouTube links, {sum(1 for e in data['exercises'] if e.get('hosted_video_url'))} hosted videos"))
