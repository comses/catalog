"""
The Merger Strategy module contains ways construct merge groups
"""

from haystack.query import SearchQuerySet
from django.db.models import Q
from . import models, merger


def get_id(solr_id: str):
    return int(solr_id.split('.')[2])


def get_instances(model, sq: SearchQuerySet):
    ids = [get_id(r.id) for r in sq]
    instances = model.objects.filter(id__in=ids)
    return instances


def find_publication_duplicates_on_load(publication: models.Publication):
    queryset = models.Publication.objects \
        .filter((Q(isi=publication.isi) & ~Q(isi='')) |
                (Q(doi=publication.doi) & ~Q(doi='')) |
                (Q(date_published_text__iexact=publication.date_published_text) &
                 ~Q(date_published_text='') &
                 Q(title__iexact=publication.title) &
                 ~Q(title=''))) \
        .exclude(id=publication.id)
    return queryset


def publication_has_duplicates_on_load(publication: models.Publication):
    queryset = find_publication_duplicates_on_load(publication)
    return queryset.exists()


def publication_merge_group_on_load(publication: models.Publication):
    instances = find_publication_duplicates_on_load(publication)
    if instances:
        pmg = merger.PublicationMergeGroup(final=publication, others=set(instances))
        return pmg
    else:
        return None


def find_publication_duplicates_by_title(publication: models.Publication):
    sq = SearchQuerySet() \
        .filter(title__exact=publication.title) \
        .exclude(id='citation.publication.{}'.format(publication.id)) \
        .models(models.Publication)
    instances = get_instances(models.Publication, sq)

    if instances:
        pmg = merger.PublicationMergeGroup(final=publication, others=set(instances))
        return pmg
    else:
        return None


def find_author_duplicates_by_name(instance: models.Author):
    instances = models.Author.objects \
        .filter(family_name=instance.family_name,
                given_name=instance.given_name) \
        .exclude(id=instance.id)

    if instances:
        amg = merger.AuthorMergeGroup(final=instance, others=set(instances))
        return amg
    else:
        return None


def find_container_duplicates_by_name(instance: models.Container):
    instances = models.Container.objects \
        .filter(name=instance.name) \
        .exclude(id=instance.id)


def find_duplicates_in_chunk(q, find_duplicates):
    if q:
        for publication in q:
            dupes = find_duplicates(publication)
            if dupes:
                yield dupes


def find_all_duplicates(model, find_duplicates, chunk_size=500):
    """
    Find all the duplicates for a given model

    :param chunk_size: Number of records to retrieve from the database at once to search through
    :param find_duplicates: Way to identify duplicates given a model instance
    :return: a generator of model instances
    """
    min_id = 0
    q = model.objects.filter(id__gte=min_id).order_by('id')[:chunk_size]
    for publication_merge_group in find_duplicates_in_chunk(q, find_duplicates):
        yield publication_merge_group

    while bool(q):
        min_id += chunk_size
        q = model.objects.filter(id__gt=min_id).order_by('id')[:chunk_size]
        for publication_merge_group in find_duplicates_in_chunk(q, find_duplicates):
            yield publication_merge_group
