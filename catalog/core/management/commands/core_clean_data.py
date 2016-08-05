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

    def parse_path(self, path):
        filename, ext = os.path.splitext(os.path.basename(path))
        filename = filename.lower()
        if filename == 'platform':
            return (models.Platform, ext)
        elif filename == 'sponsor':
            return (models.Sponsor, ext)
        elif filename == 'model_documentation':
            return (models.ModelDocumentation, ext)
        else:
            raise ValueError("Unsupported filename '{0}': should be 'platform' or 'sponsor'".format(filename))

    def handle(self, *args, **options):
        path = options['path']
        (model, action) = self.parse_path(path)
        processor = dedupe.DataProcessor(model)
        processor.execute(action, path)
