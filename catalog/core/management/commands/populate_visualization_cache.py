import logging

from django.core.cache import cache
from django.core.management.base import BaseCommand

from catalog.core.visualization.data_access import visualization_cache

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Build pandas dataframe cache of primary data'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear application caches before rebuilding visualization data.',
        )

    def handle(self, *args, **options):
        if options['clear']:
            cache.clear()
        visualization_cache.get_or_create_many()
