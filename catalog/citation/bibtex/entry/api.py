import re
import datetime
from django.contrib.auth.models import User

from typing import Dict, List, Optional, Tuple
from .. import ref
from ... import models, merger, merger_strategies
from ... import util


def make_container(entry) -> models.Container:
    container_str = entry.get("journal", "")
    container_type_str = entry.get("type", "")
    container_issn_str = entry.get("issn", "")
    container = models.Container.objects.create(type=container_type_str,
                                                issn=container_issn_str,
                                                name=container_str)
    container_alias, created = models.ContainerAlias.objects.get_or_create(
        container=container,
        name=container_str,
        defaults={'container': container, 'name': container_str})

    return container, container_alias


def make_author(publication: models.Publication, raw: models.Raw, author_str: str) -> models.Author:
    cleaned_family_name, cleaned_given_name = models.Author.normalize_author_name(author_str)
    author = models.Author.objects.create(
        type=models.Author.INDIVIDUAL,
        family_name=cleaned_family_name,
        given_name=cleaned_given_name)
    models.RawAuthors.objects.create(author=author, raw=raw)
    models.PublicationAuthors.objects.create(publication=publication, author=author)

    return author


def guess_author_str_split(author_str):
    author_split_and = re.split(r"\band\b", author_str)
    author_split_and = [author_str.strip() for author_str in author_split_and]
    return author_split_and


def make_authors(publication: models.Publication, raw: models.Raw, entry) -> List[models.Author]:
    author_str = entry.get("author")
    if author_str is not None:
        authors_split = guess_author_str_split(author_str)
        authors_aliases = [make_author(publication, raw, s) for s in authors_split]
        return authors_aliases
    else:
        return []


def make_references(publication: models.Publication,
                    entry,
                    creator) -> List[models.Publication]:
    refs_str = entry.get("cited-references")
    return ref.process_many(publication, refs_str, creator)


def make_date_published(entry) -> Optional[datetime.date]:
    date_published_text = entry.get("year", "")
    return date_published_text


def create_in_memory_publication(entry):
    date_published_text = make_date_published(entry)
    publication = models.Publication(
        doi=entry.get("doi", ""),
        isi=entry.get("isi", ""),
        date_published_text=date_published_text,
        title=util.sanitize_name(entry.get("title", ""))
    )
    return publication


def process(entry: Dict, creator: User) -> Tuple[List[str], List[models.Raw]]:
    """


    :param entry: A BibTeX parser entry
    :param creator: The user to process the record as
    :return: A new publication record, if it was added to the database
    """

    in_memory_publication = create_in_memory_publication(entry)
    duplicates = merger_strategies.find_publication_duplicates_on_load(in_memory_publication)

    errors = []
    duplicate_warnings = []
    if len(duplicates) > 1:
        merge_group = merger.PublicationMergeGroup.from_list(list(duplicates))
        if merge_group.is_valid():
            audit_command = models.AuditCommand.objects.create(action=models.AuditCommand.Action.MERGE,
                                                               creator=creator)
            merge_group.merge(audit_command)
            merge_group.final.log_update(audit_command=audit_command, isi=in_memory_publication.isi)
            publication = merge_group.final
        else:
            errors.append(str(merge_group.errors))
            return errors, duplicate_warnings

    elif len(duplicates) == 1:
        duplicate_warnings.append(models.Raw(key=models.Raw.BIBTEX_ENTRY, value=entry))
        publication = duplicates[0]

    else:
        date_published_text = make_date_published(entry)
        container, container_alias = make_container(entry)
        publication = models.Publication.objects.create(
            title=util.sanitize_name(entry.get("title", "")),
            date_published_text=date_published_text,
            doi=entry.get("doi", ""),
            isi=entry.get("unique-id", ""),
            abstract=entry.get("abstract", ""),
            is_primary=True,
            added_by=creator,
            container=container)

        raw = models.Raw.objects.create(
            key=models.Raw.BIBTEX_ENTRY,
            value=entry,
            publication=publication,
            container=container)

        make_authors(publication, raw, entry)

    secondary_errors, secondary_duplicates = make_references(publication, entry, creator)
    errors.extend(secondary_errors)
    duplicate_warnings.extend(secondary_duplicates)
    return errors, duplicate_warnings
