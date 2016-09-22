import re
import datetime
from django.contrib.auth.models import User
from collections import defaultdict

from typing import Dict, List, Optional, Tuple
from .. import common
from .. import ref
from ... import models
from ... import util


def guess_author_str_split(author_str):
    author_split_and = re.split(r"\band\b", author_str)
    author_split_and = [models.Author.normalize_author_name(author_str) for author_str in author_split_and]
    return author_split_and


def guess_author_email_str_split(author_email_str: str):
    author_emails = [author_email.strip() for author_email in author_email_str.split("\n") if author_email.strip()]
    return author_emails


def guess_orcid_numbers_str_split(orcid_numbers_str):
    orcid_number_lines = [l for l in orcid_numbers_str.split("\n") if l.strip()]
    orcid_numbers = []
    for orcid_number_line in orcid_number_lines:
        author_part, orcid_part = orcid_number_line.split("/")
        family_name, given_name = models.Author.normalize_author_name(author_part)
        orcid_numbers.append((orcid_part.strip(), family_name, given_name))

    return orcid_numbers


def guess_researcherid_str_split(researcherid_str):
    researcherid_lines = [l for l in researcherid_str.split("\n") if l.strip()]
    researcherids = []
    for researcherid_line in researcherid_lines:
        author_part, researcherid_part = researcherid_line.split("/")
        family_name, given_name = models.Author.normalize_author_name(author_part)
        researcherids.append((researcherid_part.strip(), family_name, given_name))

    return researcherids


def combine_author_info(author_names, author_emails, author_orcids, author_researcherids) -> List[models.Author]:
    n_author_names = len(author_names)
    include_emails = n_author_names == len(author_emails)

    author_name_orcid_map = defaultdict(lambda: [])
    for author_orcid in author_orcids:
        author_name = author_orcid[1:3]
        author_name_orcid_map[author_name].append(author_orcid[0])

    author_name_researcherid_map = defaultdict(lambda: [])
    for author_researchid in author_researcherids:
        author_name = author_researchid[1:3]
        author_name_researcherid_map[author_name].append(author_researchid[0])

    authors = []
    for author_name in author_names:
        orcids = author_name_orcid_map[author_name]
        researcherids = author_name_researcherid_map[author_name]

        author = models.Author(family_name=author_name[0],
                               given_name=author_name[1],
                               orcid=orcids[0] if len(orcids) > 0 else "",
                               researcherid=researcherids[0] if len(researcherids) > 0 else "")
        authors.append(author)

    if include_emails:
        for ind, author in enumerate(authors):
            author.email = author_emails[ind]
        unassigned_emails = []
    else:
        unassigned_emails = author_emails

    return authors, unassigned_emails


def make_date_published(entry) -> Optional[datetime.date]:
    date_published_text = entry.get("year", "")
    return date_published_text


def create_detached_publication(entry, creator):
    date_published_text = make_date_published(entry)
    publication = models.Publication(
        abstract=entry.get("abstract", ""),
        added_by=creator,
        date_published_text=date_published_text,
        doi=entry.get("doi", ""),
        isi=entry.get("isi", ""),
        is_primary=True,
        title=util.sanitize_name(entry.get("title", ""))
    )
    return publication


def create_detached_container(entry):
    container_str = entry.get("journal", "")
    container_type_str = entry.get("type", "")
    container_issn_str = entry.get("issn", "")
    # container_eissn_str = entry.get("eissn", "")
    container = models.Container(type=container_type_str,
                                 issn=container_issn_str,
                                 name=container_str)

    return container


def create_detached_authors(entry):
    """Create authors from """
    author_str = entry.get("author")
    author_emails_str = entry.get("author-email", "")
    author_orcid_str = entry.get("orcid-numbers", "")
    researcherid_str = entry.get("researcherid-numbers", "")

    author_names = guess_author_str_split(author_str)
    author_emails = guess_author_email_str_split(author_emails_str)
    author_orcids = guess_orcid_numbers_str_split(author_orcid_str)
    author_researcherids = guess_researcherid_str_split(researcherid_str)

    authors = combine_author_info(author_names,
                                  author_emails,
                                  author_orcids,
                                  author_researcherids)
    return authors


