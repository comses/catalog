from .. import models, util
from django.contrib.auth.models import User

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


            container, container_alias = update_container(
                audit_command=self.audit_command,
                detached_container=self.container,
                detached_container_alias=self.container_alias,
                existing_container=publication.journal)

            publication.journal = container
            update_publication(publication, self.publication, self.audit_command)

            self.raw.publication = publication
            self.raw.container_alias = container_alias
            self.raw.save()

            for (author, author_alias) in self.authors_author_alias_pairs:
                author.log_save(self.audit_command)
                author_alias.author = author
                author_alias.log_save(self.audit_command)

                models.AuthorAliasRaws.objects.log_create(
                    self.audit_command,
                    payload={'author_alias_id': author_alias.id, 'raw_id': self.raw.id})


def update_container(existing_container: Optional[models.Container],
                     detached_container: models.Container,
                     detached_container_alias: models.ContainerAlias,
                     audit_command: models.AuditCommand):
    if existing_container:
        if existing_container.issn == '':
            existing_container.issn = detached_container.issn
    else:
        existing_container = detached_container

    existing_container.log_save(audit_command)
    container_alias, created = models.ContainerAlias.objects.log_get_or_create(
        audit_command,
        payload={'container_id': existing_container.id, 'name': detached_container_alias.name},
        name=detached_container_alias.name,
        container_id=existing_container.id)

    return existing_container, container_alias


def update_publication(
        existing_publication: models.Publication,
        detached_publication: models.Publication,
        audit_command: models.AuditCommand):
    payload = {}
    if existing_publication.date_published_text is None:
        existing_publication.date_published_text = detached_publication.date_published_text
        payload["date_published_text"] = detached_publication.date_published_text
    if not existing_publication.title:
        existing_publication.title = detached_publication.title
        payload["title"] = detached_publication.title
    if not existing_publication.doi:
        existing_publication.doi = detached_publication.doi
        payload["doi"] = detached_publication.doi
    if not existing_publication.abstract:
        existing_publication.abstract = detached_publication.abstract
        payload["abstract"] = detached_publication.abstract

    existing_publication.log_save(audit_command=audit_command)


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
