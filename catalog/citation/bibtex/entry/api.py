import re

from typing import List
from .. import ref
from ... import publications as pub
from ... import util


def get_author(author_str: str) -> pub.PersistentAuthor:
    author_split = author_str.split(" ")
    assert len(author_split) >= 0

    family = author_split[0]
    given = None
    if len(author_split) > 1:
        given = author_split[1]

    author = pub.make_author(
        family=family,
        given=given,
        previous=(pub.DataSource.bibtex_entry, author_str))
    return author


def get_authors(entry) -> List[pub.PersistentAuthor]:
    author_str = entry.get("author")
    authors_split = re.split(",|and", author_str)
    authors_trimmed = [get_author(s.strip()) for s in authors_split]
    return authors_trimmed


def get_references(entry) -> List[pub.PersistentPublication]:
    refs_str = entry.get("cited-references", None)
    return ref.process_many(refs_str)


def get_year(entry) -> pub.Persistent[int]:
    year_str = entry.get("year")
    year = None
    if year_str:
        if year_str.isnumeric():
            year = int(year_str)
    return pub.Persistent(year, previous=(pub.DataSource.bibtex_entry, year_str))


def process(entry):
    return pub.PersistentPublication(
        authors=get_authors(entry),
        title=pub.Persistent(util.sanitize_name(entry.get("title"))),
        year=get_year(entry),
        doi=pub.Persistent(entry.get("doi")),
        abstract=pub.Persistent(entry.get("abstract")),
        container_type=pub.Persistent(entry.get("type")),
        container_name=pub.Persistent(util.sanitize_name(entry.get("journal"))),
        citations=get_references(entry),
        primary=True,
        previous=(pub.DataSource.bibtex_entry, entry))
