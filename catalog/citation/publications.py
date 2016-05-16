from . import util

from typing import TypeVar, Generic, List, Optional, Tuple, Any, Set
from enum import Enum
from fuzzywuzzy import fuzz
from unidecode import unidecode

T = TypeVar("T")


class DataSource(Enum):
    bibtex_entry = 0
    bibtex_ref = 1
    crossref_doi_success = 2
    crossref_doi_failed = 3
    crossref_doi_invalid = 4
    crossref_search_found = 5
    crossref_search_notfound = 6
    crossref_search_failed = 7
    normalized = 8
    unnormalized = 9


History = Tuple[DataSource, Any]


class Persistent(Generic[T]):
    def __init__(self, value: Optional[T], previous: Optional[History] = None) -> None:
        self.value = value
        if not previous:
            previous_values = []  # type: List[History]
        else:
            previous_values = [previous]
        self.previous_values = previous_values  # type: List[History]

    def __repr__(self):
        return "Persistent({})".format(self.value)

    def __eq__(self, other: "Persistent[T]") -> bool:
        return self.value == other.value and \
                self.previous_values == other.previous_values

    def update(self, persistent: 'Persistent[T]') -> None:
        self.previous_values.extend(persistent.previous_values)
        if self.value is None:
            if persistent.value is not None:
                self.value = persistent.value
        else:
            if persistent.value != self.value and persistent.value is not None:
                self.previous_values.append((DataSource.normalized, persistent.value))


class PersistentAuthor:
    def __init__(self, family: Persistent[str], given: Persistent[str], previous: Optional[History] = None) -> None:
        self.family = family
        self.given = given
        if previous:
            self.previous = [previous] # type: List[History]
        else:
            self.previous = []  # type: List[History]

    def __repr__(self):
        if self.family and self.given:
            return "PersistentAuthor({}, {})".format(self.family, self.given)

    def __eq__(self, other: "PersistentAuthor"):
        return self.family == other.family and \
                self.given == other.given and \
                self.previous == other.previous

    @property
    def fullname(self):
        has_given = self.given.value is not None and len(self.given.value) > 0
        has_family = self.family.value is not None
        if has_family:
            if has_given:
                return "{}, {}".format(self.family.value.upper(), self.given.value[0])
            else:
                return self.family.value.upper()
        else:
            return ""

    def matches(self, authors: List["PersistentAuthor"]):
        author_names = [author.fullname for author in authors]
        results = [fuzz.partial_ratio(self.fullname, author_name)
                   for author_name in author_names]
        if 100 in results:
            return {results.index(100)}
        else:
            best_results = set(i for (i, result) in enumerate(results)
                               if result >= 90*len(author_names[i]))
            return best_results

    def update(self, persistent_author: "PersistentAuthor"):
        self.family.update(persistent_author.family)
        self.given.update(persistent_author.given)
        self.previous.extend(persistent_author.previous)


def make_author(family: str, given: Optional[str], previous: Optional[History]):
    family_upper = unidecode(family.upper())
    given_upper = unidecode(given.upper()) if given is not None else None
    family_history = (DataSource.unnormalized, family) if family != family_upper else None
    given_history = (DataSource.unnormalized, given) if given != given_upper else None

    return PersistentAuthor(family=Persistent(family_upper, previous=family_history),
                            given=Persistent(given_upper, previous=given_history),
                            previous=previous)


def make_year(year: Optional[int], previous: Optional[History]):
    return Persistent(year, previous=previous)


def make_str(string: Optional[str], previous: Optional[History]):
    return Persistent(value=string, previous=previous)


def make_title(title: Optional[str], previous: Optional[History]):
    return Persistent(value=title, previous=previous)


def make_container_name(container_name: Optional[str], previous: Optional[History]):
    return make_str(string=container_name, previous=previous)


def make_container_type(container_type: Optional[str], previous: Optional[History]):
    return make_str(string=container_type, previous=previous)


def make_doi(doi: Optional[str], previous: Optional[History]):
    return make_str(string=doi, previous=previous)


