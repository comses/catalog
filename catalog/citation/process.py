import os
import re
import jsonpickle
import bibtexparser
import requests
import time
from bibtex import entry, ref
from crossref import doi_lookup, author_year_lookup
import publications as pub

from typing import List, Tuple


class BadDoiLookup(Exception): pass


SLEEP_TIME = 0.1


class Publications:
    def __init__(self, file_name):
        with open(file_name) as f:
            contents = f.read()
            bib_db = bibtexparser.loads(contents)
            self.raw_entries = bib_db.entries
            self.publications = []
            self.add_publications(self.raw_entries, self.publications)

        self.primary_ind = 0
        self.secondary_ind = None

    def __iter__(self):
        return self

    def __next__(self):
        total_primary_publications = len(self.publications)

        if self.primary_ind >= total_primary_publications:
            raise StopIteration
        else:
            total_secondary_publications = len(self.publications[self.primary_ind].citations)

        if self.secondary_ind is None:
            # print("primary: {}, secondary: {}".format(self.primary_ind, self.secondary_ind))
            self.secondary_ind = 0
            return self.publications[self.primary_ind]
        else:
            if self.secondary_ind < total_secondary_publications:
                secondary_ind = self.secondary_ind
                self.secondary_ind += 1
                # print("primary: {}, secondary: {}".format(self.primary_ind, secondary_ind))
                return self.publications[self.primary_ind].citations[secondary_ind]
            else:
                self.primary_ind += 1
                self.secondary_ind = None
                # print("primary: {}, secondary: {}".format(self.primary_ind, self.secondary_ind))
                return self.__next__()

    def reset(self):
        self.primary_ind = 0
        self.secondary_ind = None

    @property
    def state(self):
        return (self.primary_ind, self.secondary_ind)

    @staticmethod
    def add_publications(raw_entries, publications):
        for raw_entry in raw_entries:
            publication = entry.process(raw_entry)
            publications.append(publication)


class NoDoiPublication:
    def __init__(self,
                 state: Tuple[int, int],
                 publication: pub.PersistentPublication) -> None:
        self.primary_ind = state[0]
        self.secondary_ind = state[1]
        self.publication = publication


class CleanedCitationGraph:
    SAVE_FREQUENCY = 200

    def __init__(self, publications: Publications, save_path="data/full.bib.pickle"):
        self.with_dois = {}
        self.without_dois = []

        self.publications = publications # type: Publications
        self.save_file = save_path

    def save(self, f):
        print("Saving...")
        data = jsonpickle.encode(self)
        f.write(data)
        print("Saved")

    @staticmethod
    def display(publication, ind):
        if publication.primary:
            begin = ""
        else:
            begin = "\t"
        print("{}{} Author: {}; Year: {}; Title: {}"
              .format(begin,
                      ind,
                      " and ".join([author.fullname for author in publication.authors]),
                      publication.year.value,
                      publication.title.value))

    def _add_doi_entry(self, publication: pub.PersistentPublication) -> None:
        doi = publication.doi.value
        if doi is not None:
            if doi not in self.with_dois:
                self.with_dois[doi] = doi_lookup.update(publication)
            else:
                self.with_dois[doi].update(publication)

    def add_doi_entries(self) -> None:
        print("Adding DOI entries")
        print("---------------------------------")
        with open(self.save_file, "w") as f:
            ind = 1
            for publication in self.publications:
                self.display(publication, ind)
                time.sleep(SLEEP_TIME)
                self._add_doi_entry(publication)

                if ind % self.SAVE_FREQUENCY == 0:
                    self.save(f)
                ind += 1

            self.save(f)

    def _add_no_doi_entry(self, publication):
        publication = author_year_lookup.update(publication)
        doi = publication.doi.value
        if doi:
            self.with_dois[doi] = publication
        else:
            self.without_dois.append(NoDoiPublication(self.publications.state, publication))

    def add_no_doi_entries(self):
        print("Adding no DOI entries")
        print("---------------------------------")
        with open(self.save_file, "w") as f:
            ind = 1
            for publication in self.publications:
                doi = publication.doi.value
                if not doi:
                    self.display(publication, ind)
                    time.sleep(SLEEP_TIME)
                    self._add_no_doi_entry(publication)

                    if ind % self.SAVE_FREQUENCY == 0:
                        self.save(f)
                    ind += 1

            self.save(f)

    def dedupe(self):
        print("deduping")

    def add_entries(self):
        self.add_doi_entries()
        self.publications.reset()
        self.add_no_doi_entries()
        # self.dedupe()


def write_pickle(pickle_path, citation_graph):
    print("Saving...")
    with open(pickle_path, "w") as pickle_file:
        data = jsonpickle.encode(citation_graph)
        pickle_file.write(data)
    print("Saved")


def load_pickle(pickle_path):
    with open(pickle_path, "r") as pickle_file:
        data = pickle_file.read()
        citation_graph = jsonpickle.decode(data)
        return citation_graph


def write_and_add_entries(pickle_path, citation_graph, processed_entries, start_n=0, max_n=100):
    n = min(max_n, len(processed_entries))
    step_size = 50

    i = start_n + step_size

    try:
        while i < n:
            print("Primary Entries # {}".format(str(i - step_size) + " - " + str(i)))
            citation_graph.add_doi_entries(processed_entries[(i - step_size):i])
            i += step_size
            write_pickle(pickle_path, citation_graph)

        print("Last Chunk Primary Entries # {}".format(str(i - step_size) + " - " + str(n)))
        citation_graph.add_doi_entries(processed_entries[(i - step_size):n])
        write_pickle(pickle_path, citation_graph)
    except requests.exceptions.Timeout:
        print("Timed out")
        write_pickle(pickle_path, citation_graph)
    return citation_graph


def chunked_write_publications(pickle_path, citation_graph, citation_graph_cb,
                               processed_entries, start_n=0, max_n=100):
    n = min(max_n, len(processed_entries))
    step_size = 60

    i = start_n + step_size

    try:
        while i < n:
            print("Primary Entries # {} - {}".format(i - step_size, i))
            citation_graph_cb(processed_entries[(i - step_size):i])
            i += step_size
            write_pickle(pickle_path, citation_graph)

        print("Last Chunk Primary Entries # {} - {}".format(i - step_size, n))
        citation_graph_cb(processed_entries[(i - step_size):n])
        write_pickle(pickle_path, citation_graph)
    except requests.exceptions.Timeout:
        print("Timed out")
        write_pickle(pickle_path, citation_graph)
    return citation_graph