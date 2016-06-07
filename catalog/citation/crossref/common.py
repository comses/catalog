from .. import models, util

import json
import requests
from typing import Dict, List, Optional
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
                 publication_raw: models.PublicationRaw,
                 authors_raw: List[models.AuthorRaw],
                 container_raw: models.ContainerRaw,
                 raw: models.Raw):
        self.publication_raw = publication_raw
        self.authors_raw = authors_raw
        self.container_raw = container_raw
        self.raw = raw

    def attach_to(self, publication_id: int, match: Optional[int]):
        self.raw.publication_id = publication_id
        if match is not None:
            self.raw.value["match_ids"] = [match]
        self.raw.save()
        self.publication_raw.raw_id = self.raw.id
        self.publication_raw.save()

        publication = models.Publication.objects.get(id=publication_id)
        for author_raw in self.authors_raw:
            author = models.Author.objects.create(type=author_raw.type, orcid=author_raw.orcid)
            publication.authors.add(author)

            author_alias = models.AuthorAlias.objects.create(author=author, name=author_raw.name)
            author_raw.publication_raw_id = self.publication_raw.raw_id
            author_raw.raw_id = self.raw.id
            author_raw.author_alias = author_alias
            author_raw.save()

        container = publication.container
        if container is None:
            container = models.Container.objects.create(issn=self.container_raw.issn)
            publication.container = container
            publication.save()
        container_alias = models.ContainerAlias.objects.create(container=container, name=self.container_raw.name)

        self.container_raw.publication_raw_id = self.publication_raw.raw_id
        self.container_raw.raw_id = self.raw.id
        self.container_raw.container_alias = container_alias
        self.container_raw.save()

        update_publication(publication, self.publication_raw)


def update_publication(publication: models.Publication,
                       raw_publication: models.PublicationRaw):
    if publication.year is None:
        publication.year = raw_publication.year
    if not publication.title:
        publication.title = raw_publication.title
    if not publication.doi:
        publication.doi = raw_publication.doi
    if not publication.abstract:
        publication.abstract = raw_publication.abstract
    publication.save()


def get_message(response_json):
    return response_json["message"]


def make_author_raw(publication_raw: models.PublicationRaw, item_json: Dict,
                    create) -> models.AuthorRaw:
    family = item_json.get("family")
    given = item_json.get("given")
    orcid = item_json.get("ORCID", "")
    if family is None:
        name = given or ""
    elif given is None:
        name = family
    else:
        name = "{}, {}".format(family, given)

    author_raw = models.AuthorRaw(publication_raw=publication_raw,
                                  raw_id=publication_raw.raw_id,
                                  name=util.last_name_and_initials(name),
                                  type=models.Author.INDIVIDUAL,
                                  orcid=orcid)
    if create:
        # author = models.Author.objects.create(type=models.AuthorRaw.INDIVIDUAL,
        #                                       orcid=orcid)
        # author_alias = models.AuthorAlias.objects.create(author=author,
        #                                                  name=util.last_name_and_initials(name))
        # author_raw.author_alias = author_alias
        author_raw.save()
    return author_raw


def make_authors_raw(publication_raw, response_json: Dict, create) -> List[models.AuthorRaw]:
    authors_json = response_json.get("author", [])
    if not authors_json:
        authors_json = response_json.get("editor", [])
    authors_raw = [make_author_raw(publication_raw, author_json, create) for author_json in authors_json]
    return authors_raw


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


def make_container_raw(publication_raw: models.PublicationRaw, item_json, create):
    container_name = get_container_name(item_json)
    container_type = get_container_type(item_json)

    container_raw = models.ContainerRaw(publication_raw=publication_raw,
                                        raw_id=publication_raw.raw_id,
                                        name=container_name,
                                        type=container_type)
    if create:
        container_raw.save()
    return container_raw


def fix_raw_authors():
    n = models.AuthorRaw.objects.select_related('raw__publication').filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], author_alias__isnull=True).count()
    print("Fixing Authors")
    for (i, raw_author) in enumerate(models.AuthorRaw.objects.select_related('raw__publication').filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], author_alias__isnull=True).iterator()):
        print("{}/{} Name: {}, ORCID: {}".format(i, n, raw_author.name, raw_author.orcid))
        publication = raw_author.raw.publication
        author = models.Author.objects.create(type=raw_author.type, orcid=raw_author.orcid)
        publication.authors.add(author)
        author_alias = models.AuthorAlias.objects.create(author=author, name=raw_author.name)
        models.AuthorRaw.objects.filter(raw_id=raw_author.id).update(author_alias=author_alias)


def fix_raw_containers():
    print("Fixing Containers")
    n = models.ContainerRaw.objects.filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], container_alias__isnull=True).order_by('name').count()
    for (i, raw_container) in enumerate(models.ContainerRaw.objects.filter(raw__key__in=[models.Raw.CROSSREF_DOI_FAIL, models.Raw.CROSSREF_DOI_SUCCESS], container_alias__isnull=True).order_by('name').iterator()):
        print("{}/{} Name: {}, ISSN: {}".format(i, n, raw_container.name, raw_container.issn))
        publication = raw_container.raw.publication
        container = publication.container
        if container is None:
            container = models.Container.objects.create(issn=raw_container.issn)
            publication.container = container
            publication.save()
        elif container.issn == '' and raw_container.issn != '':
            container.issn = raw_container.issn
            container.save()
        container_alias, created = models.ContainerAlias.objects.get_or_create(container=container, name=raw_container.name)
        raw_container.container_alias = container_alias
        raw_container.save()