import requests
from typing import Dict
from .. import common

from ... import models


def process(publication: models.Publication, response_json: Dict, key: str, value: Dict):
    raw = models.Raw.objects.create(key=key, value=value, publication=publication)
    if response_json:
        item_json = common.get_message(response_json)
        new_raw_publication = models.PublicationRaw(
            title=common.get_title(item_json),
            year=common.get_year(item_json),
            doi=common.get_doi(item_json),
            primary=False,
            raw=raw)
        raw_authors = common.make_authors_raw(new_raw_publication, item_json, create=False)
        raw_container = common.make_container_raw(new_raw_publication, item_json, create=False)

        detached_publication = common.DetachedPublication(publication_raw=new_raw_publication,
                                                          authors_raw=raw_authors,
                                                          container_raw=raw_container,
                                                          raw=raw)
        detached_publication.attach_to(publication.id, None)
    else:
        new_raw_publication = None
    return new_raw_publication


def update(publication: models.Publication):
    url = "http://api.crossref.org/works/{}".format(publication.doi)
    try:
        response = requests.get(url, timeout=10)
        value = common.ResponseDictEncoder().encode(response)
        if response.status_code == 200:
            response_json = response.json()
            key = models.Raw.CROSSREF_DOI_SUCCESS
            return process(publication, response_json, key, value)
        else:
            key = models.Raw.CROSSREF_DOI_FAIL
            return process(publication, {}, key, value)
    except requests.Timeout:
        value = {"url": url, "reason": "TIMEOUT"}
        key = models.Raw.CROSSREF_DOI_FAIL
        return process(publication, {}, key, value)
