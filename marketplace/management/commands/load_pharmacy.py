import json
from pathlib import Path

from django.core.management.base import BaseCommand

from marketplace.models import PharmacyProduct


class Command(BaseCommand):
    help = 'Load the pharmacy catalogue from fixtures/pharmacy.json (safe to re-run; it updates by name + image)'

    def handle(self, *args, **options):
        data = json.loads((Path(__file__).resolve().parents[2] / 'fixtures' / 'pharmacy.json').read_text(encoding='utf-8'))
        for p in data:
            # name + image: the catalogue has two different products both called 'Pantoprazole'
            PharmacyProduct.objects.update_or_create(name=p['name'], image=p['image'], defaults={k: v for k, v in p.items() if k not in ('name', 'image')})
        self.stdout.write(self.style.SUCCESS(f'{len(data)} pharmacy products'))
