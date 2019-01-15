from django.http import QueryDict

from catalog.core.search_indexes import normalize_search_querydict


class Query:
    def __init__(self, content_type, search, filters):
        self.content_type = content_type
        self.filters = filters
        self.search = search

    @classmethod
    def empty(cls, content_type='sponsors'):
        search, filters = normalize_search_querydict(QueryDict())
        return cls(content_type=content_type, search=search, filters=filters)
