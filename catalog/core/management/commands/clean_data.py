from django.core.management.base import BaseCommand
from django.db import transaction
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


    def handle(self, *args, **options):
        path = options['path']
        processor = dedupe.DataProcessor(path)
        processor.execute()
