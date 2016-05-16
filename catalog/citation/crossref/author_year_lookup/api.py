from ... import publications as pub
from .. import common

import requests
from typing import Dict, List, Optional, Set


def process_item(item: Dict, response: requests.Response) -> pub.PersistentPublication:
    return pub.PersistentPublication(
        authors=common.get_authors(item),
        year=common.get_year(item),
        title=common.get_title(item),
        doi=common.get_doi(item),
        container_type=common.get_container_type(item),
        container_name=common.get_container_name(item),
        abstract=pub.Persistent(None),
        citations=[],
        primary=False,
        previous=(pub.DataSource.crossref_search_found, response))


def process(publication: pub.PersistentPublication, response: requests.Response) -> List[pub.PersistentPublication]:
    if response.status_code == 200:
        response_json = response.json()
        response_items = response_json.get("message", {"items": []}).get("items", [])
        publications = [process_item(item, response) for item in response_items]
        match = publication.matches(publications)
        if len(match) == 1:
            publication.update(publications[match.pop()])
        else:
            publication.previous_values.append((pub.DataSource.crossref_search_notfound, (response, match)))
    else:
        publication.previous_values.append((pub.DataSource.crossref_search_failed, response))


def update(publication: pub.PersistentPublication):
    author_str = ", ".join([author.fullname for author in publication.authors])
    year = publication.year.value
    if year is not None and author_str:
        response = requests.get("http://api.crossref.org/works?query={}, {}".format(author_str, year))
        process(publication, response)

    return publication
