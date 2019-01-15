import pandas as pd
from bokeh.models import ColumnDataSource

from catalog.core.search_indexes import PublicationDocSearch


def _retrieve_matches(query):
    s = PublicationDocSearch().find(q=query.search, facet_filters=query.filters).agg_by_count()
    s.execute(facet_filters=query.filters)
    return s.cache[query.content_type]['count']


def create_data_source(query):
    matches = _retrieve_matches(query)
    return ColumnDataSource(
        pd.DataFrame.from_records(matches, columns=['id', 'name', 'publication_count']))