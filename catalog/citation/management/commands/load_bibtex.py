from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from ... import bibtex as bibtex_api

import logging
import pathlib
import pickle

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads bibtex data into the database"

    def add_arguments(self, parser):
        parser.add_argument('-f', '--filename',
                            help='BibTeX file to load into the DB')
        parser.add_argument('-d', '--directory',
                            help='Directory of data files to load into the DB')
        parser.add_argument('-u', '--username',
                            required=True,
                            help='username to load the data into the db as')

    def handle(self, *args, **options):
        filename = options.get('filename')
        directory = options.get('directory')
        if not any([filename, directory]):
            raise ValueError("no input filename or directory given")
        username = options['username']
        user = User.objects.get(username=username)
        file_paths = []
        if directory:
            file_paths = [p for p in pathlib.Path(directory).iterdir() if p.is_file()]
        elif filename:
            file_paths = [pathlib.path(filename)]
        for p in file_paths:
            self.process_filepath(p, user)

    def process_filepath(self, path, user):
        output = path.parent.joinpath("invalid-{0}.p".format(path.name))
        if output.exists():
            logger.debug("deleting old output file %s", output)
            output.unlink()
        errors_and_duplicates = bibtex_api.process_entries(path.absolute().as_posix(), user)
        with output.open('wb') as f:
            logger.debug("Pickling duplicate errors to %s", output)
            pickle.dump(errors_and_duplicates, f)
        logger.debug("Done loading")
