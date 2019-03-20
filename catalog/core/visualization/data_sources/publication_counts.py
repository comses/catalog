import logging

import pandas as pd

from catalog.core.search_indexes import PublicationDocSearch
from ..data_access import data_cache, IncludedStatistics
from query import Query

logger = logging.getLogger(__name__)


def _create_count_dataframe(df):
    return df.groupby(['year_published']) \
        .agg(dict(title='count', is_archived='sum', has_formal_description='sum',
                  has_odd='sum', has_visual_documentation='sum')) \
        .rename(columns={
        'title': 'count',
        'is_archived': IncludedStatistics.code_availability_count.name,
        'has_formal_description': IncludedStatistics.formal_description_count.name,
        'has_odd': IncludedStatistics.odd_count.name,
        'has_visual_documentation': IncludedStatistics.visual_documentation_count.name
    }).reindex(pd.RangeIndex(start=1995, stop=2018, name='year_published'), fill_value=0.0)


def create_publication_counts_dataset(query: Query):
    publication_ids = [p.id for p in
                       PublicationDocSearch().find(q=query.search, facet_filters=query.filters).source(['id']).scan()]
    publication_matches = data_cache.publications.loc[publication_ids]
    publication_match_counts = _create_count_dataframe(publication_matches).assign(group='matched')
    all_publication_counts = _create_count_dataframe(data_cache.publications).assign(group='all')
    return pd.concat([publication_match_counts, all_publication_counts])