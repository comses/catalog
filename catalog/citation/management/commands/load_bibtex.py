from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from ... import bibtex as bibtex_api
from ...crossref import doi_lookup as crossref_doi_api, author_year_lookup as crossref_author_year_api

import logging
import os
import pickle

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads bibtex data into the database"

    def add_arguments(self, parser):
        parser.add_argument('-f', '--filename',
                            required=True,
                            help='BibTeX file to load into the DB')
        parser.add_argument('-o', '--output',
                            required=True,
                            help='File to log errors to')
        parser.add_argument('-u', '--username',
                            required=True,
                            help='username to load the data into the db as')

    @staticmethod
    def write_publication_errors(file_name, publication_errors):
        with open(file_name, "w") as f:
            pickle.dump(publication_errors, f, protocol=pickle.HIGHEST_PROTOCOL)

    def handle(self, *args, **options):
        filename = options['filename']
        output = options['output']
        username = options['username']
        user = User.objects.get(username=username)
        if not os.path.exists(filename):
            ValueError("File %s does not exist" % filename)
        if os.path.exists(output):
            os.unlink(output)
        errors_and_duplicates = bibtex_api.process_entries(filename, user)
        with open(output, 'wb') as f:
            print("Saving Duplicate Errors to File %s" % output)
            pickle.dump(errors_and_duplicates, f)
        print("Done loading")
