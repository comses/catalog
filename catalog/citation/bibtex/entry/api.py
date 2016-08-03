import re
import datetime

from typing import List, Optional
from .. import ref
from ... import models
from ... import util


def make_container(entry, audit_command) -> models.Container:
    container_str = entry.get("journal", "")
    container_type_str = entry.get("type", "")
    container_issn_str = entry.get("issn", "")
    container = models.Container.objects.log_create(audit_command=audit_command,
                                                    payload={'type': container_type_str,
                                                             'issn': container_issn_str})
    container_alias, created = models.ContainerAlias.objects.log_get_or_create(
        audit_command=audit_command,
        container=container,
        name=container_str,
        payload={'container': container, 'name': container_str})

    return container, container_alias


def make_author(publication: models.Publication, raw: models.Raw, author_str: str, audit_command) -> models.Author:
    cleaned_author_str = util.last_name_and_initials(util.normalize_name(author_str))
    author = models.Author.objects.log_create(
        audit_command=audit_command,
        payload= {'type': models.Author.INDIVIDUAL})
    author_alias, created = models.AuthorAlias.objects.log_get_or_create(
        audit_command=audit_command,
        author=author,
        name=cleaned_author_str,
        payload={'author': author, 'name': cleaned_author_str})
    models.AuthorAliasRaws.objects.create(author_alias=author_alias, raw=raw)
    models.PublicationAuthors.objects.create(publication=publication, author=author)

    return author


def guess_author_str_split(author_str):
    author_split_and = re.split(r"\band\b", author_str)
    author_split_and = [author_str.strip() for author_str in author_split_and]
    return author_split_and


def make_authors(publication: models.Publication, raw: models.Raw, entry, audit_command) -> List[models.Author]:
    author_str = entry.get("author")
    if author_str is not None:
        authors_split = guess_author_str_split(author_str)
        authors_aliases = [make_author(publication, raw, s, audit_command) for s in authors_split]
        return authors_aliases
    else:
        return []


def make_references(publication: models.Publication,
                    entry,
                    raw: models.Raw,
                    audit_command: models.AuditCommand) -> List[models.Publication]:
    refs_str = entry.get("cited-references")
    return ref.process_many(publication, refs_str, raw, audit_command)


def make_date_published(entry) -> Optional[datetime.date]:
    date_published_text = entry.get("year", "")
    date_published = None
    if date_published_text:
        if date_published_text.isnumeric():
            date_published = datetime.date(int(date_published_text), 1, 1)
    return date_published, date_published_text


def process(entry, audit_command: models.AuditCommand) -> models.Publication:
    date_published, date_published_text = make_date_published(entry)
    container, container_alias = make_container(entry, audit_command)

    publication = models.Publication.objects.log_create(
        audit_command=audit_command,
        payload={'title': util.sanitize_name(entry.get("title", "")),
                 'date_published_text': date_published_text,
                 'date_published': date_published,
                 'doi': entry.get("doi", ""),
                 'abstract': entry.get("abstract", ""),
                 'is_primary': True,
                 'added_by': audit_command.creator,
                 'journal': container})

    raw = models.Raw.objects.create(
        key=models.Raw.BIBTEX_ENTRY,
        value=entry,
        publication=publication,
        container_alias=container_alias)

    make_references(publication, entry, raw, audit_command)
    make_authors(publication, raw, entry, audit_command)

    return publication
