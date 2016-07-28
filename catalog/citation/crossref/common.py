from .. import models, util

import json
import requests
from typing import Dict, List, Optional, Tuple
from django.db import transaction


class ResponseDictEncoder:
    def encode(self, o):
        if isinstance(o, requests.Response):
            is_json = True
            try:
                content = o.json()
            except json.decoder.JSONDecodeError:
                content = o.content.decode('utf-8')
                is_json = False
            return {
                "url": o.url,
                "status_code": o.status_code,
                "reason": o.reason,
                "headers": dict(o.headers),
                "encoding": o.encoding,
                "is_json": is_json,
                "content": content
            }


class DetachedPublication:
    def __init__(self,
                 publication: models.Publication,
                 author_author_alias_pairs: List[Tuple[models.Author, models.AuthorAlias]],
                 container_container_alias_pair: Tuple[models.Container, models.ContainerAlias],
                 raw: models.Raw,
                 audit_command: models.AuditCommand):

        # these must not be saved in the database
        self.publication = publication
        self.container = container_container_alias_pair[0]
        self.container_alias = container_container_alias_pair[1]
        self.authors_author_alias_pairs = author_author_alias_pairs
        self.raw = raw

        # audit command must already be saved in the database
        self.audit_command = audit_command

    def attach_to(self, publication_id: int, match: Optional[int]):
        with transaction.atomic():
            publication = models.Publication.objects.get(id=publication_id)
            if match is not None:
                self.raw.value["match_ids"] = [match]
            self.raw.save()

            self.container.log_save(self.audit_command)
            self.container_alias.container = self.container
            self.container_alias.log_save(self.audit_command)
            self.container_alias.raw.add(self.raw)

            self.publication.journal = self.container
            self.publication.save()
            self.publication.raw.add(self.raw)

            for (author, author_alias) in self.authors_author_alias_pairs:
                author.save()
                author_alias.author = author
                author_alias.save()

                self.publication.authors.add(author)

                author.raw_id = self.raw.id
                author.author_alias = author_alias
                author.save()

            update_publication(publication, self.publication, self.audit_command)


def update_publication(
        publication: models.Publication,
        detached_publication: models.Publication,
        audit_command: models.AuditCommand):
    payload = {}
    if publication.year is None:
        publication.year = detached_publication.year
        payload["year"] = detached_publication.year
    if not publication.title:
        publication.title = detached_publication.title
        payload["title"] = detached_publication.title
    if not publication.doi:
        publication.doi = detached_publication.doi
        payload["doi"] = detached_publication.doi
    if not publication.abstract:
        publication.abstract = detached_publication.abstract
        payload["abstract"] = detached_publication.abstract

    publication.log_save(audit_command=audit_command)


def get_message(response_json):
    return response_json["message"]


def make_author_author_alias_pair(publication: models.Publication, item_json: Dict,
                                  create) -> models.Author:
    family = item_json.get("family")
    given = item_json.get("given")
    orcid = item_json.get("ORCID", "")
    if family is None:
        name = given or ""
    elif given is None:
        name = family
    else:
        name = "{}, {}".format(family, given)

    author = models.Author(type=models.Author.INDIVIDUAL,
                           orcid=orcid)
    author_alias = models.AuthorAlias(author=author,
                                      name=util.last_name_and_initials(name))

    if create:
        author.save()
        author_alias.author = author
        author_alias.save()
    return author, author_alias


def make_author_author_alias_pairs(publication_raw, response_json: Dict, create) -> List[models.Author]:
    authors_json = response_json.get("author", [])
    if not authors_json:
        authors_json = response_json.get("editor", [])
    author_author_alias_pairs = [make_author_author_alias_pair(publication_raw, author_json, create) for author_json in authors_json]
    return author_author_alias_pairs


def get_year(item_json):
    return item_json \
        .get("issued", {"date-parts": [[None]]}) \
        .get("date-parts", [[None]])[0][0]


def get_title(item_json):
    title = ""
    title_list = item_json.get("title")
    if title_list:
        title = title_list[0]
    return title


def get_doi(item_json):
    return item_json.get("DOI", "")


def get_container_type(item_json):
    return item_json.get("type", "")


def get_container_name(item_json):
    container_title = ""
    container_title_list = item_json.get("container-title")
    if container_title_list:
        container_title = container_title_list[0]
    return container_title


def make_container_container_alias_pair(publication_raw: models.Publication, item_json, create):
    container_name = get_container_name(item_json)
    container_type = get_container_type(item_json)

    container = models.Container(type=container_type)
    container_alias = models.ContainerAlias(name=container_name)

    if create:
        container.save()
        container_alias.container = container
        container_alias.save()
    return container, container_alias


# def fix_raw_authors():
#     n = models.RawAuthor.objects.select_related('raw__publication').filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], author_alias__isnull=True).count()
#     print("Fixing Authors")
#     for (i, raw_author) in enumerate(models.RawAuthor.objects.select_related('raw__publication').filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], author_alias__isnull=True).iterator()):
#         print("{}/{} Name: {}, ORCID: {}".format(i, n, raw_author.name, raw_author.orcid))
#         publication = raw_author.raw.publication
#         author = models.Author.objects.create(type=raw_author.type, orcid=raw_author.orcid)
#         publication.authors.add(author)
#         author_alias = models.AuthorAlias.objects.create(author=author, name=raw_author.name)
#         models.RawAuthor.objects.filter(raw_id=raw_author.id).update(author_alias=author_alias)
#
#
# def fix_raw_containers():
#     print("Fixing Containers")
#     n = models.ContainerRaw.objects.filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], container_alias__isnull=True).order_by('name').count()
#     for (i, raw_container) in enumerate(models.ContainerRaw.objects.filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], container_alias__isnull=True).order_by('name').iterator()):
#         print("{}/{} Name: {}, ISSN: {}".format(i, n, raw_container.name, raw_container.issn))
#         publication = raw_container.raw.publication
#         container = publication.container
#         if container is None:
#             container = models.Container.objects.create(issn=raw_container.issn)
#             publication.container = container
#             publication.save()
#         elif container.issn == '' and raw_container.issn != '':
#             container.issn = raw_container.issn
#             container.save()
#         container_alias, created = models.ContainerAlias.objects.get_or_create(container=container, name=raw_container.name)
#         raw_container.container_alias = container_alias
#         raw_container.save()