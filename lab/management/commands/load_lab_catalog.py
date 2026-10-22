import json
from pathlib import Path

from django.core.management.base import BaseCommand

from lab.models import LabTest, LabTestPanel


class Command(BaseCommand):
    help = 'Load the lab test and panel catalogue from fixtures/catalog.json (safe to re-run; it updates by name)'

    def handle(self, *args, **options):
        data = json.loads((Path(__file__).resolve().parents[2] / 'fixtures' / 'catalog.json').read_text(encoding='utf-8'))
        for t in data['tests']:
            LabTest.objects.update_or_create(name=t['name'], defaults={k: v for k, v in t.items() if k != 'name'})
        for p in data['panels']:
            panel, _ = LabTestPanel.objects.update_or_create(
                name=p['name'], defaults={k: v for k, v in p.items() if k not in ('name', 'tests')})
            panel.tests.set(LabTest.objects.filter(name__in=p['tests']))
        self.stdout.write(self.style.SUCCESS(f"{len(data['tests'])} lab tests, {len(data['panels'])} panels"))
