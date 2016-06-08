import logging
import ast

from . import models
from django.db import transaction

logger = logging.getLogger(__name__)


def import_split_file_line(str):
    return ast.literal_eval(str)


def import_merge_file_line(str):
    return ast.literal_eval(str)


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
            print("\tName: {}, New Names: {}".format(name, new_names))
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
    with transaction.atomic():
        record = table.objects.prefetch_related('publications').get(name=name)
        publications = record.publications.all()
        record.delete()

        new_records = [table.objects.get_or_create(name=new_name)[0]
                          for new_name in new_names]
        for new_record in new_records:
            for publication in publications:
                getattr(publication, related_name).add(new_record)

        for publication in publications:
            publication.save()


def merge_sponsors(names, new_name):
    with transaction.atomic():
        sponsors = models.Sponsor.objects.filter(name__in=names)
        publications = list(models.Publication.objects.filter(sponsors__name__in=names))
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