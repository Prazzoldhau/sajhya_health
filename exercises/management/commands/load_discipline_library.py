from django.core.management.base import BaseCommand

from exercises import discipline_library
from exercises.models import ExerciseMain, Region, SubRegion


class Command(BaseCommand):
    help = 'Add the starter activities for occupational therapy, speech therapy and behaviour therapy to their own exercise libraries (only what is missing; edits made in the admin are kept).'

    def handle(self, *args, **options):
        discipline_library.sync(Region, SubRegion, ExerciseMain)
        counts = {d: ExerciseMain.objects.filter(discipline=d).count() for d in ('physio', 'ot', 'speech', 'behaviour')}
        self.stdout.write(self.style.SUCCESS('Exercises by department: ' + ', '.join(f'{k} {v}' for k, v in counts.items())))
