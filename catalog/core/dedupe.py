import logging
import ast

from . import models
from django.db import transaction

logger = logging.getLogger(__name__)


class DataProcessor(object):

    model_names = {
        models.Platform: 'platforms',
        models.Sponsor: 'sponsors',
        models.ModelDocumentation: 'model_documentation'
    }

    def __init__(self, model):
        self.model = model
        self.related_name = DataProcessor.model_names[model]

    def execute(self, action, path):
        with transaction.atomic():
            if action == '.merge':
                self.merge(path)
            elif action == '.split':
                self.split(path)
            elif action == '.delete':
                self.delete(path)
            else:
                raise ValueError("Invalid action extension {0}. Must be '.merge' or '.split'".format(action))

    def delete(self, path):
        with open(path, "r") as f:
            names = ast.literal_eval(f.read())
            self.model.objects.filter(name__in=names).delete()

    def split(self, path):
        with open(path, "r") as f:
            splits = ast.literal_eval(f.read())
            for name, new_names in splits:
                logger.debug("Splitting %s into %s", name, new_names)
                self.split_record(name=name, new_names=new_names)

    def merge(self, path):
        with open(path, "r") as f:
            merges = ast.literal_eval(f.read())
            for names, new_name in merges:
                self.merge_records(names=names, new_name=new_name)

    def split_record(self, name, new_names):
        """
        Takes a single value name and splits it into multiple values denoted by the new_names list.
        """
        with transaction.atomic():
            related_name = self.related_name
            record = self.model.objects.prefetch_related('publications').get(name=name)
            publications = record.publications.all()
            record.delete()
            new_records = [self.model.objects.get_or_create(name=new_name)[0] for new_name in new_names]
            for publication in publications:
                models.PublicationAuditLog.objects.create(publication=publication,
                                                          message='Splitting {0}'.format(related_name),
                                                          modified_data={'name': name, 'new_names': new_names})
                for new_record in new_records:
                    getattr(publication, related_name).add(new_record)

    def get_related_publications_with_name(self, names):
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
            publications = self.get_related_publications_with_name(names)
            self.log_changes(publications, 'Merging', {'names': names, 'new_name': new_name})
            canonical_record, created = self.model.objects.get_or_create(name=new_name)
            canonical_record.publications.add(*publications)
            records_to_merge.exclude(name=new_name).delete()
            return canonical_record
