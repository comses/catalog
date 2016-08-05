import re
from typing import Dict
import copy
from unidecode import unidecode

def sanitize_doi(s):
    if s:
        s = re.sub("\{|\}", "", s)
        s = s.lower()
    return s


def sanitize_name(s):
    if s:
        s = re.sub("\{''\}|``", "\"", s)
        s = re.sub("\n", " ", s)
        s = re.sub("\\\\", "", s)
    return s


def normalize_name(name: str, strip_unicode=True) -> str:
    normalized_name = name.upper()
    normalized_name = re.sub(r"\n|\r", " ", normalized_name)
    normalized_name = re.sub(r"\.|,|\{|\}", "", normalized_name)
    if strip_unicode:
        normalized_name = unidecode(normalized_name).strip()
    else:
        normalized_name = normalized_name.strip()
    return normalized_name


def all_initials(given_names):
    return all(len(given_name) == 1 and given_name == given_name.upper()
               for given_name in given_names)


def last_name_and_initials(name: str) -> str:
    normalized_name = normalize_name(name)
    name_split = re.split(r"\b,? +\b", normalized_name)
    family = name_split[0]
    given_names = name_split[1:] if len(name_split) > 1 else []
    if all_initials(given_names):
        given = "".join(given_names)
    elif len(given_names) > 1 and any(len(given_name) > 1 for given_name in given_names):
        given = "".join(given_name[0] for given_name in given_names)
    else:
        given = " ".join(given_names)

    if given is not None:
        return family, given
    else:
        return normalized_name, ''


def last_name_and_initial(normalized_name: str) -> str:
    name_split = re.split(r"\b,? +\b", normalized_name)
    family = name_split[0]
    given_names = name_split[1:] if len(name_split) > 1 else []
    if all_initials(given_names):
        given = given_names[0][0]
    elif len(given_names) > 0 and len(given_names[0]) > 1:
        given = given_names[0][0]
    else:
        given = None

    if given is not None:
        return "{} {}".format(family, given)
    else:
        return normalized_name