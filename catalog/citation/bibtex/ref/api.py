import re
from typing import List, Optional
from ... import util
from ... import models, merger, merger_strategies
from django.contrib.auth.models import User

import datetime
import logging

logger = logging.getLogger(__name__)


class NullError(Exception): pass


def make_container(container_str: str) -> models.Container:
    container = models.Container.objects.create(
        name=container_str
    )

    return container


def make_author(publication: models.Publication, raw: models.Raw, author_str: str) -> models.Author:
    cleaned_family_name, cleaned_given_name = models.Author.normalize_author_name(author_str)
    author = models.Author.objects.create(
        type=models.Author.INDIVIDUAL,
        given_name=cleaned_given_name,
        family_name=cleaned_family_name)
    models.RawAuthors.objects.create(author=author, raw=raw)
    models.PublicationAuthors.objects.create(publication=publication, author=author,
                                             role=models.PublicationAuthors.RoleChoices.AUTHOR)
    return author


def make_doi(ref: str) -> str:
    try:
        last = ref.rsplit(",", 1)[1]
    except IndexError:
        return ""

    match = re.search("^(?:.*DOI *)(10\..+)\.$", last)
    if match:
        return util.sanitize_doi(match.group(1))
    else:
        return ""


def make_date_published(year_str: str) -> int:
    date_published = None
    if year_str:
        if year_str.isnumeric():
            date_published = datetime.date(int(year_str), 1, 1)
    return date_published


def guess_elements(ref):
    """Guesses which fields belong to a split reference string that has less than normal length"""
    ref = [s.strip() for s in ref.split(",", 3)]
    n = len(ref)
    year_ind = None
    for (ind, el) in enumerate(ref):
        if el.strip().isnumeric():
            year_ind = ind

    if year_ind is not None:
        year_str = ref[year_ind]
        author_str = ref[year_ind - 1] if year_ind - 1 >= 0 else None
        container_str = ref[year_ind + 1] if year_ind + 1 < n else None
    else:
        year_str = None
        author_str = ref[0] if 0 < n else None
        container_str = ref[1] if 1 < n else None

    return author_str or "", year_str or "", container_str or ""


def create_in_memory_publication(doi):
    return models.Publication(doi=doi)


def process(publication: models.Publication,
            ref: str,
            creator: User) -> models.Publication:
    author_str = None
    year_str = None
    container_str = None

    if ref:
        author_str, year_str, container_str = guess_elements(ref)

    doi = make_doi(ref)
    in_memory_citation = create_in_memory_publication(doi)
    duplicates = merger_strategies.find_publication_duplicates_on_load(in_memory_citation)
    if len(duplicates) > 1:
        merge_group = merger.PublicationMergeGroup.from_list(list(duplicates))
        if merge_group.is_valid():
            audit_command = models.AuditCommand.objects.create(action=models.AuditCommand.Action.MERGE,
                                                               creator=creator)
            merge_group.merge(audit_command=audit_command)
            models.PublicationCitations.objects.log_create(audit_command=audit_command, publication_id=publication.id,
                                                           citation_id=merge_group.final.id)
            return None, None
        else:
            return str(merge_group.errors), None
    elif len(duplicates) == 1:
        models.PublicationCitations.objects.create(publication=publication, citation=duplicates[0])
        return None, models.Raw(key=models.Raw.BIBTEX_REF, value=ref)
    else:
        container = make_container(container_str)
        citation = models.Publication.objects.create(
            title='',
            date_published_text=year_str,
            date_published=make_date_published(year_str),
            doi=doi,
            abstract='',
            is_primary=False,
            added_by=creator,
            container=container)

        citation_raw = models.Raw.objects.create(
            key=models.Raw.BIBTEX_REF,
            value=ref,
            publication=citation,
            container=container
        )
        make_author(citation, citation_raw, author_str)
        models.PublicationCitations.objects.create(publication=publication, citation=citation)

        return None, None


def process_many(publication: models.Publication,
                 refs_str: Optional[str],
                 creator: User) -> List[models.Publication]:
    if refs_str:
        refs = refs_str.split("\n")
    else:
        refs = []

    duplicates = []
    errors = []
    if refs_str:
        for ref in refs:
            error, duplicate = process(publication, ref, creator)
            if error is not None:
                errors.append(error)
            if duplicate is not None:
                duplicates.append(duplicate)
    return errors, duplicates
