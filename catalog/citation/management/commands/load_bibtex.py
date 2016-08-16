from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import User
import os

from ... import bibtex as bibtex_api
from ...crossref import doi_lookup as crossref_doi_api, author_year_lookup as crossref_author_year_api
from ...ingest import dedupe

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads bibtex data into the database"

    def add_arguments(self, parser):
        parser.add_argument('--file',
                            dest='file_name',
                            help='settings json file describing how you want to load into the db')
        parser.add_argument('--username',
                            dest='user_name',
                            help='username to load the data into the db as')

    def handle(self, *args, **options):
        file_name = options['file_name']
        if not os.path.exists(file_name):
            logger.error("Settings file '{}' does not exist".format(file_name))
        else:
            user_name = options['user_name']
            user = User.objects.get(username=user_name)
            settings = bibtex_api.Settings.from_file(file_name=file_name)
            bibtex_api.process_entries(settings, user)
            dedupe(settings, user)
            crossref_doi_api.augment_publications(user)
            dedupe(settings, user)
            crossref_author_year_api.augment_publications(user)
            dedupe(settings, user)
