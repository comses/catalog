import logging
from collections import namedtuple

import pandas as pd
from bokeh.io import curdoc
from bokeh.layouts import row, column
from bokeh.models import TableColumn, DataTable, ColumnDataSource, Paragraph
from bokeh.palettes import Spectral10
from bokeh.plotting import figure

from catalog.core.search_indexes import PublicationDocSearch
from data_access import data_cache

logger = logging.getLogger(__name__)

Query = namedtuple('Query', ['content_type', 'search'])

logger.info('starting')


def extract_query():
    doc = curdoc()
    args = doc.session_context.request.arguments if doc and doc.session_context else {}
    logger.info(args)
    content_type_arg = args.get('content_type')
    content_type = content_type_arg[0].decode() if content_type_arg else 'sponsors'
    search_arg = args.get('q')

    search = search_arg[0].decode() if search_arg else ''
    query = Query(content_type=content_type, search=search)
    return query


query = extract_query()

logger.info('extracted query: {}'.format(query.content_type))


def retrieve_matches(search, content_type):
    s = PublicationDocSearch().find(q=search, field_name_to_ids={}).agg_by_count()
    response = s.execute(filters={})
    return s.cache[content_type]['count']


def create_search_match_table(data_source):
    columns = [
        TableColumn(field='name', title='Name'),
        TableColumn(field='publication_count', title='Publication Match Count'),
    ]
    return DataTable(source=data_source,
                     columns=columns)


p = Paragraph(text='Begin')
top_matches_data_source = ColumnDataSource(
    pd.DataFrame.from_records(retrieve_matches(search=query.search, content_type=query.content_type)))
match_table = create_search_match_table(top_matches_data_source)


class CodeAvailabilityChart:
    def __init__(self, search, model_name, indices):
        self.search = search
        self.indices = indices
        self.model_name = model_name

    def create_dataset(self):
        related_ids = top_matches_data_source.to_df().id.iloc[self.indices].values
        api = data_cache.get_model_data_access_api(self.model_name)
        df = api.get_full_text_matches(self.search)
        return api.get_year_related_counts(df=df, related_ids=related_ids)

    def create_view(self, df):
        p = figure(
            tools='pan,wheel_zoom,save',
            title='Code Availability Over Time',
            plot_width=800)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = 'Year'
        p.yaxis.axis_label = 'Publication Added Count'
        color_mapper = Spectral10
        api = data_cache.get_model_data_access_api(self.model_name)
        for i, (related_id, dfg) in enumerate(df.groupby('related__id')):
            name = api.get_related_names(related_id)['name']
            p.line(
                x=dfg.index.get_level_values('year_published'),
                y=dfg['count'],
                legend=name,
                line_width=2,
                color=color_mapper[i])
            p.line(
                x=dfg.index.get_level_values('year_published'),
                y=dfg['archived_count'],
                legend='{} (Code Available)'.format(name),
                line_width=2,
                color=color_mapper[i],
                line_dash='dashed')
        return p

    def render(self):
        df = self.create_dataset()
        return self.create_view(df)


page = column(
    row(CodeAvailabilityChart(search=query.search, model_name=query.content_type, indices=[0, 1]).render()),
    row(match_table))


def update_chart():
    page.children[0] = CodeAvailabilityChart(search=query.search, model_name=query.content_type,
                                             indices=top_matches_data_source.selected.indices).render()


def update_table():
    top_matches_data_source.data.update(ColumnDataSource(pd.DataFrame.from_records(
        retrieve_matches(search=query.search, content_type=query.content_type))).data)


top_matches_data_source.selected.on_change('indices', lambda attr, old, new: update_chart())

curdoc().add_root(page)
curdoc().title = 'Visualization of {} for search {}'.format(query.content_type, query.search)
