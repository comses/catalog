from ... import models
from .. import common
from ... import util
from django.contrib.auth.models import User

import requests
from typing import Dict, List, Optional, Set
from fuzzywuzzy import fuzz
from django.db import connection


def process_item(year_authors_result: Dict, response_item: Dict, raw: models.Raw,
                 audit_command: models.AuditCommand) -> common.DetachedPublication:
    other_publication = models.Publication(
        year=common.get_year(response_item),
        title=common.get_title(response_item),
        doi=common.get_doi(response_item),
        primary=False)
    authors = common.make_author_author_alias_pairs(other_publication, response_item, create=False)
    container = common.make_container_container_alias_pair(other_publication, response_item, create=False)
    return common.DetachedPublication(publication=other_publication,
                                      author_author_alias_pairs=authors,
                                      container_container_alias_pair=container,
                                      raw=raw,
                                      audit_command=audit_command)


def process(year_authors_result: Dict, response: requests.Response, audit_command: models.AuditCommand) -> None:
    value = common.ResponseDictEncoder().encode(response)
    raw = models.Raw(key=models.Raw.CROSSREF_SEARCH_SUCCESS,
                     value=value,
                     data_source=audit_command,
                     publication_id=year_authors_result["id"])

    other_raw_publication = None
    if response.status_code == 200:
        response_json = response.json()
        response_items = response_json.get("message", {"items": []}).get("items", [])
        detached_publications = [process_item(year_authors_result, response_item, raw, audit_command) for response_item
                                 in response_items]

        matches = _match_publication(year_authors_result, detached_publications)
        if len(matches) == 1:
            match = matches.pop()
            detached_publication = detached_publications[match]
            detached_publication.attach_to(year_authors_result["id"], match)
            other_raw_publication = detached_publication.publication
        else:
            raw.key = models.Raw.CROSSREF_SEARCH_FAIL_NOT_UNIQUE
            raw.value["match_ids"] = list(matches)
            raw.save()
    else:
        raw.key = models.Raw.CROSSREF_SEARCH_FAIL_OTHER
        raw.save()
    return other_raw_publication


def update(year_authors_result: Dict, audit_command: models.AuditCommand):
    author_str = "; ".join(year_authors_result["author_names"])
    year = year_authors_result["date_published_text"]
    if year is not None and author_str:
        response = requests.get("http://api.crossref.org/works?query={}, {}".format(author_str, year))
        return process(year_authors_result, response, audit_command)
    else:
        print("Did not lookup")


def augment_publications(user: User, limit=None):
    """Add missing information with CrossRef year author search"""

    sql = \
        """
        WITH publication_ids_with_only_bibtex_raw AS (
            SELECT pubs.id AS id
            FROM citation_publication AS pubs
            INNER JOIN citation_raw AS raw ON raw.publication_id = pubs.id
            GROUP BY pubs.id, title, doi, date_published
            HAVING bool_and(raw.key ='BIBTEX_ENTRY' OR raw.key = 'BIBTEX_REF') OR count(raw.*) = 0
            ORDER BY id
        ), publication_ids_with_dois_and_missing_data AS (
            SELECT id
            FROM citation_publication
            WHERE doi <> '' AND (title = '' OR date_published_text = '' OR abstract = '')
        )
        SELECT pub.id, pub.date_published_text, pub.doi, pub.title
          , array_agg(trim(BOTH FROM creator.given_name || ' ' || creator.family_name, ' ')) AS author_names
        FROM citation_publication AS pub
        LEFT JOIN citation_publicationauthors AS pub_creators ON pub.id = pub_creators.publication_id
        LEFT JOIN citation_author AS creator ON pub_creators.author_id = creator.id
        LEFT JOIN (
          SELECT DISTINCT ON (author_id) id, family_name, given_name, author_id
          FROM citation_authoralias
        ) AS author_names ON author_names.author_id = creator.id
        WHERE pub.id IN
          (SELECT id FROM publication_ids_with_only_bibtex_raw
           INTERSECT
           SELECT id FROM publication_ids_with_dois_and_missing_data)
        GROUP BY pub.id, pub.date_published_text, pub.doi, pub.title
        """

    if isinstance(limit, int) and 1 <= limit:
        sql += "\nLIMIT {};".format(limit)
    else:
        sql += ";"

    cursor = connection.cursor()
    cursor.execute(sql)
    description = cursor.description
    columns = [col[0] for col in description]

    # Return rows of  the form {"id": Int, "authors": Array[String]}
    year_author_results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    for (ind, year_author_result) in enumerate(year_author_results):
        audit_command = models.AuditCommand.objects.create(
            creator=user, action="augment data crossref year author search")
        print("Entry")
        print("\t{ind} Year: {year}, Title: {title}, DOI: {doi} ID: {publication_id}".format(ind=ind,
                                                                                             **year_author_result))
        publication = update(year_author_result, audit_command)
        if publication:
            print(publication)


def _match_author_name(name: str, other_name: str):
    return name == other_name


def _match_publication_title(publication, detached_publications: List[common.DetachedPublication],
                             publication_matches: Set[int]) -> Set[int]:
    if publication["title"]:
        # Determine if titles approximately match
        publication_titles = [detached_publication.publication.title for detached_publication in detached_publications]
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


def _match_publication_year(publication, detached_publications: List[common.DetachedPublication],
                            publication_matches: Set[int]) -> Set[int]:
    if publication["date_published_text"] is not None:
        # Determine if years exactly match
        years_matches = set(i for (i, detached_publication) in enumerate(detached_publications)
                            if publication["year"] == detached_publication.publication_raw.year)
        publication_matches.intersection_update(years_matches)
        return publication_matches


def _match_publication_author(publication, detached_publication: common.DetachedPublication) -> bool:
    names = publication["names"]
    detached_raw_authors = detached_publication.authors_author_alias_pairs
    for name in names:
        for raw_author in detached_raw_authors:
            raw_name = raw_author.name
            if not _match_author_name(name, raw_name):
                return False
    return True


def _match_publication_authors(publication, detached_publications: List[common.DetachedPublication],
                               publication_matches: Set[int]) -> Set[int]:
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
