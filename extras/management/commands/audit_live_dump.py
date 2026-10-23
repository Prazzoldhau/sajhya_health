import json
import sys

from django.core.management.base import BaseCommand, CommandError

from extras import live_map


class Command(BaseCommand):
    help = ('Check that every table and column of a live-site export has a home in this project (see extras/live_map.py). '
            'Accepts a .sql dump or extras/live_schema.json; only the structure is read, no data is loaded or printed.')

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=None, help='dump.sql or live_schema.json (default: extras/live_schema.json)')
        parser.add_argument('--show-dropped', action='store_true', help='also list the columns that are deliberately not carried over')

    def handle(self, *args, **options):
        path = options['path']
        if path is None:
            from pathlib import Path
            path = Path(__file__).resolve().parents[2] / 'live_schema.json'
        try:
            schema = json.load(open(path, encoding='utf-8'))['tables'] if str(path).endswith('.json') else live_map.parse_sql_schema(path)
        except OSError as exc:
            raise CommandError(f'Cannot read {path}: {exc}')
        report = live_map.audit(schema)
        self.stdout.write(f"{report['tables']} live tables: {report['mapped_tables']} mapped, {report['internal']} Django-internal; {report['columns']} columns checked")
        if options['show_dropped']:
            for table, column, why in report['dropped']:
                self.stdout.write(f'  not carried over: {table}.{column} ({why})')
        problems = report['unmapped_tables'] + report['unmapped_columns'] + report['missing_models']
        if problems:
            for p in problems:
                self.stderr.write(f'UNMAPPED: {p}')
            self.stderr.write(f'{len(problems)} problem(s): add the model/field or a mapping in extras/live_map.py')
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS('Every live table and column has a home in this project.'))
