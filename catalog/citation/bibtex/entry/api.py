import re

from typing import List, Optional
from .. import ref
from ... import models
from ... import util


def make_container(raw, entry) -> models.Container:
    container_str = entry.get("journal", "")
    container_type_str = entry.get("type", "")
    container_issn_str = entry.get("issn", "")
    container = models.Container.objects.create(type=container_type_str,
                                                issn=container_issn_str)
    container_alias = models.ContainerAlias.objects.create(container=container,
                                                           name=container_str)
    container_raw = models.ContainerRaw.objects.create(raw=raw,
                                                       publication_raw_id=raw.id,
                                                       name=container_str,
                                                       type=container_type_str,
                                                       issn=container_issn_str,
                                                       container_alias=container_alias)
    return container


def make_author(raw: models.Raw, author_str: str) -> models.Author:
    cleaned_author_str = util.last_name_and_initials(util.normalize_name(author_str))
    author = models.Author.objects.create(type=models.Author.INDIVIDUAL)
    author_alias = models.AuthorAlias.objects.create(author=author,
                                                     name=cleaned_author_str)
    models.AuthorRaw.objects.create(
        raw=raw,
        publication_raw_id=raw.id,
        name=cleaned_author_str,
        type=models.AuthorRaw.INDIVIDUAL,
        author_alias=author_alias)
    return author


def guess_author_str_split(author_str):
    author_split_and = re.split(r"\band\b", author_str)
    author_split_and = [author_str.strip() for author_str in author_split_and]
    return author_split_and


def make_authors(raw: models.Raw, entry) -> List[models.Author]:
    author_str = entry.get("author")
    if author_str is not None:
        authors_split = guess_author_str_split(author_str)
        authors_aliases = [make_author(raw, s) for s in authors_split]
        return authors_aliases
    else:
        return []


def make_references(publication_raw: models.PublicationRaw, entry) -> List[models.PublicationRaw]:
    refs_str = entry.get("cited-references")
    return ref.process_many(publication_raw, refs_str)


def make_year(entry) -> Optional[int]:
    year_str = entry.get("year")
    year = None
    if year_str:
        if year_str.isnumeric():
            year = int(year_str)
    return year


def process(entry) -> models.PublicationRaw:
    publication = models.Publication.objects.create(
        title=util.sanitize_name(entry.get("title", "")),
        year=make_year(entry),
        doi=entry.get("doi", ""),
        abstract=entry.get("abstract", ""),
        primary=True)

    raw = models.Raw.objects.create(
        key=models.Raw.BIBTEX_ENTRY,
        value=entry,
        publication=publication)

    publication_raw = models.PublicationRaw.objects.create(
        title=publication.title,
        year=publication.year,
        doi=publication.doi,
        abstract=publication.abstract,
        primary=True,
        raw=raw)

    make_references(publication_raw, entry)
    authors = make_authors(raw, entry)
    container = make_container(raw, entry)

    publication.authors = authors
    publication.container = container
    publication.save()

    return publication_raw
