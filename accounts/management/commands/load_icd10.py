import re

import simple_icd_10 as icd
from django.core.management.base import BaseCommand

from accounts.models import Icd10Code

CODE_RE = re.compile(r'^[A-Z]\d{2}(\.\d+)?$')  # skips chapters ("I") and blocks ("A00-A09")


class Command(BaseCommand):
    help = 'Load/refresh the WHO ICD-10 code list used by the diagnosis search'

    def handle(self, *args, **options):
        rows = [(c, icd.get_description(c)) for c in icd.get_all_codes(with_dots=True) if CODE_RE.match(c)]
        existing = set(Icd10Code.objects.values_list('code', flat=True))
        new = [Icd10Code(code=c, title=t[:300]) for c, t in rows if c not in existing]
        Icd10Code.objects.bulk_create(new, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f'{len(new)} codes added ({len(rows)} in list)'))
