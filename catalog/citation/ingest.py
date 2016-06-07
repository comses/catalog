import bibtexparser
from . import merger
from .bibtex import entry as bibtex_entry_api
from .crossref import doi_lookup as crossref_doi_api, author_year_lookup as crossref_search_api
from . import models
from django.db import connection


from typing import List


class BadDoiLookup(Exception): pass


SLEEP_TIME = 0.1


def load_bibtex(file_name):
    with open(file_name) as f:
        contents = f.read()
        bib_db = bibtexparser.loads(contents)
        return bib_db.entries


def display(publication_raw, ind):
    if publication_raw.primary:
        begin = ""
    else:
        begin = "\t"
    print("{}{} Year: {}; Title: {}; DOI: {}"
          .format(begin,
                  ind,
                  publication_raw.year,
                  publication_raw.title,
                  publication_raw.doi))


def ingest(entries: List):
    publications_raw = []
    for (ind, entry) in enumerate(entries):
        publication_raw = bibtex_entry_api.process(entry)
        publications_raw.append(publication_raw)
        display(publication_raw, ind)
    return publications_raw


def dedupe_publications_by_doi():
    mergeset = merger.create_publication_mergeset_by_doi()
    merger.merge_publications(mergeset)


def crossref_dois_lookup(limit=None):
    """
    Add missing information with CrossRef DOI search

    Precondition: publications DOIs have been deduped
    """

    sql = \
        """SELECT id, doi
        FROM citation_publication
        WHERE doi <> '' AND id IN (
            SELECT publication_id
            FROM citation_raw AS raw
            LEFT JOIN citation_publicationraw AS raw_pub ON raw_pub.raw_id = raw.id
            INNER JOIN citation_publication AS pub ON pub.id = raw.publication_id
            GROUP BY publication_id
            HAVING bool_and(raw.key = 'BIBTEX_ENTRY' OR
                            raw.key = 'BIBTEX_REF') AND
                   (bool_and(pub.title = '') OR
                    bool_and(pub.abstract = '') OR
                    bool_and(pub.year IS NULL)))"""

    if isinstance(limit, int) and 1 <= limit:
        sql += "\nLIMIT {};".format(limit)
    else:
        sql += ";"

    publications = models.Publication.objects.raw(sql)

    for (ind, publication) in enumerate(publications):
        print("Entry")
        display(publication, ind)
        other_publication_raw = crossref_doi_api.update(publication)
        if isinstance(other_publication_raw, models.PublicationRaw):
            display(other_publication_raw, ind)
        else:
            print("\t{} {}".format(ind, other_publication_raw))


def crossref_year_author_lookup(limit=None):
    """Add missing information with CrossRef year author search"""

    sql = \
        """SELECT id AS raw_id,
               publication_id,
               year,
               title,
               doi,
               raw_authors.names AS names
        FROM citation_raw AS raw
        LEFT JOIN citation_publicationraw AS raw_pub ON raw_pub.raw_id = raw.id
        LEFT JOIN (
          SELECT raw_id, array_agg(name) AS names
          FROM citation_authorraw
          GROUP BY raw_id
        ) AS raw_authors ON raw_authors.raw_id = raw.id
        WHERE publication_id IN (
            SELECT publication_id
            FROM citation_raw AS raw
            LEFT JOIN citation_publicationraw AS raw_pub ON raw_pub.raw_id = raw.id
            LEFT JOIN citation_publication AS pub ON pub.id = raw.publication_id
            GROUP BY publication_id
            HAVING bool_and(raw.key = 'BIBTEX_ENTRY' OR
                            raw.key = 'BIBTEX_REF') AND
                   (bool_and(pub.title = '') OR
                    bool_and(pub.abstract = '') OR
                    bool_and(pub.year IS NULL)))
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
        other_publication_raw = crossref_search_api.update(year_author_result)
        if other_publication_raw:
            display(other_publication_raw, ind)