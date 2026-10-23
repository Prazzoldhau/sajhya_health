"""Convert the MySQL database and all its tables to utf8mb4, so Nepali text and emoji can be stored.

    python manage.py convert_db_utf8mb4

cPanel creates databases with the server default (often latin1); loading Nepali exercise descriptions then fails with MySQL error 1366.
Safe to run again: tables that are already utf8mb4 are left alone.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

CHARSET, COLLATION = 'utf8mb4', 'utf8mb4_unicode_ci'


class Command(BaseCommand):
    help = 'Convert the database and every table to utf8mb4 (MySQL only).'

    def handle(self, *args, **options):
        if connection.vendor != 'mysql':
            raise CommandError('This only applies to a MySQL database.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE()')
            name = cursor.fetchone()[0]
            cursor.execute(f'ALTER DATABASE `{name}` CHARACTER SET {CHARSET} COLLATE {COLLATION}')
            cursor.execute('SELECT table_name, table_collation FROM information_schema.tables WHERE table_schema = %s AND table_type = %s', [name, 'BASE TABLE'])
            tables = cursor.fetchall()
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
            done = 0
            for table, collation in tables:
                if collation and collation.startswith(CHARSET):
                    continue
                cursor.execute(f'ALTER TABLE `{table}` CONVERT TO CHARACTER SET {CHARSET} COLLATE {COLLATION}')
                done += 1
            cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        self.stdout.write(self.style.SUCCESS(f'{name}: converted {done} of {len(tables)} tables to {CHARSET}.'))
