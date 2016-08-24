from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from ... import bibtex as bibtex_api
from ...crossref import doi_lookup as crossref_doi_api, author_year_lookup as crossref_author_year_api
from ...ingest import dedupe

import logging
import os

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads bibtex data into the database"

    def add_arguments(self, parser):
        parser.add_argument('--filename',
                            required=True,
                            help='settings json file describing how you want to load into the db')
        parser.add_argument('--username',
                            required=True,
                            help='username to load the data into the db as')

    def handle(self, *args, **options):
        filename = options['filename']
        if not os.path.exists(filename):
            logger.error("Settings file %s does not exist", filename)
        else:
            username = options['username']
            user = User.objects.get(username=username)
            settings = bibtex_api.Settings.from_file(file_name=filename)
            bibtex_api.process_entries(settings, user)
            dedupe(settings, user)
            crossref_doi_api.augment_publications(user)
            dedupe(settings, user)
            crossref_author_year_api.augment_publications(user)
            dedupe(settings, user)
