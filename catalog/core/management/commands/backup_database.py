import json
import logging
import os

from django.core.management.base import BaseCommand, CommandError

from catalog.core.backups import BackupError, create_backup

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create and verify a PostgreSQL backup in the backups root; prints one JSON result'

    def add_arguments(self, parser):
        parser.add_argument('--wait', action='store_true',
                            help='wait for a running backup operation instead of failing')
        parser.add_argument('--scheduled', action='store_true',
                            help='mark the backup as taken by the nightly schedule')

    def handle(self, *args, **options):
        try:
            result = create_backup(
                wait=options['wait'],
                scheduled=options['scheduled'],
                revision=os.environ.get('CATALOG_BUNDLE_REVISION'),
                image=os.environ.get('CATALOG_IMAGE'),
            )
        except (BackupError, OSError) as exc:
            logger.error('backup failed: %s', exc)
            raise CommandError('backup failed: {0}'.format(exc)) from exc
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
