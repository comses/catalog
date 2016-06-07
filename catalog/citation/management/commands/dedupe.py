from django.core.management.base import BaseCommand
from django.db import transaction

from ...ingest import dedupe_publications_by_doi
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
        'fix': {
            'fix': fix
        }
    }

    def handle(self, *args, **options):
        table = options["table"]
        strategy = options["strategy"]
        with transaction.atomic():
            self.OPTIONS[table][strategy]()
        logger.info("Deduplication using strategy '{}' on table '{}' complete".format(strategy, table))