from django.core.management.base import BaseCommand
from django.db import transaction
import os

from ...ingest import ingest, load_bibtex

import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Loads bibtex data into the database"

    def add_arguments(self, parser):
        parser.add_argument('--file',
                            dest='file_name',
                            help='name of file you want to load into the db')

    def handle(self, *args, **options):
        file_name = options['file_name']
        if not os.path.exists(file_name):
            logger.error("File '{}' does not exist".format(file_name))
        else:
            entries = load_bibtex(file_name)
            logger.info("BibTeX entries processed")
            with transaction.atomic():
                ingest(entries)
            logger.info("BibTeX entries loaded into DB")