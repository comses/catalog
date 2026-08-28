import logging

from django.core.management.base import BaseCommand, CommandError

from catalog.core.search_indexes import bulk_index_public

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Rebuild the public Elasticsearch 8 search indices from '
        'PostgreSQL. Exits nonzero if any generation index fails to '
        'build, fails validation, or its alias swap fails; on failure '
        'the live read aliases are left untouched.'
    )

    def handle(self, *args, **options):
        try:
            bulk_index_public()
        except Exception as exc:
            # Log the full traceback; surface a CommandError so
            # ``manage.py`` (and any supervisor/cron wrapping it) exits
            # with a nonzero status.
            logger.exception('failed to rebuild the public search indices')
            raise CommandError(
                'failed to rebuild the public search indices: {0}'.format(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            'Public search indices rebuilt successfully.'))
