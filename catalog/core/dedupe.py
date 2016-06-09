import logging
import ast
import os

from . import models
from django.db import transaction

logger = logging.getLogger(__name__)


def import_split_file_line(str):
    return ast.literal_eval(str)


def import_merge_file_line(str):
    return ast.literal_eval(str)


class DataProcessor(object):

    def __init__(self, path):
        self.table, self.ext = os.path.splitext(os.path.basename(path))
        self.table = self.table.lower()
        if self.table == 'platform':
            self.model = models.Platform
            self.related_name = 'platforms'
        elif self.table == 'sponsor':
            self.model = models.Sponsor
            self.related_name = 'sponsors'
        else:
            raise ValueError("Unsupported table '{0}': must be 'platform' or 'sponsor'".format(self.table))

    def is_mergefile(self):
        return self.ext == '.merge'

    def is_splitfile(self):
        return self.ext == '.split'

    def execute(self):
        if self.is_mergefile(self.ext):
            with transaction.atomic():
                self.merge()
        elif self.is_splitfile(self.ext):
            with transaction.atomic():
                self.split()
        else:
            raise ValueError("Extension {0} not valid. Must be either '.merge' or '.split'".format(self.ext))

    def split(self):
        path = self.path
        with open(path, "r") as f:
            splits = ast.literal_eval(f.read())
            print("Splitting")
            for split in splits:
                name, new_names = split
                logger.debug("Name: %s, New Names: %s", name, new_names)
                # print("\tName: {}, New Names: {}".format(name, new_names))
                self.split_record(name=name, new_names=new_names)

    def merge(self):
        with open(self.path, "r") as f:
            merges = ast.literal_eval(f.read())
            for names, new_name in merges:
                self.merge_records(names=names, new_name=new_name)

    def split_record(self, name, new_names):
        """
        Takes a single value name and splits it into multiple values denoted by the new_names list.
        """
        related_name = self.related_name
        with transaction.atomic():
            record = self.model.objects.prefetch_related('publications').get(name=name)
            publications = record.publications.all()
            record.delete()
            new_records = [self.model.objects.get_or_create(name=new_name)[0] for new_name in new_names]
            for new_record in new_records:
                for publication in publications:
                    getattr(publication, related_name).add(new_record)

    def get_related_publications(self, names):
        criteria = {'{0}__name__in'.format(self.related_name): names}
        return list(models.Publication.objects.filter(**criteria))

    def log_changes(self, publications, action, modified_data):
        message = '{0} {1}'.format(action, self.related_name)
        for p in publications:
            models.PublicationAuditLog.objects.create(publication=p, message=message, modified_data=modified_data)


    def merge_records(self, names, new_name):
        with transaction.atomic():
            records_to_merge = self.model.objects.filter(name__in=names)
# log the deleted records to merge and the record that will be replacing them
            publications = self.get_related_publications(names)
            self.log_changes(publications, 'Merging', { 'names': names, 'new_name': new_name })
            canonical_record, created = self.model.objects.get_or_create(name=new_name)
            canonical_record.publications.add(*publications)
            records_to_merge.exclude(name=new_name).delete()
            return canonical_record


def process_split_file(path, table):
    if table == models.Platform:
        related_name = "platforms"
    elif table == models.Sponsor:
        related_name = "sponsors"
    else:
        raise ValueError("Table argument {} invalid. Must be one of Platform or Sponsor".format(table))
    with open(path, "r") as f:
        splits = import_split_file_line(f.read())
        print("Splitting")
        for split in splits:
            name, new_names = split
            logger.debug("Name: %s, New Names: %s", name, new_names)
            # print("\tName: {}, New Names: {}".format(name, new_names))
            split_record(name=name, new_names=new_names, table=table, related_name=related_name)


def process_merge_file(path, table):
    if table == models.Platform:
        merge_records = merge_platforms
    elif table == models.Sponsor:
        merge_records = merge_sponsors
    else:
        raise ValueError("Table argument {} invalid. Must be one of Platform or Sponsor".format(table))
    with open(path, "r") as f:
        merges = import_merge_file_line(f.read())
        for merge in merges:
            names, new_name = merge
            merge_records(names=names, new_name=new_name)


def split_record(name, new_names, table, related_name):
    """
    Takes a single value name and splits it into multiple values denoted by the new_names list.
    """
    with transaction.atomic():
        record = table.objects.prefetch_related('publications').get(name=name)
        publications = record.publications.all()
        record.delete()
        new_records = [table.objects.get_or_create(name=new_name)[0] for new_name in new_names]
        for new_record in new_records:
            for publication in publications:
                getattr(publication, related_name).add(new_record)

#        for publication in publications:
#            publication.save()


def merge_sponsors(names, new_name):
    with transaction.atomic():
        sponsors = models.Sponsor.objects.filter(name__in=names)
        publications = list(models.Publication.objects.filter(sponsors__name__in=names))
# log the deleted sponsors and the sponsor replacing them
        for p in publications:
            models.PublicationAuditLog.objects.create(publication=p,
                                                      message='Merging sponsors',
                                                      modified_data={
                                                          'new_name': new_name,
                                                          'merged_names': names
                                                      })

        sponsors.delete()


        new_sponsor, created = models.Sponsor.objects.get_or_create(name=new_name)
        new_sponsor.publications.add(*publications)

    return new_sponsor


def merge_platforms(names, new_name):
    with transaction.atomic():
        platforms = models.Platform.objects.filter(name__in=names)
        publications = list(models.Publication.objects.filter(platforms__name__in=names))
        platforms.delete()

        new_platform, created = models.Platform.objects.get_or_create(name=new_name)
        new_platform.publications.add(*publications)

    return new_platform
