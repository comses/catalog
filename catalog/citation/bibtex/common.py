from . import entry as entry_api
from .. import models

import bibtexparser
import json
from typing import List


class Settings:
    def __init__(self, file_name, steps):
        self.file_name = file_name
        self.steps = steps

    @classmethod
    def from_file(cls, file_name):
        with open(file_name, "r") as f:
            contents = f.read()
            settings = json.loads(contents)
            return cls(file_name=settings['file_name'], steps=settings['steps'])


def load_bibtex(file_name):
    with open(file_name) as f:
        contents = f.read()
        bib_db = bibtexparser.loads(contents)
        return bib_db.entries


def process_entries(settings_file_name, user):
    settings = Settings.from_file(file_name=settings_file_name)
    entries = load_bibtex(settings.file_name)

    audit_command = models.AuditCommand.objects.create(
        role=models.AuditCommand.Role.CURATOR_EDIT,
        creator=user,
        action=models.AuditCommand.Action.LOAD)

    ind = 0
    for entry in entries:
        publication = entry_api.process(entry, audit_command)
        display(publication, ind)
        ind += 1


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