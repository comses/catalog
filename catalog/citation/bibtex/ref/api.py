import re
from typing import List, Optional
from ... import util
from ... import models, merger
from .. import common
from django.contrib.auth.models import User

import datetime
import logging

logger = logging.getLogger(__name__)


class NullError(Exception): pass


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


def create_detached_author(author_str):
    family_name, given_name = models.Author.normalize_author_name(author_str)
    return models.Author(family_name=family_name, given_name=given_name)


def create_detached_citation(ref: str, year_str: str, creator: User):
    doi = make_doi(ref)
    citation = models.Publication(
        title='',
        date_published_text=year_str,
        doi=doi,
        abstract='',
        is_primary=False,
        added_by=creator)
    return citation


def create_detached_container(container_str):
    return models.Container(name=container_str)


def create_detached_raw(ref):
    return models.Raw(key=models.Raw.BIBTEX_REF, value=ref)


def create_detached_citation_and_related(publication, ref, creator):
    author_str = None
    year_str = None
    container_str = None

    if ref:
        author_str, year_str, container_str = guess_elements(ref)

    detached_author = create_detached_author(author_str)
    detached_citation = create_detached_citation(ref, year_str, creator)
    detached_container = create_detached_container(container_str)
    detached_raw = create_detached_raw(ref)
    duplicate_citation = detached_citation.duplicates().order_by('date_added').first()

    return detached_citation, detached_author, detached_container, detached_raw, duplicate_citation


def create_citation(publication: models.Publication,
                    ref: str,
                    creator: User) -> models.Publication:
    detached_citation, detached_author, detached_container, detached_raw, duplicate_citation = \
        create_detached_citation_and_related(publication, ref, creator)

    if duplicate_citation:
        audit_command = models.AuditCommand(action=models.AuditCommand.Action.MERGE,
                                            creator=creator)
        duplicate_author = _augment_citation(
            audit_command=audit_command, detached_citation=detached_citation,
            detached_author=detached_author, detached_container=detached_container,
            detached_raw=detached_raw, duplicate_citation=duplicate_citation)

        models.PublicationCitations.objects.log_get_or_create(audit_command=audit_command,
                                                              publication_id=publication.id,
                                                              citation_id=duplicate_citation.id)
        if duplicate_author:
            models.PublicationAuthors.objects.log_get_or_create(audit_command=audit_command,
                                                                publication_id=publication.id,
                                                                author_id=duplicate_author.id)
        citation = duplicate_citation
        detached_raw.publication = citation
        detached_raw.container = citation.container
        if not audit_command.has_been_saved:
            # Save a raw value if the state has been updated
            detached_raw.save()

    else:
        container, created = models.Container.objects.get_or_create(name=detached_container.name)
        detached_citation.container = container
        detached_citation.save()
        detached_author.save()

        author = detached_author
        citation = detached_citation

        models.PublicationAuthors.objects.create(publication=citation, author=author)
        models.PublicationCitations.objects.create(publication=publication, citation=citation)

        detached_raw.publication = citation
        detached_raw.container = citation.container
        detached_raw.save()


def _augment_citation(audit_command, detached_citation, detached_author, detached_container, detached_raw,
                      duplicate_citation):
    merger.augment_publication(duplicate_citation, detached_citation, audit_command)
    merger.augment_container(duplicate_citation.container, detached_container, audit_command)
    duplicate_author = detached_author.duplicates().first()
    if duplicate_author:
        merger.augment_author(duplicate_author, detached_author, audit_command)

    if not audit_command.has_been_saved:
        detached_raw.publication = duplicate_citation
        detached_raw.container = duplicate_citation.container
        detached_raw.save()
    return duplicate_author


def augment_citation(audit_command, publication, ref, creator):
    """Since secondary publications citation have little information don't bother trying to augment existing
    publications in the DB"""
    pass


def augment_many(audit_command: models.AuditCommand,
                 publication: models.Publication,
                 refs_str: Optional[str],
                 creator: User):
    if refs_str:
        refs = refs_str.split("\n")
    else:
        refs = []

    if refs_str:
        for ref in refs:
            augment_citation(audit_command, publication, ref, creator)


def create_many(publication: models.Publication,
                refs_str: Optional[str],
                creator: User) -> List[models.Publication]:
    if refs_str:
        refs = refs_str.split("\n")
    else:
        refs = []

    if refs_str:
        for ref in refs:
            create_citation(publication, ref, creator)
