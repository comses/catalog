from . import models, util
from django.db import connection, transaction
from django.db.models import QuerySet, Q, Count
from typing import List, Optional
from django.contrib.auth.models import User

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

    def __getitem__(self, item):
        return self._groups[item]

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


def create_author_mergeset_by_orcid() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(id) AS ids
        FROM citation_author WHERE orcid <> '' GROUP BY orcid HAVING count(*) > 1;"""
    )

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_author_mergeset_by_name() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(DISTINCT author_id) AS ids
        FROM citation_authoralias AS authoralias
        WHERE "given_name" <> '' AND "family_name" <> ''
        GROUP BY "given_name", "family_name"
        HAVING count(*) > 1;""")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_container_mergeset_by_issn() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(id) AS ids
        FROM citation_container WHERE issn <> '' GROUP BY issn HAVING count(*) > 1;""")

    groups = [row[0] for row in cursor.fetchall()]
    return MergeSet(groups)


def create_container_mergeset_by_name() -> MergeSet:
    cursor = connection.cursor()
    cursor.execute(
        """SELECT array_agg(container_id) AS ids
        FROM citation_containeralias WHERE name <> '' GROUP BY name HAVING count(*) > 1;""")

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
        print("\tYear: {}, Title: {}, DOI: {}".format(publication.date_published_text, publication.title,
                                                      publication.doi))
    print("\n")


def merge_publications(mergeset: MergeSet,
                       audit_command: models.AuditCommand,
                       final_publications: Optional[List[models.Publication]] = None) -> None:
    if not final_publications or len(mergeset) != len(final_publications):
        final_publication_ids = [mergeitem.pop() for mergeitem in mergeset]
        final_publications = models.Publication.objects.filter(id__in=final_publication_ids).all()

    for (ids, final_publication) in zip(mergeset, final_publications):
        assert len(ids) >= 0

        publications = models.Publication.objects.filter(id__in=ids).all()

        models.Raw.objects \
            .filter(publication_id__in=ids) \
            .log_update(audit_command=audit_command, publication_id=final_publication.id)

        authors = models.Author.objects.filter(publications=final_publication).all()
        models.PublicationAuthors.objects \
            .filter(publication_id__in=ids, author__in=authors) \
            .log_delete(audit_command)
        models.PublicationAuthors.objects \
            .filter(publication_id__in=ids) \
            .log_update(audit_command=audit_command, publication_id=final_publication.id)

        citations = models.Publication.objects.filter(Q(citations=final_publication)).all()
        references = models.Publication.objects.filter(Q(referenced_by=final_publication)).all()
        models.PublicationCitations.objects \
            .filter(publication_id__in=ids, citation__in=citations | references) \
            .log_delete(audit_command)
        models.PublicationCitations.objects \
            .filter(publication_id__in=ids) \
            .log_update(audit_command=audit_command, publication_id=final_publication.id)

        changes = {}
        for publication in publications:
            for field in ['date_published_text', 'title', 'doi', 'abstract']:
                if not getattr(final_publication, field):
                    changes[field] = getattr(publication, field)

        final_publication.log_update(audit_command, **changes)
        publications.log_delete(audit_command)
        display_merge_publications(publications)


def merge_containers(mergeset: MergeSet, audit_command: models.AuditCommand) -> None:
    final_container_ids = [mergeitem.pop() for mergeitem in mergeset]
    final_containers = models.Container.objects.filter(id__in=final_container_ids).all()

    for (ids, final_container) in zip(mergeset, final_containers):
        containers = models.Container.objects.filter(id__in=ids).all()

        for container in containers:
            if container.name != final_container.name:
                models.ContainerAlias.objects.log_get_or_create(
                    audit_command=audit_command,
                    container_id=final_container.id,
                    name=container.name)

            container_aliases = container.container_aliases.all()
            for container_alias in container_aliases:
                if models.ContainerAlias.objects.filter(
                        name=container_alias.name).first() is None:
                    container_alias.log_update(audit_command=audit_command, container_id=final_container.id)
                else:
                    container_alias.log_delete(audit_command=audit_command)

            changes = {}
            for field in ['issn']:
                if not getattr(final_container, field):
                    changes[field] = getattr(container, field)

            final_container.log_update(audit_command=audit_command, **changes)
            models.Raw.objects.filter(container=container).exclude(
                id__in=models.Raw.objects.filter(container=final_container)).log_update(
                audit_command=audit_command, container_id=final_container.id)
            container.log_delete(audit_command=audit_command)


def merge_authors(mergeset: MergeSet, audit_command: models.AuditCommand) -> None:
    final_ids = [mergeitem.pop() for mergeitem in mergeset]
    final_authors = models.Author.objects.filter(id__in=final_ids).all()

    for (ids, final_author) in zip(mergeset, final_authors):
        authors = models.Author.objects.filter(id__in=ids).all()

        for author in authors:
            if author.family_name != final_author.family_name or \
                            author.given_name != final_author.given_name:
                models.AuthorAlias.objects.log_get_or_create(
                    audit_command=audit_command,
                    author_id=final_author.id,
                    given_name=author.given_name,
                    family_name=author.family_name)

            author_aliases = author.author_aliases.all()
            for author_alias in author_aliases:
                if models.AuthorAlias.objects.filter(
                        given_name=author_alias.given_name,
                        family_name=author_alias.family_name).first() is None:
                    author_alias.log_update(audit_command=audit_command, author_id=final_author.id)
                else:
                    author_alias.log_delete(audit_command=audit_command)

            changes = {}
            for field in ['orcid', 'given_name', 'family_name']:
                if not getattr(final_author, field):
                    changes[field] = getattr(author, field)

            final_author.log_update(audit_command=audit_command, **changes)
            models.RawAuthors.objects.filter(author=author).exclude(
                raw__in=models.Raw.objects.filter(authors__in=[final_author])).log_update(
                audit_command=audit_command, author_id=final_author.id)
            author.log_delete(audit_command=audit_command)
