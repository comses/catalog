from . import models, util
from django.db import connection, transaction
from django.db.models import QuerySet, Q, Count
from typing import List, Optional
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

    def __len__(self):
        return len(self._groups)


class TraceContext:
    def __init__(self, user, action):
        self.user = user
        self.action = action
        self.payload = []

    def trace(self, table, payload, source):
        self.payload.append({'table': table, 'payload': payload, 'source': source})

    def save(self):
        models.AuditLog.objects.create(creator=self.user, action=self.action, message='', payload=self.payload)


def fix_raw_authors():
    with transaction.atomic():
        raw_authors = models.RawAuthor.objects.filter(raw__key__in=["CROSSREF_DOI_SUCCESS"])
        author_aliases = list(models.AuthorAlias.objects.filter(raw_authors__in=raw_authors)) # type: List[models.AuthorAlias)
        authors = list(models.Author.objects.filter(author_aliases__in=author_aliases)) # type: List[models.Author)

        for raw_author in raw_authors:
            print(raw_author)
            author = models.Author.objects.create(orcid=raw_author.orcid, type=raw_author.type)
            author_alias = models.AuthorAlias.objects.create(name=raw_author.name, author=author)

            raw_author.author_alias = author_alias
            raw_author.save()

        for author_alias in author_aliases:
            print(author_alias)
            if author_alias.raw_authors.count() == 0:
                author_alias.delete()

        for author in authors:
            print(author)
            if author.author_aliases.count() == 0:
                author.delete()


# def fix_citations():
#     with transaction.atomic():
#         raw_publications = models.PublicationRaw.objects.annotate(cite_count=Count('citations')).filter(cite_count__gt=0).select_related('raw__publication')
#
#         for raw_publication in raw_publications:
#             publication = raw_publication.raw.publication
#             print("Title: {}".format(raw_publication.title))
#             for citation in raw_publication.citations.all():
#                 publication_to_join = citation.raw.publication
#                 publication.citations.add(publication_to_join)


def create_author_mergeset_by_orcid() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(id) AS ids
        FROM citation_author GROUP BY orcid HAVING count(*) > 1;"""
    )


def create_author_mergeset_by_name() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(DISTINCT author_id) AS ids
        FROM citation_authoralias
        WHERE author_id NOT IN (
          SELECT author_id
          FROM citation_publication_authors
        )
        GROUP BY "name"
        HAVING count(*) > 1;""")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_container_mergeset_by_issn() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(id) AS ids
        FROM citation_container GROUP BY issn HAVING count(*) > 1;""")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_container_mergeset_by_name() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(container_id) AS ids
        FROM citation_containeralias GROUP BY name HAVING count(*) > 1;""")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_publication_mergeset_by_doi() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT array_agg(id) AS ids FROM citation_publication WHERE doi <> '' GROUP BY doi HAVING count(*) > 1")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_publication_mergeset_by_titles() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT array_agg(id) AS ids FROM citation_publication WHERE title <> '' GROUP BY lower(title) HAVING count(*) > 1")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def display_merge_publications(publications):
    print("Merged")
    for publication in publications:
        print("\tYear: {}, Title: {}, DOI: {}".format(publication.year, publication.title, publication.doi))
    print("\n")


def merge_publications(mergeset: MergeSet, final_publications: Optional[List[models.Publication]]=None) -> None:
    if not final_publications or len(mergeset) != len(final_publications):
        final_publication_ids = [mergeitem.pop() for mergeitem in mergeset]
        final_publications = models.Publication.objects.filter(id__in=final_publication_ids).all()

    for (ids, final_id) in zip(mergeset, final_publications):
        assert len(ids) >= 0
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


def merge_containers(mergeset: MergeSet) -> None:
    for ids in mergeset:
        containers_to_merge = models.Container.objects.filter(id__in=ids)
        canonical_container = containers_to_merge[0]
        containers_to_merge = containers_to_merge[1:]

        canonical_container_names = [container_alias.name for container_alias
                                     in canonical_container.container_aliases.all()]
        models.Publication.objects \
            .filter(container__in=containers_to_merge) \
            .update(container=canonical_container)
        # Delete Container Aliases with the same name as any of the Container Aliases
        # part of the canonical container
        models.ContainerAlias.objects \
            .filter(container__in=containers_to_merge, name__in=canonical_container_names) \
            .delete()
        models.ContainerAlias.objects \
            .filter(container__in=containers_to_merge) \
            .update(container=canonical_container)

        containers_to_merge.delete()


def merge_authors(mergeset: MergeSet) -> None:
    for ids in mergeset:
        authors_to_merge = models.Author.objects.filter(id__in=ids)
        canonical_author = authors_to_merge[0]
        authors_to_merge = authors_to_merge[1:]

        canonical_author_names = [author_alias.name for author_alias
                                  in canonical_author.author_aliases.all()]
        models.Publication.authors.filter(publications__authors__in=authors_to_merge).delete()
        models.Publication.authors.add(canonical_author)
        # Delete Author Aliases with the same name as any of the Author Aliases
        # part of the canonical author
        models.AuthorAlias.objects \
            .filter(author__in=authors_to_merge, name__in=canonical_author_names) \
            .delete()
        models.AuthorAlias.objects.filter(author__in=authors_to_merge).update(author=canonical_author)

        authors_to_merge.delete()


# def first_author_alias(publication: models.Publication, raw_author: models.RawAuthor):
#     """Get a unique author alias"""
#     author_aliases = models.AuthorAlias.objects.filter(Q(name__exact=raw_author.name))
#     if len(author_aliases) == 1:
#         author_alias = author_aliases[0]
#         return author_alias
#     elif len(author_aliases) > 1:
#         authors_by_publication = author_aliases.filter(Q(publications=publication))
#         if len(authors_by_publication) == 1:
#             author_alias = author_aliases[0]
#             return author_alias
#     return None


# def create_or_get_author(publication: models.Publication, raw_author: models.RawAuthor):
#     author_alias = first_author_alias(publication, raw_author)
#     if author_alias is None:
#         author = models.Author.objects.create(type=raw_author.type)
#         models.AuthorAlias.objects.create(name=raw_author.name, author=author)
#     else:
#         author = author_alias.author
#     publication.authors.add(author)
#     return author
#
#
# def create_or_get_container(publication: models.Publication, raw_container: models.ContainerRaw):
#     containers = models.Container.objects.filter(Q(containeralias__name__iexact=raw_container.name) |
#                                                  Q(issn__exact=raw_container.issn),
#                                                  ~Q(containeralias__name__exact=''),
#                                                  ~Q(issn__exact=''))
#     if len(containers) == 1:
#         container = containers[0]
#     else:
#         container = models.Container.objects.create(issn=raw_container.issn)
#         models.ContainerAlias.objects.create(name=raw_container.name, container=container)
#     publication.container = container
#     publication.save()
#
#     return container
