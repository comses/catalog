import requests
from typing import Dict
from django.contrib.auth.models import User

from .. import common
from ... import models


def process(publication: models.Publication, response_json: Dict, key: str, value: Dict, audit_command: models.AuditCommand):
    raw = models.Raw(key=key, value=value)
    if response_json:
        item_json = common.get_message(response_json)
        new_publication = models.Publication(
            title=common.get_title(item_json),
            date_published_text=str(common.get_year(item_json)),
            doi=common.get_doi(item_json),
            is_primary=False,
            added_by=audit_command.creator)
        author_author_alias_pairs = common.make_author_author_alias_pairs(new_publication, item_json, create=False)
        container_container_alias_pair = common.make_container_container_alias_pair(new_publication, item_json, create=False)

        detached_publication = common.DetachedPublication(publication=new_publication,
                                                          author_author_alias_pairs=author_author_alias_pairs,
                                                          container_container_alias_pair=container_container_alias_pair,
                                                          raw=raw,
                                                          audit_command=audit_command)
        detached_publication.attach_to(publication.id, None)
    return publication


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


def augment_publications(user: User, limit=None):
    """
    Add missing information with CrossRef DOI search

    Precondition: publications DOIs have been deduped
    """

    sql = \
        """
        SELECT pubs.id, doi
        FROM citation_publication AS pubs
        WHERE doi <> '' AND (title = '' OR abstract = '' OR pubs.date_published_text = '')
        ORDER BY id"""

    if isinstance(limit, int) and 1 <= limit:
        sql += "\nLIMIT {};".format(limit)
    else:
        sql += ";"

    publications = models.Publication.objects.raw(sql)

    for (ind, publication) in enumerate(publications):
        audit_command = models.AuditCommand.objects.create(
            creator=user, action="augment with crossref doi lookup")
        print("{} {}".format(ind, str(publication)))
        other_publication = update(publication, audit_command)
        if isinstance(other_publication, models.Publication):
            print("{} {}".format(ind, str(other_publication)))
        else:
            print("\t{} {}".format(ind, other_publication))