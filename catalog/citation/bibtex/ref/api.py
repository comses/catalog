import re
from typing import List, Optional
from ... import util
from ... import models

import logging

logger = logging.getLogger(__name__)


class NullError(Exception): pass


def make_container(raw: models.Raw, container_str: str) -> models.Container:
    container = models.Container.objects.create()
    container_alias = models.ContainerAlias.objects.create(container=container,
                                                           name=container_str)
    models.ContainerRaw.objects.create(raw=raw,
                                       publication_raw_id=raw.id,
                                       name=container_str,
                                       container_alias=container_alias)
    return container


def make_author(raw: models.Raw, author_str: str) -> models.Author:
    cleaned_author_str = util.last_name_and_initials(util.normalize_name(author_str))
    author = models.Author.objects.create(type=models.Author.INDIVIDUAL)
    author_alias = models.AuthorAlias.objects.create(author=author,
                                                     name=cleaned_author_str)
    models.AuthorRaw.objects.create(raw=raw,
                                    publication_raw_id=raw.id,
                                    name=cleaned_author_str,
                                    type=models.AuthorRaw.INDIVIDUAL,
                                    author_alias=author_alias)
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


def make_year(year_str: str) -> int:
    year = None
    if year_str:
        if year_str.isnumeric():
            year = int(year_str)
    return year


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


def process(publication_raw: models.PublicationRaw, ref: str) -> models.PublicationRaw:
    author_str = None
    year_str = None
    container_str = None

    if ref:
        author_str, year_str, container_str = guess_elements(ref)

    doi = make_doi(ref)

    secondary_publication = models.Publication.objects.create(
        title="",
        year=make_year(year_str),
        doi=doi,
        abstract="",
        primary=False)

    secondary_raw = models.Raw.objects.create(
        key=models.Raw.BIBTEX_REF,
        value=ref,
        publication=secondary_publication)

    secondary_publication_raw = models.PublicationRaw.objects.create(
        title=secondary_publication.title,
        year=secondary_publication.year,
        doi=doi,
        abstract=secondary_publication.abstract,
        primary=False,
        raw=secondary_raw,
        referenced_by=publication_raw)

    author = make_author(secondary_raw, author_str)
    container = make_container(secondary_raw, container_str)

    secondary_publication.authors.add(author)
    secondary_publication.container = container
    secondary_publication.save()

    return secondary_publication_raw


def process_many(publication_raw: models.PublicationRaw, refs_str: Optional[str]) -> List[models.PublicationRaw]:
    if refs_str:
        refs = refs_str.split("\n")
    else:
        refs = []
    return [process(publication_raw, ref) for ref in refs]
