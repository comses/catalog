import logging
from collections import namedtuple

import pandas as pd
from bokeh.io import curdoc
from bokeh.layouts import row, column
from bokeh.models import TextInput, TableColumn, DataTable, ColumnDataSource, Paragraph
from bokeh.models.widgets import Select
from bokeh.palettes import Spectral10
from bokeh.plotting import figure
from django.db.models import QuerySet
from django_pandas.io import read_frame

from catalog.core.search_indexes import PublicationDocSearch
from citation.models import Publication, PublicationSponsors, Sponsor, PublicationPlatforms, Platform, Author, \
    PublicationAuthors, Tag, PublicationTags

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
    ('authors', 'Authors'),
    ('platforms', 'Platforms'),
    ('sponsors', 'Sponsors'),
    ('tags', 'Tags')
]
model_name_select = Select(title='Content Type', options=model_options,
                           value=query.content_type)
search_text_input = TextInput(title='Search', value=query.search)


def retrieve_matches(search, content_type):
    s = PublicationDocSearch().full_text(q=search).agg_by_count()
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
top_matches_data_source = ColumnDataSource(
    pd.DataFrame.from_records(retrieve_matches(search=query.search, content_type=query.content_type)))
match_table = create_search_match_table(top_matches_data_source)


class ModelDataAccess:
    def __init__(self, data_cache: 'DataCache', related_name, related_through_name):
        self.data_cache = data_cache
        self.related_name = related_name
        self.related_through_name = related_through_name

    def get_full_text_matches(self, query):
        publication_ids = [p.id for p in PublicationDocSearch().full_text(q=query).source(['id']).scan()]
        publication_matches = self.data_cache.publications.loc[publication_ids]
        return publication_matches

    def get_year_related_counts(self, df: pd.DataFrame, related_ids):
        related_through_table = getattr(self.data_cache, self.related_through_name)
        related = related_through_table[related_through_table.related__id.isin(related_ids)]
        _counts_df = df.join(related, how='inner').groupby(['year_published', 'related__id']).agg(
            dict(title='count', is_archived='sum'))
        mi = self.data_cache.get_all_year_related_combinations(related_ids)
        counts_df = _counts_df.reindex(mi, fill_value=0)
        return counts_df.rename(columns={'title': 'count', 'is_archived': 'archived_count'})

    def get_related_names(self, related_ids):
        related_table = getattr(self.data_cache, self.related_name)
        return related_table.loc[related_ids]


class DataCache:
    def __init__(self):
        self._publication_queryset = None
        self._publications = None

        self._authors = None
        self._publication_authors = None

        self._platforms = None
        self._publication_platforms = None

        self._sponsors = None
        self._publication_sponsors = None

        self._tags = None
        self._publication_tags = None

    def _publication_as_dict(self, p: Publication):
        return {'id': p.id,
                'container': p.container.id,
                'date_published': p.date_published,
                'year_published':
                    p.date_published.year if p.date_published is not None else None,
                'is_archived': p.is_archived,
                'status': p.status,
                'title': p.title}

    def _author_as_dict(self, a: Author):
        return {
            'id': a.id,
            'name': a.name
        }

    def _publication_author_as_dict(self, pa: PublicationAuthors):
        return {
            'publication__id': pa.publication_id,
            'related__id': pa.author_id,
            'name': pa.author.name
        }

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
    def authors(self):
        if self._authors is None:
            self._authors = pd.DataFrame.from_records(
                (self._author_as_dict(a) for a in Author.objects.filter(publications__in=self.publication_queryset)),
                index='id')
        return self._authors

    @property
    def publication_authors(self):
        if self._publication_authors is None:
            self._publication_authors = pd.DataFrame.from_records(
                (self._publication_author_as_dict(pa) for pa in
                 PublicationAuthors.objects.filter(publication__in=self.publication_queryset).select_related('author')),
                index='publication__id')
        return self.publication_authors

    @property
    def platforms(self):
        if self._platforms is None:
            self._platforms = read_frame(Platform.objects.filter(publications__in=self.publication_queryset).distinct(),
                                         fieldnames=['id', 'name'], index_col='id')
        return self._platforms

    @property
    def publication_platforms(self):
        if self._publication_platforms is None:
            self._publication_platforms = read_frame(
                PublicationPlatforms.objects.filter(publication__in=self.publication_queryset),
                fieldnames=['publication__id', 'platform__id', 'platform__name'], index_col='publication__id')
            self._publication_platforms.rename(
                columns={'platform__name': 'name', 'platform__id': 'related__id'}, inplace=True)
        return self._publication_platforms

    @property
    def sponsors(self):
        if self._sponsors is None:
            self._sponsors = read_frame(Sponsor.objects.filter(publications__in=self.publication_queryset).distinct(),
                                        fieldnames=['id', 'name'], index_col='id')
        return self._sponsors

    @property
    def publication_sponsors(self):
        if self._publication_sponsors is None:
            self._publication_sponsors = read_frame(
                PublicationSponsors.objects.filter(publication__in=self.publication_queryset),
                fieldnames=['publication__id', 'sponsor__id', 'sponsor__name'], index_col='publication__id')
            self._publication_sponsors.rename(
                columns={'sponsor__name': 'name', 'sponsor__id': 'related__id'}, inplace=True)
        return self._publication_sponsors

    @property
    def tags(self):
        if self._tags is None:
            self._tags = read_frame(Tag.objects.filter(publications__in=self.publication_queryset),
                                    fieldnames=['id', 'name'], index_col='id')
        return self._tags

    @property
    def publication_tags(self):
        if self._publication_tags is None:
            self._publication_tags = read_frame(
                PublicationTags.objects.filter(publication__in=self.publication_queryset),
                fieldnames=['publication__id', 'tag__id', 'tag__name'], index_col='publication__id')
            self._publication_tags.rename(
                columns={'tag__name': 'name', 'tag__id': 'related__id'}, inplace=True)
        return self._publication_tags

    def get_model_data_access_api(self, related_name, related_through_name=None):
        related_name = related_name
        if related_through_name is None:
            related_through_name = 'publication_{}'.format(related_name)
        return ModelDataAccess(data_cache=self, related_name=related_name, related_through_name=related_through_name)

    def get_all_year_related_combinations(self, related_ids):
        return pd.MultiIndex.from_product([range(1995, 2018), related_ids], names=['year_published', 'related__id'])


data_cache = DataCache()


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
            logger.info('related_id: %s', related_id)
            logger.info('name_retrive, %s', api.get_related_names(related_id)['name'])
            name = api.get_related_names(related_id)['name']
            logger.info('name: %s', name)
            logger.info(dfg)
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
    row(model_name_select, search_text_input),
    row(CodeAvailabilityChart(search=query.search, model_name=model_name_select.value, indices=[0, 1]).render()),
    row(match_table))


def update_chart():
    page.children[1] = CodeAvailabilityChart(search=query.search, model_name=model_name_select.value,
                                             indices=top_matches_data_source.selected.indices).render()


def update_table():
    top_matches_data_source.data.update(ColumnDataSource(pd.DataFrame.from_records(
        retrieve_matches(search=search_text_input.value, content_type=model_name_select.value))).data)


model_name_select.on_change('value', lambda attr, old, new: update_chart() or update_table())
top_matches_data_source.selected.on_change('indices', lambda attr, old, new: update_chart())

curdoc().add_root(page)
curdoc().title = 'Visualization of {} for search {}'.format(query.content_type, query.search)
