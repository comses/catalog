from django.core.management.base import BaseCommand
from django.db import transaction

from ...ingest import (dedupe_publications_by_doi,
                       dedupe_containers_by_issn,
                       dedupe_containers_by_name,
                       dedupe_authors_by_publication_and_name)
from ...crossref.common import fix_raw_authors, fix_raw_containers

import logging

logger = logging.getLogger(__name__)


def fix():
    #fix_raw_authors()
    fix_raw_containers()


class Command(BaseCommand):
    help = "Deduplicate records using a particular stategy"

    def add_arguments(self, parser):
        parser.add_argument('--table',
                            dest='table',
                            help='table whose records you want to deduplicate')
        parser.add_argument('--strategy',
                            dest='strategy',
                            help='method used to deduplicate records')

    OPTIONS = {
        'publication': {
            'doi': dedupe_publications_by_doi
        },
        'container': {
            'issn': dedupe_containers_by_issn,
            'name': dedupe_containers_by_name
        },
        'author': {
            'publication_and_name': dedupe_authors_by_publication_and_name
        }
    }

    def handle(self, *args, **options):
        table = options["table"]
        strategy = options["strategy"]
        with transaction.atomic():
            self.OPTIONS[table][strategy]()
        logger.info("Deduplication using strategy '{}' on table '{}' complete".format(strategy, table))