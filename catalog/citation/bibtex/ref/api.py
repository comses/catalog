import re
from typing import List, Optional
from ... import util
from ... import models

import datetime
import logging

logger = logging.getLogger(__name__)


class NullError(Exception): pass


def make_container(container_str: str, audit_command: models.AuditCommand) -> models.Container:
    container = models.Container.objects.log_create(
        audit_command=audit_command,
        payload={})
    container_alias = models.ContainerAlias.objects.log_create(
        audit_command=audit_command,
        payload={'container': container,
                 'name': container_str})

    return container, container_alias


def make_author(publication: models.Publication, raw: models.Raw, author_str: str, audit_command: models.AuditCommand) -> models.Author:
    cleaned_author_str = util.last_name_and_initials(util.normalize_name(author_str))
    author = models.Author.objects.log_create(
        audit_command=audit_command,
        payload={'type': models.Author.INDIVIDUAL})
    author_alias = models.AuthorAlias.objects.log_create(
        audit_command=audit_command,
        payload={'author': author,
                 'name': cleaned_author_str})
    models.AuthorAliasRaws.objects.create(author_alias=author_alias, raw=raw)
    models.PublicationAuthors.objects.create(publication=publication, author=author)
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


def process(publication: models.Publication,
            ref: str,
            raw: models.Raw,
            audit_command: models.AuditCommand) -> models.Publication:
    author_str = None
    year_str = None
    container_str = None

    if ref:
        author_str, year_str, container_str = guess_elements(ref)

    doi = make_doi(ref)

    container, container_alias = make_container(container_str, audit_command)
    citation = models.Publication.objects.log_create(
        audit_command=audit_command,
        payload={'title': '',
                 'date_published_text': year_str,
                 'date_published': make_date_published(year_str),
                 'doi': doi,
                 'abstract': '',
                 'is_primary': False,
                 'added_by': audit_command.creator,
                 'journal': container})

    citation_raw = models.Raw.objects.create(
        key=models.Raw.BIBTEX_REF,
        value=ref,
        publication=citation,
        container_alias=container_alias
    )
    make_author(citation, citation_raw, author_str, audit_command)

    models.PublicationCitations.objects.create(publication=publication, citation=citation)

    return citation


def process_many(publication: models.Publication,
                 refs_str: Optional[str],
                 raw: models.Raw,
                 audit_command) -> List[models.Publication]:
    if refs_str:
        refs = refs_str.split("\n")
    else:
        refs = []
    return [process(publication, ref, raw, audit_command) for ref in refs]
