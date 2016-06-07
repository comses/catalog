from ... import models
from .. import common
from ... import util

import requests
from typing import Dict, List, Optional, Set
from fuzzywuzzy import fuzz


def process_item(publication: Dict, item: Dict, raw: models.Raw) -> common.DetachedPublication:
    other_raw_publication = models.PublicationRaw(
        year=common.get_year(item),
        title=common.get_title(item),
        doi=common.get_doi(item),
        primary=False)
    authors_raw = common.make_authors_raw(other_raw_publication, item, create=False)
    container_raw = common.make_container_raw(other_raw_publication, item, create=False)
    return common.DetachedPublication(publication_raw=other_raw_publication,
                                      authors_raw=authors_raw,
                                      container_raw=container_raw,
                                      raw=raw)


def process(query: Dict, response: requests.Response) -> None:
    value = common.ResponseDictEncoder().encode(response)
    raw = models.Raw(key=models.Raw.CROSSREF_SEARCH_SUCCESS,
                     value=value,
                     publication_id=query["publication_id"])

    other_raw_publication = None
    if response.status_code == 200:
        response_json = response.json()
        response_items = response_json.get("message", {"items": []}).get("items", [])
        detached_publications = [process_item(query, item, raw) for item in response_items]

        matches = _match_publication(query, detached_publications)
        if len(matches) == 1:
            match = matches.pop()
            detached_publication = detached_publications[match]
            detached_publication.attach_to(query["publication_id"], match)
            other_raw_publication = detached_publication.publication_raw
        else:
            raw.key = models.Raw.CROSSREF_SEARCH_FAIL_NOT_UNIQUE
            raw.value["match_ids"] = list(matches)
            raw.save()
    else:
        raw.key = models.Raw.CROSSREF_SEARCH_FAIL_OTHER
        raw.save()
    return other_raw_publication


def update(publication: Dict):
    author_str = "; ".join(publication["names"])
    year = publication["year"]
    if year is not None and author_str:
        response = requests.get("http://api.crossref.org/works?query={}, {}".format(author_str, year))
        return process(publication, response)


def _match_author_name(name: str, other_name: str):
    return name == other_name


def _match_publication_title(publication, detached_publications: List[common.DetachedPublication], publication_matches: Set[int]) -> Set[int]:
    if publication["title"]:
        # Determine if titles approximately match
        publication_titles = [detached_publication.publication_raw.title for detached_publication in detached_publications]
        title_match_ratios = [fuzz.partial_ratio(publication["title"], publication_title)
                              for publication_title in publication_titles]
        if 100 in title_match_ratios:
            return {title_match_ratios.index(100)}
        else:
            titles_matches = set(i for (i, result) in enumerate(title_match_ratios) if result >= 90)
            publication_matches.intersection_update(titles_matches)
            return publication_matches
    else:
        return publication_matches


def _match_publication_year(publication, detached_publications: List[common.DetachedPublication], publication_matches: Set[int]) -> Set[int]:
    if publication["year"] is not None:
        # Determine if years exactly match
        years_matches = set(i for (i, detached_publication) in enumerate(detached_publications)
                            if publication["year"] == detached_publication.publication_raw.year)
        publication_matches.intersection_update(years_matches)
        return publication_matches


def _match_publication_author(publication, detached_publication: common.DetachedPublication) -> bool:
    names = publication["names"]
    detached_raw_authors = detached_publication.authors_raw
    for name in names:
        for raw_author in detached_raw_authors:
            raw_name = raw_author.name
            if not _match_author_name(name, raw_name):
                return False
    return True


def _match_publication_authors(publication, detached_publications: List[common.DetachedPublication], publication_matches: Set[int]) -> Set[int]:
    author_matches = set(i for (i, other_publication) in enumerate(detached_publications)
                         if _match_publication_author(publication, other_publication))
    publication_matches.intersection_update(author_matches)
    return publication_matches


def _match_publication(year_authors_query, detached_publications: List[common.DetachedPublication]) -> Set[int]:
    publication_matches = set(range(len(detached_publications)))
    _match_publication_year(year_authors_query, detached_publications, publication_matches)
    _match_publication_title(year_authors_query, detached_publications, publication_matches)
    _match_publication_authors(year_authors_query, detached_publications, publication_matches)
    return publication_matches
