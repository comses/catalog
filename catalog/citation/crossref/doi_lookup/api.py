import requests
from typing import Dict
from .. import common

from ... import models


def process(publication: models.Publication, response_json: Dict, key: str, value: Dict, audit_command: models.AuditCommand):
    raw = models.Raw.objects.create(key=key, value=value, data_source=audit_command, publication=publication)
    if response_json:
        item_json = common.get_message(response_json)
        new_raw_publication = models.Publication(
            title=common.get_title(item_json),
            year=common.get_year(item_json),
            doi=common.get_doi(item_json),
            primary=False)
        author_author_alias_pairs = common.make_author_author_alias_pairs(new_raw_publication, item_json, create=False)
        container_container_alias_pair = common.make_container_container_alias_pair(new_raw_publication, item_json, create=False)

        detached_publication = common.DetachedPublication(publication=new_raw_publication,
                                                          author_author_alias_pairs=author_author_alias_pairs,
                                                          container_container_alias_pair=container_container_alias_pair,
                                                          raw=raw,
                                                          audit_command=audit_command)
        detached_publication.attach_to(publication.id, None)
    else:
        new_raw_publication = None
    return new_raw_publication


def update(publication: models.Publication, audit_command: models.AuditCommand):
    url = "http://api.crossref.org/works/{}".format(publication.doi)
    try:
        response = requests.get(url, timeout=10)
        value = common.ResponseDictEncoder().encode(response)
        if response.status_code == 200:
            response_json = response.json()
            key = models.Raw.CROSSREF_DOI_SUCCESS
            return process(publication, response_json, key, value, audit_command)
        else:
            key = models.Raw.CROSSREF_DOI_FAIL
            return process(publication, {}, key, value, audit_command)
    except requests.Timeout:
        value = {"url": url, "reason": "TIMEOUT"}
        key = models.Raw.CROSSREF_DOI_FAIL
        return process(publication, {}, key, value, audit_command)
