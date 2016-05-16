import re
from typing import List, Optional
from ... import util
from ... import publications as pub


def get_author(author_str: Optional[str]) -> pub.PersistentAuthor:
    family = None
    given = None

    cleaned_author_str = re.sub("\[|\]|\{|\}", "", author_str)
    if cleaned_author_str:
        author_split = cleaned_author_str.split(" ", 1)
        family = author_split[0]
        if len(author_split) > 1:
            given = author_split[1]

    return pub.make_author(family=family,
                           given=given,
                           previous=(pub.DataSource.bibtex_ref, author_str))


def get_doi(ref: str):
    try:
        last = ref.rsplit(",", 1)[1]
    except IndexError:
        return None

    match = re.search("^(?:.*DOI *)(10\..+)\.$", last)
    if match:
        return util.sanitize_doi(match.group(1))
    else:
        return None


def get_year(year_str: str) -> pub.Persistent[int]:
    year = None
    if year_str:
        if year_str.isnumeric():
            year = int(year_str)
    return pub.Persistent(year, (pub.DataSource.bibtex_ref, year_str))


def process(ref: str) -> pub.PersistentPublication:
    author = None
    year = None
    container_name = None

    if ref:
        split_citation = [s.strip() for s in ref.split(",", 3)]
        if len(split_citation) > 2:
            author, year, container_name = split_citation[:3]
        elif len(split_citation) == 2:
            author, year = split_citation
        elif len(split_citation) == 1:
            author = split_citation[0]

    doi = get_doi(ref)
    publication = pub.PersistentPublication(
        authors=[get_author(author)],
        year=get_year(year),
        title=pub.Persistent(None),
        doi=pub.Persistent(doi),
        container_name=pub.Persistent(container_name),
        container_type=pub.Persistent(None),
        abstract=pub.Persistent(None),
        citations=[],
        primary=False,
        previous=(pub.DataSource.bibtex_ref, ref))

    return publication


def process_many(refs_str: Optional[str]) -> List[pub.PersistentPublication]:
    if refs_str:
        refs = refs_str.split("\n")
    else:
        refs = []
    return [process(ref) for ref in refs]