def make_abstract(abstract: Optional[str], previous: Optional[History]):
    return make_str(string=abstract, previous=previous)


class PersistentPublication:
    def __init__(self,
                 authors: List[PersistentAuthor],
                 year: Persistent[int],
                 title: Persistent[str],
                 container_type: Persistent[str],
                 container_name: Persistent[str],
                 doi: Persistent[str],
                 abstract: Persistent[str],
                 citations: List["PersistentPublication"],
                 primary: bool,
                 previous: Optional[History]=None) -> None:

        self.authors = authors

        if year.value is not None:
            if 1000 < year.value < 2050:
                self.year = year
            else:
                raise ValueError("year {} should be between 1000 and 2050".format(year.value))
        else:
            self.year = year
        self.title = title
        self.container_name = container_name
        self.container_type = container_type
        self.doi = doi
        self.abstract = abstract
        self.citations = citations
        self.primary = primary

        if previous:
            self.previous_values = [previous]
        else:
            self.previous_values = []

    @property
    def secondary_publications_with_dois(self):
        return iter(secondary_publication for secondary_publication in self.citations
                    if secondary_publication.doi.value is not None)

    @property
    def secondary_publications_without_dois(self):
        return iter(secondary_publication for secondary_publication in self.citations
                    if secondary_publication.doi.value is None)

    def update_authors(self, authors):
        """
        Match a set of authors with the current set of authors

        If an author is not found in the current set, it is added to it
        """

        author_match_inds = []
        for self_author in self.authors:
            results = self_author.matches(authors)
            if len(results) == 1:
                ind = results.pop()
                self_author.update(authors[ind])
                author_match_inds.append(ind)

        # add authors not in author_match_inds
        for i in range(len(authors)):
            if i not in author_match_inds:
                self.authors.append(authors[i])

    def update(self, publication: "PersistentPublication") -> None:
        self.update_authors(publication.authors)
        self.year.update(publication.year)
        self.title.update(publication.title)
        self.doi.update(publication.doi)
        self.container_type.update(publication.container_type)
        self.container_name.update(publication.container_name)
        self.abstract.update(publication.abstract)

        if not self.primary:
            if publication.primary:
                self.primary = True
                self.citations = publication.citations

        self.previous_values.extend(publication.previous_values)

    def _match_titles(self, publications: List["PersistentPublication"], publication_matches: Set[int]) -> Set[int]:
        if self.title.value:
            # Determine if titles approximately match
            publication_titles = [publication.title.value for publication in publications]
            title_match_ratios = [fuzz.partial_ratio(self.title.value, publication_title)
                                  for publication_title in publication_titles]
            if 100 in title_match_ratios:
                return {title_match_ratios.index(100)}
            else:
                titles_matches = set(i for (i, result) in enumerate(title_match_ratios) if result >= 90)
                publication_matches.intersection_update(titles_matches)
                return publication_matches
        else:
            return publication_matches

    def _match_years(self, publications: List["PersistentPublication"], publication_matches: Set[int]) -> Set[int]:
        if self.year.value is not None:
            # Determine if years exactly match
            years_matches = set(i for (i, publication) in enumerate(publications)
                                if publication.year.value == self.year.value)
            publication_matches.intersection_update(years_matches)
            return publication_matches

    def _match_author(self, publication: "PersistentPublication") -> bool:
        authors = self.authors
        authors_comp = publication.authors
        for author in authors:
            if not author.matches(authors_comp):
                return False
        return True

    def _match_authors(self, publications: List["PersistentPublication"], publication_matches: Set[int]) -> Set[int]:
        author_matches = set(i for (i, publication) in enumerate(publications)
                             if self._match_author(publication))
        publication_matches.intersection_update(author_matches)
        return publication_matches

    def matches(self, publications: List["PersistentPublication"]) -> Set[int]:
        publication_matches = set(range(len(publications)))
        self._match_years(publications, publication_matches)
        self._match_titles(publications, publication_matches)
        self._match_authors(publications, publication_matches)
        return publication_matches