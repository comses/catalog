import re


def sanitize_doi(s):
    if s:
        s = re.sub("\{|\}", "", s)
        s = s.lower()
    return s


def sanitize_name(s):
    if s:
        s = re.sub("\n", " ", s)
        s = re.sub("\\\\", "", s)
    return s
