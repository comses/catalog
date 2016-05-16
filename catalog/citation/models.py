from django.db import models
from django.contrib.postgres.fields import JSONField
from . import publications as pub
from collections import defaultdict


class Container(models.Model):
    name = models.TextField(max_length=1000)
    type = models.TextField(max_length=1000)


class Publication(models.Model):
    year = models.IntegerField()
    title = models.TextField(max_length=1000, null=True)
    doi = models.TextField(max_length=1000, null=True)
    container = models.ForeignKey(Container, default=None, null=True)
    container_name = models.TextField(max_length=1000, null=True)
    container_type = models.TextField(max_length=1000, null=True)
    abstract = models.TextField(max_length=20000, blank=True, null=True)
    history = JSONField(null=True)

    @staticmethod
    def from_persistent_publication(publication: pub.PersistentPublication) -> "Publication":
        history = {}
        for field_name in ['year', 'title', 'doi', 'abstract']:
            for data_source in pub.DataSource:
                Publication.add_history(history, data_source,
                                        field_name, getattr(publication, field_name))

        return Publication(year=publication.year.value,
                           title=publication.title.value,
                           doi=publication.doi.value,
                           container_name=publication.container_name.value,
                           )

    @staticmethod
    def add_history(history, data_source: pub.DataSource, field_name, field: pub.Persistent):
        history[data_source][field_name] = \
            Publication.get_data_source(field.previous_values, data_source)

    @staticmethod
    def get_data_source(previous_values, data_source: pub.DataSource):
        return [value for (data_source_comp, value) in previous_values
                if data_source == data_source_comp]

class Authors(models.Model):
    publication = models.ForeignKey(Publication)
    family = models.TextField(max_length=300)
    given = models.TextField(max_length=300)
    history = JSONField()