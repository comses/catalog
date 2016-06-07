from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from ...models import PublicationRaw
import os

from ...ingest import ingest, crossref_dois_lookup, crossref_year_author_lookup

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads crossref doi data into the database"

    def add_arguments(self, parser):
        parser.add_argument('--api',
                            dest='api',
                            default='crossref_doi_api',
                            help="API to use find publications")
        parser.add_argument('--n_of_entries',
                            type=int,
                            dest='n_of_entries',
                            default=10,
                            help='maximum number of entries to load into the DB')

    def handle(self, *args, **options):
        if options['api'] == 'crossref_doi_api':
            with transaction.atomic():
                crossref_dois_lookup(options['n_of_entries'])
            logger.info("CrossRef DOI entries loaded into DB")
        elif options['api'] == 'crossref_search_api':
            with transaction.atomic():
                crossref_year_author_lookup(options['n_of_entries'])
            logger.info("CrossRef search entries loaded into DB")