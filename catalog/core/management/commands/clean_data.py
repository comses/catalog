from django.core.management.base import BaseCommand
import os

from ... import models
from catalog.core import dedupe


class Command(BaseCommand):
    help = "Merge and split database records according from a file"

    def add_arguments(self, parser):
        parser.add_argument('--file',
                            dest='path',
                            help='file to clean data with')
        """ FIXME: move to dedicated management command
        parser.add_argument('--table',
                            dest='table',
                            help='table to clean data with. Use only with the --delete flag')
        parser.add_argument('--delete',
                            nargs="*",
                            dest="deleted_names",
                            help="records to delete")
        """

    @staticmethod
    def delete_records(table, names):
        for name in names:
            table.objects.filter(name__iexact=name).delete()

    def parse_path(self, path):
        filename, ext = os.path.splitext(os.path.basename(path))
        filename = filename.lower()
        if filename == 'platform':
            return (models.Platform, ext)
        elif filename == 'sponsor':
            return (models.Sponsor, ext)
        else:
            raise ValueError("Unsupported filename '{0}': should be 'platform' or 'sponsor'".format(filename))

    def handle(self, *args, **options):
        path = options['path']
        (model, action) = self.parse_path(path)
        processor = dedupe.DataProcessor(model)
        processor.execute(action, path)
