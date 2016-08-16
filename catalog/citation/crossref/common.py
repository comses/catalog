from .. import models, util
from django.contrib.auth.models import User
from unidecode import unidecode

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
                existing_container=publication.container)

            publication.container = container
            update_publication(publication, self.publication, self.audit_command)

            self.raw.publication = publication
            self.raw.container = container
            self.raw.save()

            for (author, author_alias) in self.authors_author_alias_pairs:
                author_db = models.Author.objects.log_create(audit_command=self.audit_command,
                                                             given_name=author.given_name,
                                                             family_name=author.family_name,
                                                             orcid=author.orcid,
                                                             email=author.email)
                author_alias_db = models.AuthorAlias.objects.log_create(audit_command=self.audit_command,
                                                                        given_name=author_alias.given_name,
                                                                        family_name=author_alias.family_name,
                                                                        author_id=author_db.id)

                models.RawAuthors.objects.log_create(
                    self.audit_command,
                    author_id=author_db.id, raw_id=self.raw.id)


def update_container(existing_container: Optional[models.Container],
                     detached_container: models.Container,
                     detached_container_alias: models.ContainerAlias,
                     audit_command: models.AuditCommand):
    if existing_container:
        if existing_container.issn == '' and detached_container.issn != '':
            existing_container.log_update(audit_command=audit_command, issn=detached_container.issn)
        container = existing_container
    else:
        container = models.Container.objects.log_create(audit_command=audit_command,
                                                        name=detached_container.name,
                                                        issn=detached_container.issn,
                                                        type=detached_container.type)

    container_alias, created = models.ContainerAlias.objects.log_get_or_create(
        audit_command,
        name=detached_container_alias.name,
        container_id=container.id)

    return container, container_alias


def update_publication(
        existing_publication: models.Publication,
        detached_publication: models.Publication,
        audit_command: models.AuditCommand):
    changes = {}
    if existing_publication.date_published_text is None:
        existing_publication.date_published_text = detached_publication.date_published_text
        changes["date_published_text"] = detached_publication.date_published_text
    if not existing_publication.title:
        existing_publication.title = detached_publication.title
        changes["title"] = detached_publication.title
    if not existing_publication.doi:
        existing_publication.doi = detached_publication.doi
        changes["doi"] = detached_publication.doi
    if not existing_publication.abstract:
        existing_publication.abstract = detached_publication.abstract
        changes["abstract"] = detached_publication.abstract

    existing_publication.log_update(audit_command=audit_command, **changes)


def get_message(response_json):
    return response_json["message"]


def make_author_author_alias_pair(publication: models.Publication, item_json: Dict,
                                  create) -> models.Author:
    family = unidecode(item_json.get("family").upper())
    given = unidecode(item_json.get("given").upper())
    orcid = item_json.get("ORCID", "")

    author = models.Author(type=models.Author.INDIVIDUAL,
                           orcid=orcid,
                           given_name=given,
                           family_name=family)
    author_alias = models.AuthorAlias(author=author,
                                      given_name=given,
                                      family_name=family)

    if create:
        author.save()
        author_alias.author = author
        author_alias.save()
    return author, author_alias


def make_author_author_alias_pairs(publication_raw, response_json: Dict, create) -> List[models.Author]:
    authors_json = response_json.get("author", [])
    if not authors_json:
        authors_json = response_json.get("editor", [])
    author_author_alias_pairs = [make_author_author_alias_pair(publication_raw, author_json, create) for author_json in
                                 authors_json]
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

    container = models.Container(type=container_type, name=container_name)
    container_alias = models.ContainerAlias(name=container_name)

    if create:
        container.save()
        container_alias.container = container
        container_alias.save()
    return container, container_alias
