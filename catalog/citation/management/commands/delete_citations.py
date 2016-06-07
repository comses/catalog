from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connection

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "delete all records in every citation table"

    def handle(self, *args, **options):
        models = apps.get_app_config('citation').get_models()
        cursor = connection.cursor()
        for model in models:
            cursor.execute('TRUNCATE TABLE "{0}" CASCADE'.format(model._meta.db_table))
            if model._meta.db_table not in ["citation_containerraw", "citation_publicationraw"]:
                cursor.execute('SELECT setval(\'{0}\', 1, FALSE)'.format(model._meta.db_table + "_id_seq"))
        logger.info("All citation info truncated")