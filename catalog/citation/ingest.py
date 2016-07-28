import bibtexparser
import json

from . import merger
from . import bibtex as bibtex_api
from .bibtex import entry as bibtex_entry_api
from .crossref import doi_lookup as crossref_doi_api, author_year_lookup as crossref_search_api
from . import models
from django.db import connection

from typing import List


class BadDoiLookup(Exception): pass


def display(publication, ind):
    if publication.is_primary:
        begin = ""
    else:
        begin = "\t"
    print("{}{} Date Added: {}; Title: {}; DOI: {}"
          .format(begin,
                  ind,
                  publication.date_added,
                  publication.title,
                  publication.doi))

SLEEP_TIME = 0.1


def ingest_crossref_doi(data_source, limit=None):
    """
    Add missing information with CrossRef DOI search

    Precondition: publications DOIs have been deduped
    """

    sql = \
        """
        SELECT pubs.id, doi
        FROM citation_publication AS pubs
        INNER JOIN citation_raw_publications AS raw_pubs ON raw_pubs.publication_id = pubs.id
        INNER JOIN citation_raw AS raw ON raw.id = raw_pubs.raw_id
        GROUP BY pubs.id, doi
        HAVING bool_and(raw.key = 'BIBTEX_ENTRY' OR
                        raw.key = 'BIBTEX_REF') AND
               (bool_and(pubs.title = '') OR
                bool_and(pubs.abstract = '') OR
                bool_and(pubs.date_published IS NULL))
        ORDER BY id"""

    if isinstance(limit, int) and 1 <= limit:
        sql += "\nLIMIT {};".format(limit)
    else:
        sql += ";"

    publications = models.Publication.objects.raw(sql)

    for (ind, publication) in enumerate(publications):
        print("Entry")
        display(publication, ind)
        other_publication = crossref_doi_api.update(publication, data_source)
        if isinstance(other_publication, models.Publication):
            display(other_publication, ind)
        else:
            print("\t{} {}".format(ind, other_publication))


def ingest_crossref_search(data_source, limit=None):
    """Add missing information with CrossRef year author search"""

    sql = \
        """
        SELECT pubs.id, title, doi, date_published
        FROM citation_publication AS pubs
        INNER JOIN citation_raw_publications AS raw_pubs ON raw_pubs.publication_id = pubs.id
        INNER JOIN citation_raw AS raw ON raw.id = raw_pubs.raw_id
        GROUP BY pubs.id, title, doi, date_published
        HAVING bool_and(raw.key = 'BIBTEX_ENTRY' OR
                        raw.key = 'BIBTEX_REF') AND
               (bool_and(pubs.title = '') OR
                bool_and(pubs.abstract = '') OR
                bool_and(pubs.date_published IS NULL))
        ORDER BY id"""

    if isinstance(limit, int) and 1 <= limit:
        sql += "\nLIMIT {};".format(limit)
    else:
        sql += ";"

    cursor = connection.cursor()
    cursor.execute(sql)
    description = cursor.description
    columns = [col[0] for col in description]

    year_author_results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    for (ind, year_author_result) in enumerate(year_author_results):
        print("Entry")
        print("\t{ind} Year: {year}, Title: {title}, DOI: {doi} ID: {publication_id}".format(ind=ind, **year_author_result))
        other_publication_raw = crossref_search_api.update(year_author_result, data_source)
        if other_publication_raw:
            display(other_publication_raw, ind)


def dedupe_publications_by_doi():
    mergeset = merger.create_publication_mergeset_by_doi()
    merger.merge_publications(mergeset)


def dedupe_publications_by_title():
    mergeset = merger.create_publication_mergeset_by_titles()
    merger.merge_publications(mergeset)


def dedupe_containers_by_issn():
    mergeset = merger.create_container_mergeset_by_issn()
    merger.merge_containers(mergeset)


def dedupe_containers_by_name():
    mergeset = merger.create_container_mergeset_by_name()
    merger.merge_containers(mergeset)


def dedupe_authors_by_orcid():
    mergeset = merger.create_author_mergeset_by_orcid()
    merger.merge_containers(mergeset)


def dedupe_authors_by_publication_and_name():
    mergeset = merger.create_author_mergeset_by_name()
    merger.merge_authors(mergeset)