import logging

from django.core.management.base import BaseCommand

from catalog.core.visualization.data_access import visualization_cache

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Build pandas dataframe cache of primary data'''

    def handle(self, *args, **options):
        visualization_cache.get_or_create_many()