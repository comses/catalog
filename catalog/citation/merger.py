from . import models, util
from django.db import connection
from django.db.models import QuerySet, Q
from typing import Dict, Tuple, Iterable, List, MutableSequence, Union
from collections import defaultdict

import logging

logger = logging.getLogger(__name__)


class MergeSet:

    def __init__(self, groups=None):
        if groups is None:
            groups = []
        self._groups = groups

    def add(self, model_objects):
        assert len(model_objects) > 0
        self._groups.append([model_object.id for model_object in model_objects])

    def __iter__(self):
        return iter(self._groups)


def create_author_mergeset_by_name() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(DISTINCT author_id) AS ids
        FROM citation_authoralias GROUP BY \"name\" HAVING count(*) > 1;""")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_container_mergeset_by_issn() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(id) AS ids
        FROM citation_container GROUP BY issn HAVING count(*) > 1;""")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_publication_mergeset_by_doi() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute("SELECT array_agg(id) AS ids FROM citation_publication WHERE doi <> '' GROUP BY doi HAVING count(*) > 1")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_publication_mergeset_by_titles() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute("SELECT array_agg(id) AS ids FROM citation_publication WHERE title <> '' GROUP BY title HAVING count(*) > 1")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def display_merge_publications(publications):
    print("Merged")
    for publication in publications:
        print("\tYear: {}, Title: {}, DOI: {}".format(publication.year, publication.title, publication.doi))
    print("\n")


def merge_publications(mergeset: MergeSet) -> None:
    for ids in mergeset:
        assert len(ids) > 0
        models.Raw.objects.filter(publication_id__in=ids).update(publication_id=ids[0])
        authors = models.Author.objects.filter(publications__id__in=ids)

        publications = models.Publication.objects.filter(id__in=ids)
        assert len(publications) > 0
        publication = publications.filter(id=ids[0]).first()
        other_publications = publications.exclude(id=publication.id)

        publication.authors = authors
        for other_publication in other_publications:
            for field in ['year', 'title', 'doi', 'abstract']:
                if not getattr(publication, field):
                    setattr(publication, field, getattr(other_publication, field))
        publication.save()
        other_publications.delete()
        display_merge_publications(publications)


def first_author_alias(publication: models.Publication, raw_author: models.AuthorRaw):
    """Get a unique author alias"""
    author_aliases = models.AuthorAlias.objects.filter(Q(name__exact=raw_author.name))
    if len(author_aliases) == 1:
        author_alias = author_aliases[0]
        return author_alias
    elif len(author_aliases) > 1:
        authors_by_publication = author_aliases.filter(Q(publications=publication))
        if len(authors_by_publication) == 1:
            author_alias = author_aliases[0]
            return author_alias
    return None


def create_or_get_author(publication: models.Publication, raw_author: models.AuthorRaw):
    author_alias = first_author_alias(publication, raw_author)
    if author_alias is None:
        author = models.Author.objects.create(type=raw_author.type)
        models.AuthorAlias.objects.create(name=raw_author.name, author=author)
    else:
        author = author_alias.author
    publication.authors.add(author)
    return author


def create_or_get_container(publication: models.Publication, raw_container: models.ContainerRaw):
    containers = models.Container.objects.filter(Q(containeralias__name__iexact=raw_container.name) |
                                                 Q(issn__exact=raw_container.issn),
                                                 ~Q(containeralias__name__exact=''),
                                                 ~Q(issn__exact=''))
    if len(containers) == 1:
        container = containers[0]
    else:
        container = models.Container.objects.create(issn=raw_container.issn)
        models.ContainerAlias.objects.create(name=raw_container.name, container=container)
    publication.container = container
    publication.save()

    return container



