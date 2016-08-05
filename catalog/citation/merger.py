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
        print("\tYear: {}, Title: {}, DOI: {}".format(publication.date_published_text, publication.title, publication.doi))
    print("\n")


def merge_publications(mergeset: MergeSet,
                       audit_command: models.AuditCommand,
                       final_publications: Optional[List[models.Publication]]=None) -> None:

    if not final_publications or len(mergeset) != len(final_publications):
        final_publication_ids = [mergeitem.pop() for mergeitem in mergeset]
        final_publications = models.Publication.objects.filter(id__in=final_publication_ids).all()

    for (ids, final_publication) in zip(mergeset, final_publications):
        assert len(ids) >= 0

        publications = models.Publication.objects.filter(id__in=ids).all()

        models.Raw.objects\
            .filter(publication_id__in=ids)\
            .log_update(audit_command=audit_command, publication_id=final_publication.id)

        authors = models.Author.objects.filter(publications=final_publication).all()
        models.PublicationAuthors.objects\
            .filter(publication_id__in=ids, author__in=authors)\
            .log_delete(audit_command)
        models.PublicationAuthors.objects\
            .filter(publication_id__in=ids)\
            .log_update(audit_command=audit_command, publication_id=final_publication.id)

        citations = models.Publication.objects.filter(Q(citations=final_publication)).all()
        references = models.Publication.objects.filter(Q(referenced_by=final_publication)).all()
        models.PublicationCitations.objects\
            .filter(publication_id__in=ids, citation__in=citations | references)\
            .log_delete(audit_command)
        models.PublicationCitations.objects\
            .filter(publication_id__in=ids)\
            .log_update(audit_command=audit_command, publication_id=final_publication.id)

        # TODO: remove log_save and track updates here for updating later, create log_update method
        for publication in publications:
            for field in ['date_published_text', 'title', 'doi', 'abstract']:
                if not getattr(final_publication, field):
                    setattr(final_publication, field, getattr(publication, field))

        final_publication.log_save(audit_command)
        publications.log_delete(audit_command)
        display_merge_publications(publications)


def merge_containers(mergeset: MergeSet, audit_command: models.AuditCommand) -> None:
    final_container_ids = [mergeitem.pop() for mergeitem in mergeset]
    final_containers = models.Container.objects.filter(id__in=final_container_ids).all()

    cursor = connection.cursor()
    for (ids, final_container) in zip(mergeset, final_containers):

        containers = models.Container.objects.filter(id__in=ids).all()

        final_container_aliases = models.ContainerAlias.objects.filter(container=final_container)
        container_aliases_to_delete = models.ContainerAlias.objects.filter(container_id__in=ids)
        raw_update = \
            """
            update citation_raw as raw set container_alias_id = container_alias_map.target_id
            from (
                select final.id as target_id, deleted.id as source_id
                from (
                    select id, name
                    from citation_containeralias
                    where id = any(%s)) as final
                inner join (
                    select id, name
                    from citation_containeralias
                    where id = any(%s)) as deleted on deleted.name = final.name
            ) as container_alias_map
            where container_alias_map.source_id = raw.container_alias_id"""
        cursor.execute(raw_update,
                       [[final_alias.id for final_alias in final_container_aliases],
                        [alias_to_delete.id for alias_to_delete in container_aliases_to_delete]])
        models.ContainerAlias.objects\
            .filter(container_id__in=ids,
                    name__in=[final_container_alias.name for final_container_alias in final_container_aliases])\
            .log_delete(audit_command)
        models.ContainerAlias.objects.filter(container_id__in=ids).log_update(audit_command, container_id=final_container.id)

        models.Publication.objects.filter(container__in=containers).log_update(audit_command, container_id=final_container.id)

        for container in containers:
            for field in ['issn']:
                if not getattr(final_container, field):
                    setattr(final_container, field, getattr(container, field))

        final_container.log_save(audit_command)
        containers.log_delete(audit_command)


def merge_authors(mergeset: MergeSet, audit_command: models.AuditCommand) -> None:
    # TODO: repoint raw values if author_alias is deleted
    final_ids = [mergeitem.pop() for mergeitem in mergeset]
    final_authors = models.Author.objects.filter(id__in=final_ids).all()

    for (ids, final_author) in zip(mergeset, final_authors):
        authors = models.Author.objects.filter(id__in=ids).all()

        final_author_aliases = models.AuthorAlias.objects.filter(author=final_author)

        author_aliases_to_delete = models.AuthorAlias.objects\
            .filter(author_id__in=ids,
                    given_name__in=[final_author_alias.given_name for final_author_alias in final_author_aliases],
                    family_name__in=[final_author_alias.family_name for final_author_alias in final_author_aliases])
        for author_alias_to_delete in author_aliases_to_delete:
            raws = author_alias_to_delete.raw.all()
            final_author_alias=final_author_aliases.get(given_name=author_alias_to_delete.given_name,
                                                        family_name=author_alias_to_delete.family_name)
            models.RawAuthors.objects\
                .filter(author_alias=author_alias_to_delete, raw__in=raws)\
                .update(author_alias=final_author_alias)
        author_aliases_to_delete.log_delete(audit_command)
        models.AuthorAlias.objects.filter(author_id__in=ids).update(author=final_author)

        publications = models.Publication.objects.filter(creators=final_author)
        models.PublicationAuthors.objects\
            .filter(publication__in=publications, author__in=authors)\
            .log_delete(audit_command)
        models.PublicationAuthors.objects\
            .filter(author__in=authors)\
            .log_update(audit_command, author_id=final_author.id)

        for author in authors:
            for field in ['orcid']:
                if not getattr(final_author, field):
                    setattr(final_author, field, getattr(author, field))

        final_author.log_save(audit_command)
        authors.log_delete(audit_command)