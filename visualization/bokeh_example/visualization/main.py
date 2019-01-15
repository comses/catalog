import logging

import pandas as pd
from bokeh.io import curdoc
from bokeh.layouts import row, column, widgetbox
from bokeh.models import TableColumn, DataTable, ColumnDataSource, Paragraph, CheckboxGroup, Div
from django.http import QueryDict

import components.publication_counts
import components.publication_counts_over_time
import data_sources.publication_counts_by_content_type
import data_sources.top_matches_by_content_type
import data_sources.publication_counts

from catalog.core.search_indexes import PublicationDocSearch, normalize_search_querydict
from data_access import IncludedStatistics
from query import Query

logger = logging.getLogger(__name__)


def bokeh_arguments_to_query_dict(arguments: dict) -> QueryDict:
    qd = QueryDict(mutable=True)
    for k, v in arguments.items():
        for el in v:
            qd[k] = el
    return qd


def extract_query():
    doc = curdoc()
    args = doc.session_context.request.arguments if doc and doc.session_context else {}
    qd = bokeh_arguments_to_query_dict(args)
    logger.info('args: %s', args)
    logger.info('qd: %s', qd)
    search, filters = normalize_search_querydict(qd)
    content_type_arg = args.get('content_type')
    content_type = content_type_arg[0].decode() if content_type_arg else 'sponsors'
    query = Query(content_type=content_type, search=search, filters=filters)
    return query


query = extract_query()

logger.info('extracted query: {}'.format(query.content_type))

included_statistics_checkbox = CheckboxGroup(labels=IncludedStatistics.labels(),
                                             active=[])

#
# General
#

publication_counts_df = data_sources.publication_counts.create_publication_counts_dataset(query)
publication_count_graph = components.publication_counts.create_chart(
    statistic_indices=included_statistics_checkbox.active, publication_count_df=publication_counts_df)


def update_chart():
    page.children[1] = components.publication_counts.create_chart(
        statistic_indices=included_statistics_checkbox.active, publication_count_df=publication_counts_df)


included_statistics_checkbox.on_change('active', lambda attr, old, new: update_chart())


#
# Content Type Section
#

def create_search_match_table(data_source):
    columns = [
        TableColumn(field='name', title='Name'),
        TableColumn(field='publication_count', title='Publication Match Count'),
    ]
    return DataTable(source=data_source,
                     columns=columns,
                     height=275,
                     width=500)


top_matches_data_source = data_sources.top_matches_by_content_type.create_data_source(query)
top_matches_data_source.selected.indices = [0, 1]

match_table = create_search_match_table(top_matches_data_source)

publication_counts_by_content_type_over_time_df = data_sources.publication_counts_by_content_type.create_dataset(
    query,
    top_matches_df=match_table.source.to_df(),
    top_matches_selected_indices=match_table.source.selected.indices)

publication_count_by_content_type_graph = components.publication_counts_over_time.create_chart(
    query,
    publication_count_df=publication_counts_by_content_type_over_time_df,
    statistic_indices=[])


def update_content_type_chart():
    logger.info('statistic_indices: %s', included_statistics_checkbox.active)
    publication_counts_over_time_df = data_sources.publication_counts_by_content_type.create_dataset(
        query,
        top_matches_df=top_matches_data_source.to_df(),
        top_matches_selected_indices=top_matches_data_source.selected.indices)
    page.children[2] = components.publication_counts_over_time.create_chart(
        query,
        publication_count_df=publication_counts_over_time_df,
        statistic_indices=included_statistics_checkbox.active)


included_statistics_checkbox.on_change('active', lambda attr, old, new: update_content_type_chart())
top_matches_data_source.selected.on_change('indices', lambda attr, old, new: update_content_type_chart())

#
# Page Layout
#

page = column(
    row(column(Div(text='<b>Available Statistics</b>'), included_statistics_checkbox), widgetbox(match_table)),
    row(publication_count_graph),
    # Plot publication creation count over time (overall and for search results only)
    # Table of summary statistics
    row(publication_count_by_content_type_graph))

curdoc().add_root(page)
curdoc().title = 'Visualization of {} for search {}'.format(query.content_type, query.search)
