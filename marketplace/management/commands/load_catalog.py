import json
from pathlib import Path

from django.core.management.base import BaseCommand

from marketplace.models import Category, Product


class Command(BaseCommand):
    help = 'Load the starter marketplace catalog (categories + products) from fixtures/catalog.json'

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / 'fixtures' / 'catalog.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        for c in data['categories']:
            Category.objects.update_or_create(id=c['id'], defaults={k: c[k] for k in ('name', 'icon', 'description')})
        for p in data['products']:
            Product.objects.update_or_create(id=p['id'], defaults={k: v for k, v in p.items() if k != 'id'})
        self.stdout.write(self.style.SUCCESS(f"{len(data['categories'])} categories, {len(data['products'])} products"))
