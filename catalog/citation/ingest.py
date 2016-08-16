import bibtexparser
import json

from . import merger
from . import bibtex as bibtex_api
from .bibtex import entry as bibtex_entry_api
from .crossref import doi_lookup as crossref_doi_api, author_year_lookup as crossref_search_api
from . import models
from django.db import connection
from django.contrib.auth.models import User

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


def dedupe_publications_by_doi(audit_command: models.AuditCommand):
    mergeset = merger.create_publication_mergeset_by_doi()
    merger.merge_publications(mergeset, audit_command)


def dedupe_publications_by_title(audit_command: models.AuditCommand):
    mergeset = merger.create_publication_mergeset_by_titles()
    merger.merge_publications(mergeset, audit_command)


def dedupe_containers_by_issn(audit_command: models.AuditCommand):
    mergeset = merger.create_container_mergeset_by_issn()
    merger.merge_containers(mergeset, audit_command)


def dedupe_containers_by_name(audit_command: models.AuditCommand):
    mergeset = merger.create_container_mergeset_by_name()
    merger.merge_containers(mergeset, audit_command)


def dedupe_authors_by_orcid(audit_command: models.AuditCommand):
    mergeset = merger.create_author_mergeset_by_orcid()
    merger.merge_containers(mergeset, audit_command)


def dedupe_authors_by_publication_and_name(audit_command: models.AuditCommand):
    mergeset = merger.create_author_mergeset_by_name()
    merger.merge_authors(mergeset, audit_command)


DISPATCH_DEDUPE = {
    "dedupe_publications_by_doi": dedupe_publications_by_doi,
    "dedupe_authors_by_orcid": dedupe_authors_by_orcid,
    "dedupe_containers_by_issn": dedupe_containers_by_issn,
    "dedupe_publications_by_title": dedupe_publications_by_title,
    "dedupe_authors_by_name": dedupe_authors_by_publication_and_name,
    "dedupe_containers_by_name": dedupe_containers_by_name
}


def dedupe(settings, user: User):
    steps = settings.steps
    for step in steps:
        audit_command = models.AuditCommand.objects.create(creator=user,
                                                           action=step,
                                                           role=models.AuditCommand.Role.CURATOR_EDIT)
        DISPATCH_DEDUPE[step](audit_command)