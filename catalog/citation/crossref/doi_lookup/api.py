import requests
from typing import Dict
from .. import common

from ... import publications as pub


def process(response_json):
    item_json = common.get_message(response_json)
    return pub.PersistentPublication(
        authors=common.get_authors(item_json),
        year=common.get_year(item_json),
        title=common.get_title(item_json),
        doi=common.get_doi(item_json),
        container_type=common.get_container_type(item_json),
        container_name=common.get_container_name(item_json),
        abstract=pub.Persistent(None),
        citations=[],
        primary=False,
        previous=(pub.DataSource.crossref_doi_success, item_json))


def update(publication: pub.PersistentPublication):
    response = requests.get("http://api.crossref.org/works/{}".format(publication.doi.value), timeout=10)
    if response.status_code == 200:
        response_json = response.json()
        crossref_publication = process(response_json)
        publication.update(crossref_publication)
        return publication
    else:
        publication.previous_values.append((pub.DataSource.crossref_doi_invalid, response))