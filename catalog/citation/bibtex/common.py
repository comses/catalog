from . import entry as entry_api

import bibtexparser
import json
from typing import Optional

import textwrap


class AlreadyExistsError(Exception): pass


class PublicationLoadErrors:
    def __init__(self, raw, audit_command, unaugmented_authors, unassigned_emails):
        self.audit_command = audit_command
        self.unassigned_emails = unassigned_emails
        self.unaugmented_authors = unaugmented_authors
        self.raw = raw
        self.title = raw.publication.title

    def __bool__(self):
        return bool(self.unaugmented_authors) or bool(self.unassigned_emails)

    def __str__(self):
        unaugmented_authors_str = textwrap.indent("\n".join(" - " + str(ua) for ua in self.unaugmented_authors) \
                                                      if self.unaugmented_authors else "None", "\t")
        unaugmented_emails_str = textwrap.indent("\n".join(" - " + str(uc) for uc in self.unassigned_emails)
                                                    if self.unassigned_emails else "None", "\t")
        template = textwrap.dedent(
            """
            Publication Load Errors
            -----------------------
            Publication Title: {}

            Raw: {}

            AuditCommand: {}

            Unaugmented Authors:
            {}

            Unassigned Emails:
            {}

            """)
        return template.format(self.title if self.title else "None", str(self.raw), str(self.audit_command), unaugmented_authors_str,
                               unaugmented_emails_str)


def load_bibtex(file_name):
    with open(file_name) as f:
        contents = f.read()
        bib_db = bibtexparser.loads(contents)
        return bib_db.entries


def process_entries(file_name, user):
    entries = load_bibtex(file_name)

    errors = []
    for ind, entry in enumerate(entries):
        publication_load_error = entry_api.process(entry, user)
        if publication_load_error:
            errors.append(publication_load_error)
        if ind % 20 == 0:
            print("\nProcessed %s Primary Publications\n" % ind)
    return errors


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
