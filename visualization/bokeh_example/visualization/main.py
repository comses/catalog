import logging
from collections import namedtuple

import pandas as pd
from bokeh.io import curdoc
from bokeh.layouts import widgetbox, layout
from bokeh.models import TextInput, TableColumn, DataTable, ColumnDataSource, Paragraph
from bokeh.models.widgets import Select
from bokeh.plotting import figure
from django.db.models import QuerySet
from django_pandas.io import read_frame

from catalog.core.search_indexes import PublicationDocSearch
from citation.models import Publication, PublicationSponsors

logger = logging.getLogger(__name__)

Query = namedtuple('Query', ['content_type', 'search'])

logger.info('starting')


def extract_query():
    logger.info('about to extract')
    doc = curdoc()
    args = doc.session_context.request.arguments if doc and doc.session_context else {}
    logger.info('retrieved request args')
    content_type_arg = args.get('content_type')
    content_type = content_type_arg[0].decode() if content_type_arg else 'sponsors'
    search_arg = args.get('search')
    search = search_arg[0].decode() if search_arg else ''
    query = Query(content_type=content_type, search=search)
    logger.info('finished ')
    return query


query = extract_query()

logger.info('extracted query: {}'.format(query.content_type))

model_options = [
    ('author', 'Authors'),
    ('platform', 'Platforms'),
    ('sponsor', 'Sponsors'),
    ('tag', 'Tags')
]
model_name_select = Select(title='Content Type', options=model_options,
                           value=query.content_type)
search_text_input = TextInput(title='Search', value=query.search)


def retrieve_matches(content_type):
    s = PublicationDocSearch().full_text(q=query.search).agg_by_count()
    response = s.execute()
    return s.cache[content_type]['count']


def create_search_match_table(data_source):
    columns = [
        TableColumn(field='name', title='Name'),
        TableColumn(field='publication_count', title='Publication Match Count'),
    ]
    return DataTable(source=data_source,
                     columns=columns)


p = Paragraph(text='Begin')
top_matches_data_source = ColumnDataSource(pd.DataFrame.from_records(retrieve_matches(query.content_type)))
match_table = create_search_match_table(top_matches_data_source)


def handler(attr, old, new):
    p.text = str(new)


top_matches_data_source.selected.on_change('indices', handler)


class DataCache:
    def __init__(self):
        self._publication_queryset = None
        self._publications = None
        self._publication_sponsors = None

    def _publication_as_dict(self, p: Publication):
        return {'id': p.id,
                'container': p.container.id,
                'date_published': p.date_published,
                'year_published':
                    p.date_published.year if p.date_published is not None else None,
                'is_archived': p.is_archived,
                'status': p.status,
                'title': p.title}

    @property
    def publication_queryset(self) -> QuerySet:
        if self._publication_queryset is None:
            self._publication_queryset = Publication.api.primary().filter(status='REVIEWED').select_related('container')
        return self._publication_queryset

    @property
    def publications(self):
        if self._publications is None:
            self._publications = pd.DataFrame.from_records(
                (self._publication_as_dict(p) for p in self.publication_queryset), index='id')
            self._publications.index.rename(name='publication__id', inplace=True)
        return self._publications

    @property
    def publication_sponsors(self):
        if self._publication_sponsors is None:
            self._publication_sponsors = read_frame(
                PublicationSponsors.objects.filter(publication__in=self.publication_queryset),
                fieldnames=['publication__id', 'sponsor__id', 'sponsor__name'], index_col='publication__id')
            self._publication_sponsors.rename(
                columns={'sponsor__name': 'name', 'sponsor__id': 'related__id'}, inplace=True)
        return self._publication_sponsors

    def get_full_text_matches(self, query):
        publication_ids = [p.id for p in PublicationDocSearch().full_text(q=query).source(['id']).scan()]
        publication_matches = self.publications.loc[publication_ids]
        return publication_matches

    def get_year_related_counts(self, df: pd.DataFrame, related_ids):
        related = self.publication_sponsors[self.publication_sponsors.related__id.isin(related_ids)]
        _counts_df = df.join(related, how='inner').groupby(['year_published', 'related__id']).agg(
            dict(title='count', is_archived='sum'))
        mi = self.get_all_year_related_combinations(related_ids)
        counts_df = _counts_df.reindex(mi, fill_value=0)
        return counts_df.rename(columns={'title': 'count', 'is_archived': 'archived_count'})


    def get_all_year_related_combinations(self, related_ids):
        return pd.MultiIndex.from_product([range(1995, 2018), related_ids], names=['year_published', 'related__id'])


data_cache = DataCache()


def create_code_availability_chart(query, content_type, indices):
    def create_dataset():
        related_ids = top_matches_data_source.to_df().id.iloc[indices].values

    def create_view():
        p = figure(
            tools='pan,wheel_zoom,save',
            title='Code Availability Over Time',
            plot_width=800)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = 'Year'
        p.yaxis.axis_label = 'Publication Added Count'


curdoc().add_root(layout([widgetbox(model_name_select, search_text_input), match_table, p]))
curdoc().title = 'Visualization of {} for search {}'.format(query.content_type, query.search)
