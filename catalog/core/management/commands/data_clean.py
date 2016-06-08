from django.core.management.base import BaseCommand
from django.db import transaction
import os

from ... import models
from ...data_clean import process_merge_file, process_split_file


class Command(BaseCommand):
    help = "Merge and split database records according from a file"

    def add_arguments(self, parser):
        parser.add_argument('--file',
                            dest='path',
                            default=None,
                            help='file to clean data with')
        parser.add_argument('--table',
                            dest='table',
                            help='table to clean data with. Use only with the --delete flag')
        parser.add_argument('--delete',
                            nargs="*",
                            dest="deleted_names",
                            help="records to delete")

    @staticmethod
    def delete_records(table, names):
        for name in names:
            table.objects.filter(name__iexact=name).delete()

    @staticmethod
    def is_mergefile(ext: str):
        return ext == ".merge"

    @staticmethod
    def is_splitfile(ext: str):
        return ext == ".split"

    def handle(self, *args, **options):
        path = options['path']
        if path is not None:
            table, ext = os.path.splitext(os.path.basename(path))
        else:
            table = options['table'].lower()
            ext = None
        deleted_names = options['deleted_names']

        if table == 'platform':
            table = models.Platform
        elif table == 'sponsor':
            table = models.Sponsor
        else:
            raise ValueError("Table '{}' must can be only be one of two values: 'platform' and 'sponsor'")

        if deleted_names:
            if path is not None:
                raise ValueError("If file is set then the delete option is not allowed")
            else:
                self.delete_records(table, deleted_names)
        else:
            if path is None or not os.path.exists(path):
                print("File {} does not exist".format(path))

            if self.is_mergefile(ext):
                with transaction.atomic():
                    process_merge_file(path, table)
            elif self.is_splitfile(ext):
                with transaction.atomic():
                    process_split_file(path, table)
            else:
                raise ValueError("Extension {} not valid. Must be either '.merge' or '.split'" \
                                 .format(os.path.splitext(path)[1]))
