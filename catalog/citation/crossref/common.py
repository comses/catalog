from .. import publications as pub
from typing import Dict


def get_message(response_json):
    return response_json["message"]


def get_author(item_json: Dict):
    family = item_json.get("family")
    given = item_json.get("given")
    return pub.make_author(family=family,
                           given=given,
                           previous=(pub.DataSource.crossref_doi_success, str(item_json)))


def get_authors(response_json: Dict):
    authors_json = response_json.get("author", [])
    authors = [get_author(author_json) for author_json in authors_json]
    return authors


def get_year(item_json):
    return pub.Persistent(item_json \
                          .get("issued", {"date-parts": [[None]]}) \
                          .get("date-parts", [[None]])[0][0])


def get_title(item_json):
    #print(item_json.get("title"))
    title = None
    title_list = item_json.get("title")
    if title_list:
        title = title_list[0]
    return pub.Persistent(title)


def get_doi(item_json):
    return pub.Persistent(item_json.get("DOI"))


def get_container_type(item_json):
    return pub.Persistent(item_json.get("type"))


def get_container_name(item_json):
    container_title = None
    container_title_list = item_json.get("container-title")
    if container_title_list:
        container_title = container_title_list[0]
    return pub.Persistent(container_title)
