from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

from ... import dedupe, models


class Command(BaseCommand):
    help = "Merge and split database records according from a file"

    def add_arguments(self, parser):
        parser.add_argument('--file',
                            required=True,
                            help='.merge, .split, or .delete data file specifying how to clean data')
        parser.add_argument('--creator',
                            required=True,
                            help="username of a User to be recorded in the audit log when executing these commands")

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
        path = options['file']
        creator = User.objects.get(username=options['creator'])
        (model, action) = self.parse_path(path)
        processor = dedupe.DataProcessor(model, creator)
        processor.execute(action, path)
