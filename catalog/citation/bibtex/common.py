from . import entry as entry_api
from .. import models, merger

import bibtexparser
import pickle
import json
from typing import Optional
from collections import namedtuple
from django.db import transaction


class AlreadyExistsError(Exception): pass


class Settings:
    def __init__(self, file_name: str, output_file_name: str, log_file_name: Optional[str]):
        self.file_name = file_name
        self.output_file_name = output_file_name
        self.log_file_name = log_file_name

    @classmethod
    def from_file(cls, file_name: str):
        with open(file_name, "r") as f:
            contents = f.read()
            settings = json.loads(contents)
            return cls(file_name=settings['file_name'],
                       output_file_name=settings['output_file_name'],
                       log_file_name=settings.get('log_file_name'))


def load_bibtex(file_name):
    with open(file_name) as f:
        contents = f.read()
        bib_db = bibtexparser.loads(contents)
        return bib_db.entries


def process_entries(settings, user):
    entries = load_bibtex(settings.file_name)

    errors = []
    duplicates = []
    for ind, entry in enumerate(entries):
        error, duplicate = entry_api.process(entry, user)
        if error:
            errors.extend(error)
        if duplicate:
            duplicates.extend(duplicate)
        if ind % 20 == 0:
            print("\nProcessed %s Primary Publications\n" % ind)
    return {"errors": errors, "duplicates": duplicates}


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
