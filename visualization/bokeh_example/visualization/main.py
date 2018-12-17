import logging
from collections import namedtuple

import pandas as pd
from bokeh.io import curdoc
from bokeh.layouts import row, column, widgetbox, layout
from bokeh.models import TableColumn, DataTable, ColumnDataSource, Paragraph, CheckboxGroup, Legend, Div
from bokeh.palettes import Spectral10
from bokeh.plotting import figure
from django.http import QueryDict

from catalog.core.search_indexes import PublicationDocSearch, normalize_search_querydict
from data_access import data_cache, IncludedStatistics

logger = logging.getLogger(__name__)

Query = namedtuple('Query', ['content_type', 'search', 'filters'])

logger.info('starting')


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


def retrieve_matches():
    s = PublicationDocSearch().find(q=query.search, facet_filters=query.filters).agg_by_count()
    s.execute(facet_filters=query.filters)
    return s.cache[query.content_type]['count']


def create_search_match_table(data_source):
    columns = [
        TableColumn(field='name', title='Name'),
        TableColumn(field='publication_count', title='Publication Match Count'),
    ]
    return DataTable(source=data_source,
                     columns=columns,
                     height=275,
                     width=500)


p = Paragraph(text='Begin')
top_matches_data_source = ColumnDataSource(
    pd.DataFrame.from_records(retrieve_matches(), columns=['id', 'name', 'publication_count']))
match_table = create_search_match_table(top_matches_data_source)

included_statistics_checkbox = CheckboxGroup(labels=IncludedStatistics.labels(),
                                             active=[])


class CodeAvailabilityChart:
    def __init__(self, model_name, indices, statistic_indices):
        self.indices = indices
        self.model_name = model_name
        self.statistic_indices = statistic_indices

    def create_dataset(self):
        df = top_matches_data_source.to_df()
        indices = [self.indices[i] for i in range(min(len(self.indices), len(df.index)))]
        related_ids = top_matches_data_source.to_df().id.iloc[indices].values
        api = data_cache.get_model_data_access_api(self.model_name)
        df = api.get_full_text_matches(query.search, facet_filters=query.filters)
        return api.get_year_related_counts(df=df, related_ids=related_ids)

    def create_view(self, df):
        p = figure(
            tools='pan,wheel_zoom,save',
            title='Publication Counts Over Time',
            plot_width=800)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = 'Year'
        p.yaxis.axis_label = 'Publication Added Count'
        color_mapper = Spectral10
        api = data_cache.get_model_data_access_api(self.model_name)

        name_legend_items = []
        for i, (related_id, dfg) in enumerate(df.groupby('related__id')):
            name = api.get_related_names(related_id)['name']
            r = p.line(
                x=dfg.index.get_level_values('year_published'),
                y=dfg['count'],
                line_width=2,
                color=color_mapper[i])
            name_legend_items.append((name, [r]))
            for statistic_index in self.statistic_indices:
                statistic_name = IncludedStatistics.names()[statistic_index]
                statistic_style = IncludedStatistics.styles()[statistic_index]
                p.line(
                    x=dfg.index.get_level_values('year_published'),
                    y=dfg[statistic_name],
                    line_width=2,
                    color=color_mapper[i],
                    line_dash=statistic_style)
        name_legend = Legend(items=name_legend_items, location='top_left')

        line_style_legend_items = []
        for statistic_index in self.statistic_indices:
            statistic_label = IncludedStatistics.labels()[statistic_index]
            statistic_style = IncludedStatistics.styles()[statistic_index]
            r = p.line(x=[], y=[], line_width=2, color='black', line_dash=statistic_style) # Fake glyphs for rendering styles
            line_style_legend_items.append((statistic_label, [r]))
        line_style_legend = Legend(items=line_style_legend_items, location='top_right')

        p.add_layout(name_legend)
        p.add_layout(line_style_legend)
        return p

    def render(self):
        df = self.create_dataset()
        return self.create_view(df)


page = column(
    row(column(Div(text='<b>Available Statistics</b>'),included_statistics_checkbox), widgetbox(match_table)),
    row(CodeAvailabilityChart(model_name=query.content_type, indices=[0, 1],
                              statistic_indices=[]).render()))


def update_chart():
    logger.info('statistic_indices: %s', included_statistics_checkbox.active)
    page.children[1] = CodeAvailabilityChart(model_name=query.content_type,
                                             indices=top_matches_data_source.selected.indices,
                                             statistic_indices=included_statistics_checkbox.active).render()


def update_table():
    top_matches_data_source.data.update(ColumnDataSource(pd.DataFrame.from_records(
        retrieve_matches())).data)


included_statistics_checkbox.on_change('active', lambda attr, old, new: update_chart())
top_matches_data_source.selected.indices = [0, 1]
top_matches_data_source.selected.on_change('indices', lambda attr, old, new: update_chart())

curdoc().add_root(page)
curdoc().title = 'Visualization of {} for search {}'.format(query.content_type, query.search)