def create_detached_raw(entry):
    return models.Raw(
        key=models.Raw.BIBTEX_ENTRY,
        value=entry)


def augment_authors(audit_command, publication, detached_authors):
    if publication.is_primary:
        augmented_authors = []
        unaugmented_authors = []
        for detached_author in detached_authors:
            duplicate = detached_author.duplicates().first()
            if duplicate:
                detached_author.augment(audit_command, duplicate)
                augmented_authors.append(duplicate)
            else:
                unaugmented_authors.append((ref, detached_author))
    else:
        # We can delete all creators for a secondary publication without checking that they are referenced by other
        # entities because secondary entries for authors do not enough information for merging to ever occur
        publication.creators.log_delete(audit_command)
        create_authors(audit_command, publication, detached_authors)
        augmented_authors = []
    return augmented_authors


def augment_citations(audit_command, publication, entry, creator):
    if publication.citations.count() == 0:
        return create_citations(publication, entry, creator)
    else:
        refs_str = entry.get("cited-references")
        return ref.augment_many(audit_command, publication, refs_str, creator)


def create_authors(audit_command: models.AuditCommand, publication: models.Publication,
                   detached_authors: List[models.Author]):
    """Create authors from dettached authors. If author is already in the database then it is just linked to
     the publication"""

    unduplicated_authors = []
    for detached_author in detached_authors:
        duplicate = detached_author.duplicates().order_by('date_added').first()
        if duplicate:
            detached_author.augment(audit_command=audit_command, author=duplicate)
            models.PublicationAuthors.objects.log_get_or_create(audit_command=audit_command,
                                                                publication_id=publication.id, author_id=duplicate.id)
        else:
            unduplicated_authors.append(detached_author)

    authors = models.Author.objects.bulk_create(unduplicated_authors)
    publication_authors = [models.PublicationAuthors(publication=publication, author=author) for author in
                           unduplicated_authors]
    models.PublicationAuthors.objects.bulk_create(publication_authors)


def create_citations(publication, entry, creator):
    refs_str = entry.get("cited-references")
    return ref.create_many(publication, refs_str, creator)


def create_container(audit_command: models.AuditCommand, detached_container: models.Container):
    container = detached_container.duplicates().order_by('date_added').first()
    if container:
        detached_container.augment(audit_command=audit_command, container=container)
    else:
        container = detached_container
        container.save()
    return container


def process(entry: Dict, creator: User):
    detached_publication = create_detached_publication(entry, creator)
    detached_container = create_detached_container(entry)
    detached_authors, unassigned_emails = create_detached_authors(entry)
    detached_raw = create_detached_raw(entry)

    duplicate_publications = detached_publication.duplicates()
    publication_already_in_db = len(duplicate_publications) > 0

    audit_command = models.AuditCommand(creator=creator, action=models.AuditCommand.Action.MERGE)
    if publication_already_in_db:
        publication = duplicate_publications[0]
        unaugmented_authors = augment_authors(audit_command, publication, detached_authors)
        detached_publication.augment(audit_command, publication)
        detached_container.augment(audit_command, publication.container)

        detached_raw.container = publication.container
        detached_raw.publication = publication
        if not audit_command._state.adding:
            # Save a raw value if we've done any updates
            detached_raw.save()

        augment_citations(audit_command, publication, entry, creator)
    else:
        container = create_container(audit_command, detached_container)
        publication = detached_publication
        publication.container = container
        publication.save()
        create_authors(audit_command, publication, detached_authors)

        create_citations(publication, entry, creator)
        unaugmented_authors = []

        detached_raw.container = publication.container
        detached_raw.publication = publication
        detached_raw.save()

    return common.PublicationLoadErrors(raw=detached_raw, audit_command=audit_command,
                                        unaugmented_authors=unaugmented_authors,
                                        unassigned_emails=unassigned_emails)
