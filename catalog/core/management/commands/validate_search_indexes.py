import logging

from django.core.management.base import BaseCommand, CommandError

from catalog.core.search_indexes import validate_search_indices

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Validate Elasticsearch aliases, counts, and basic queries'

    def handle(self, *args, **options):
        try:
            counts = validate_search_indices()
        except Exception as exc:
            logger.exception('failed to validate Elasticsearch indexes')
            raise CommandError(
                'failed to validate Elasticsearch indexes: {0}'.format(exc)) from exc
        summary = ', '.join(
            '{0}={1}'.format(alias, count)
            for alias, count in sorted(counts.items())
        )
        self.stdout.write(self.style.SUCCESS(
            'Elasticsearch index validation succeeded: {0}'.format(summary)))
