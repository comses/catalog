import itertools
import logging
import pickle
from pathlib import Path

import networkx as nx
import pandas as pd
from bokeh.colors import RGB
from bokeh.layouts import column, widgetbox, row
from bokeh.models import Select, TableColumn, ColumnDataSource, DataTable, \
    HoverTool, WheelZoomTool, PanTool, Circle, MultiLine, Paragraph
from bokeh.models.graphs import NodesAndLinkedEdges
from bokeh.palettes import Spectral10
from bokeh.plotting import figure
from django.apps import apps
from django.db.models import F, Prefetch, Count, Q
from django_pandas.io import read_frame
from haystack.query import SearchQuerySet

from citation.models import Publication, PublicationPlatforms, \
    PublicationAuthors, PublicationSponsors, Sponsor, PublicationCitations, \
    PublicationModelDocumentations, ModelDocumentation, Platform, Container, Author
from widgets.vue_multiselect import VueMultiselectWidget
from .data_access import CategoryStatistics

logger = logging.getLogger(__name__)


def autocomplete(model_name, q):
    model_names = [m._meta.model_name for m in [Author, Container, Platform, Sponsor]]
    if model_name not in model_names:
        return []
    model = apps.get_model('citation', model_name)

    if model == Container:
        containers = Container.objects.filter(id__in=Publication.api.primary().values_list('container', flat=True))
        if q:
            containers = containers.filter(Q(name__iregex=q) | Q(issn__iexact=q))
        return [dict(value=c.pk, label=c.name) for c in containers[:20]]

    search_results = SearchQuerySet().models(model).order_by('name')
    if q:
        search_results = search_results.autocomplete(name=q)
    pks = [int(pk) for pk in search_results.values_list('pk', flat=True)]
    results = model.objects.filter(pk__in=pks)[:20]
    return [dict(value=r.pk, label=r.name) for r in results]


def publication_as_dict(p: Publication):
    return {'id': p.id,
            'container': p.container.id,
            'date_published': p.date_published,
            'year_published':
                p.date_published.year if p.date_published is not None else None,
            'flagged': p.flagged,
            'is_archived': p.is_archived,
            'status': p.status,
            'title': p.title}


reviewed_primary_publications = Publication.api.primary() \
    .filter(status='REVIEWED')

publication_df = pd.DataFrame.from_records(
    [publication_as_dict(p) for p in
     reviewed_primary_publications
         .select_related('container')], index='id')
publication_df.index.rename(
    name='publication__id',
    inplace=True)
publication_df.index = publication_df.index.astype(int)
publication_df.year_published = \
    publication_df.year_published.astype('category')

publication_authors_df = read_frame(
    PublicationAuthors.objects.filter(
        publication__in=reviewed_primary_publications),
    fieldnames=['publication__id', 'author__id'],
    index_col='publication__id')
publication_authors_df.rename(
    index=int,
    columns={
        'author__id': 'author'},
    inplace=True)

publication_platforms_df = read_frame(
    PublicationPlatforms.objects.filter(
        publication__in=reviewed_primary_publications),
    fieldnames=['publication__id', 'platform__id'],
    index_col='publication__id')
publication_platforms_df.rename(
    index=int,
    columns={
        'platform__id': 'platform'},
    inplace=True)

publication_sponsor_df = read_frame(
    PublicationSponsors.objects.filter(
        publication__in=reviewed_primary_publications),
    fieldnames=['publication__id', 'sponsor__id'],
    index_col='publication__id')
publication_sponsor_df.rename(
    index=int,
    columns={
        'sponsor__id': 'sponsor'},
    inplace=True)

publication_citation_df = read_frame(
    PublicationCitations.objects.filter(
        publication__in=reviewed_primary_publications,
        citation__in=reviewed_primary_publications),
    fieldnames=['publication__id', 'citation__id'],
    index_col='publication__id')

model_documentation_df = read_frame(
    ModelDocumentation.objects.annotate(model_documentation__id=F('id')),
    fieldnames=['name'],
    index_col='model_documentation__id')

publication_model_documentation_df = read_frame(
    PublicationModelDocumentations.objects.filter(
        publication__in=reviewed_primary_publications),
    fieldnames=['publication__id', 'model_documentation__id'],
    index_col='publication__id')


class ColorStreamIterator:
    def __init__(self, size):
        levels = range(0, 256, 255 // size)
        self.iterator = iter(
            filter(
                lambda rgb: any(
                    c > 31 for c in rgb), itertools.product(
                    levels, levels, levels)))

    def __next__(self):
        color = RGB(*next(self.iterator))
        return color


class ColorStream:
    def __init__(self, size):
        self.size = size

    def __iter__(self):
        return ColorStreamIterator(self.size)


class AbstractPublicationCountChart:
    title = None
    x_axis = None
    y_axis = None

    DEFAULT_MODEL_NAME = 'none'
    NONE_LABEL = 'All publications'

    model_name_lookup = {
        'author': publication_authors_df,
        'platform': publication_platforms_df,
        'sponsor': publication_sponsor_df
    }

    def __init__(self):
        self.selected_options_widget = VueMultiselectWidget(selectedOptions=[])
        self.model_name_widget = Select(
            title='Model Name', value='none', options=[
                'none', 'author', 'container', 'platform', 'sponsor'])
        self.selected_options_widget.on_change(
            'selectedOptions', lambda attr, old, new: self.render_plot())
        self.model_name_widget.on_change(
            'value', lambda attr, old, new: self.clear_options())
        self.layout = column(
            widgetbox(
                self.model_name_widget,
                self.selected_options_widget,
                width=800),
            column(
                self.create_plot()))

    def create_plot(self):
        pass

    def clear_options(self):
        modelName = self.model_name_widget.value
        self.selected_options_widget.selectedOptions = []
        self.selected_options_widget.options = []
        self.selected_options_widget.modelName = modelName
        self.render_plot()

    def render_plot(self):
        # nesting the column layout prevents multiselect widget from
        # rerendering so ESC key exits properly
        self.layout.children[1].children[0] = self.create_plot()

    def render(self):
        return self.layout


class PublicationCodeAvailabilityChart(AbstractPublicationCountChart):
    title = 'Publication Added Counts by Year'
    x_axis = 'Year'
    y_axis = 'Publication Added Count'

    def create_plot(self):
        df = self.create_dataset(
            modelName=self.model_name_widget.value,
            selectedOptions=self.selected_options_widget.selectedOptions)
        p = figure(
            tools='pan,wheel_zoom,save',
            title=self.title,
            plot_width=800)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = self.x_axis
        p.yaxis.axis_label = self.y_axis
        logger.info(df)
        grouped = df.groupby('group')
        logger.info(grouped.groups)
        color_mapper = Spectral10
        for i, (name, dfg) in enumerate(df.groupby('group')):
            logger.info('name: %s', name)
            logger.info(dfg)
            p.line(
                x=dfg.year_published,
                y=dfg['count'],
                legend=name,
                line_width=2,
                color=color_mapper[i])
            p.line(
                x=dfg.year_published,
                y=dfg.is_archived,
                legend='{} (Code Available)'.format(name),
                line_width=2,
                color=color_mapper[i],
                line_dash='dashed')
        return p

    @staticmethod
    def build_dense_year_published_df(df, modelName='none'):
        groupings = ['year_published']
        if modelName is not 'none':
            groupings.append(modelName)
        df_count = df.groupby(groupings)[['title']].count()
        df_is_archived = df.groupby(groupings)[['is_archived']].sum()
        result_df = df_count.join(df_is_archived)
        result_df.rename(index=str, columns={'title': 'count'}, inplace=True)
        result_df.fillna(0, inplace=True)
        result_df.reset_index(inplace=True)
        return result_df

    @classmethod
    def create_dataset(cls, modelName, selectedOptions):
        logger.info('selectedOptions: %s', selectedOptions)
        logger.info('modelName: %s', modelName)
        if modelName == 'none' or not selectedOptions:
            grouped = publication_df.groupby(['year_published'])
            df = (grouped[['title']].count()).join(
                grouped[['is_archived']].sum())
            df.rename(index=str, columns={'title': 'count'}, inplace=True)
            df.fillna(0, inplace=True)
            df.reset_index(inplace=True)
            df['group'] = 'All publications'
            return df

        pks = [o['value'] for o in selectedOptions]

        if modelName == 'container':
            df = publication_df.loc[publication_df[modelName].isin(pks)]
        else:
            related_df = cls.model_name_lookup[modelName]
            related_df = related_df.loc[related_df[modelName].isin(pks)]
            df = publication_df.join(related_df, how='inner')

        df = cls.build_dense_year_published_df(df, modelName)
        df.rename(index=str, columns={modelName: 'group'}, inplace=True)
        df['group'] = df['group'].astype('int')
        label_lookup = {o['value']: o['label'] for o in selectedOptions}
        df['group'] = [label_lookup[pk] for pk in df['group']]
        return df


class PublicationModelDocumentationChart(AbstractPublicationCountChart):

    @classmethod
    def create_dataset(cls, modelName, selectedOptions):
        counts_by_year = publication_df.join(publication_model_documentation_df) \
            .groupby(['year_published', 'model_documentation__id'])[['title']] \
            .count()
        counts_by_year.fillna(value=0, inplace=True)
        counts_by_year.rename(index=str, columns={'title': 'count'}, inplace=True)
        return counts_by_year

    def create_code_availability_table(self):
        return Paragraph(text='foo')

    def create_plot(self):
        df = self.create_dataset(modelName=self.model_name_widget.value,
                                 selectedOptions=self.selected_options_widget.selectedOptions)
        p = figure(
            tools='pan,wheel_zoom,save',
            title=self.title,
            plot_width=800)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = self.x_axis
        p.yaxis.axis_label = self.y_axis
        cs = itertools.cycle(ColorStream(2))
        for color, (name_id, dfg) in zip(cs, df.groupby('model_documentation__id')):
            name = model_documentation_df.name[int(name_id)]
            logger.info('name: %s', name)
            logger.info(dfg)
            p.line(
                x=dfg.index.get_level_values('year_published'),
                y=dfg['count'],
                legend=name,
                line_width=2,
                color=color)
        return p


class Overview:
    def __init__(self):
        self.layout = column(
            row(self.create_platform_code_availability_table()),
            row(self.create_sponsor_code_availability_table()),
        )

    def create_sponsor_code_availability_table(self):
        columns = [
            TableColumn(
                field='name', title='Sponsor'), TableColumn(
                field='count', title='# of times sponsored'), TableColumn(
                field='code_availability_count', title='# of times code available')]
        df = publication_df.join(publication_sponsor_df, how='inner')
        df = df.groupby(
            'sponsor',
            as_index=False).agg(
            dict(
                title='count',
                is_archived='sum'))
        df.rename(
            index=str,
            columns={
                'is_archived': 'code_availability_count',
                'title': 'count'},
            inplace=True)
        df = df.loc[df['count'].nlargest(10).index]
        sponsor_map = Sponsor.objects.filter(id__in=df.sponsor).in_bulk()
        df['name'] = df['sponsor'].apply(lambda pk: sponsor_map[pk].name)
        return DataTable(
            source=ColumnDataSource(df),
            columns=columns, width=800)

    def create_platform_code_availability_table(self):
        columns = [
            TableColumn(
                field='name', title='Platform'), TableColumn(
                field='count', title='# of times platform used'), TableColumn(
                field='code_availability_count', title='# of times code available')]
        df = publication_df.join(publication_platforms_df, how='inner')
        df = df.groupby(
            'platform',
            as_index=False).agg(
            dict(
                title='count',
                is_archived='sum'))
        df.rename(
            index=str,
            columns={
                'is_archived': 'code_availability_count',
                'title': 'count'},
            inplace=True)
        df = df.loc[df['count'].nlargest(10).index]
        platform = Platform.objects.filter(id__in=df.platform).in_bulk()
        df['name'] = df['platform'].apply(lambda pk: platform[pk].name)
        return DataTable(
            source=ColumnDataSource(df),
            columns=columns, width=800)

    def render(self):
        return self.layout


class PublicationCitationNetwork:
    def __init__(self):
        self.network, self.network_layout = self.get_network()
        self.network_renderer = self.get_network_renderer(
            network=self.network, network_layout=self.network_layout)
        self.layout = row(self.create_network_figure(self.network_renderer))

    @staticmethod
    def _build_network():
        g = nx.Graph()
        logger.info('starting')
        # a = np.array([1, 2])
        # g.add_nodes_from(int(x) for x in a)
        # g.add_edge(a[0], a[1])
        g.add_nodes_from(int(n) for n in publication_df.index.values)

        for id, p in publication_df.iterrows():
            try:
                citation_ids = publication_citation_df.loc[[id]][
                    'citation__id']
            except KeyError:
                continue
            for c_id in citation_ids:
                g.add_edge(id, c_id)
        logger.info('made it')
        return g, nx.spring_layout(g)

    @classmethod
    def _load_graph_from_pickle(cls, p: Path):
        with p.open('rb') as f:
            network, network_layout = pickle.load(f)
        logger.info('loaded from file')
        return network, network_layout

    @classmethod
    def get_network(cls):
        path = Path('/code/visualization/bokeh_example/graph.pickle')
        if path.exists():
            logger.info('load from file')
            return cls._load_graph_from_pickle(path)
        else:
            logger.info('building from scratch')
            network, network_layout = cls._build_network()
            with path.open('wb') as fileobj:
                pickle.dump((network, network_layout), fileobj)
            return network, network_layout

    @staticmethod
    def get_network_renderer(network, network_layout):
        # inline import to prevent circular imports
        from bokeh.models.renderers import GraphRenderer
        from bokeh.models.graphs import StaticLayoutProvider

        # Handles nx 1.x vs 2.x data structure change
        nodes = list(network.nodes())
        edges = list(network.edges())

        edges_start = [edge[0] for edge in edges]
        edges_end = [edge[1] for edge in edges]

        node_source = ColumnDataSource(
            data=dict(
                index=nodes,
                name=list(
                    publication_df.loc[nodes]
                    ['title'])))
        edge_source = ColumnDataSource(data=dict(
            start=edges_start,
            end=edges_end
        ))

        network_renderer = GraphRenderer()
        network_renderer.node_renderer.data_source.data = node_source.data
        network_renderer.node_renderer.glyph = Circle(
            size=8, fill_color='#0000CC')
        network_renderer.edge_renderer.data_source.data = edge_source.data
        network_renderer.edge_renderer.glyph = MultiLine(
            line_color='#CCCCCC', line_alpha=0.8, line_width=2)

        network_renderer.layout_provider = StaticLayoutProvider(
            graph_layout=network_layout)
        network_renderer.inspection_policy = NodesAndLinkedEdges()

        return network_renderer

    @classmethod
    def create_network_figure(cls, graph_renderer):
        f = figure(title='Publication Cocitation Network',
                   x_range=(-1.1, 1.1), y_range=(-1.1, 1.1), tools='')

        hover = HoverTool(tooltips=[
            ('Name', '@name')
        ])
        f.renderers.append(graph_renderer)
        f.add_tools(hover, WheelZoomTool(), PanTool())
        f.xaxis.visible = False
        f.yaxis.visible = False
        logger.info('returning figure')
        return f

    def render(self):
        return self.layout


class NetworkStatistics:
    model = None

    def get_queryset(self):
        return Publication.api.primary().prefetch_related(
            Prefetch(lookup='citations', queryset=Publication.api.primary().only('id'), to_attr='primary_citations')) \
            .annotate(n_authors=Count('publication_authors'))

    def primary_statistics(self):
        n_citations = 0
        n_authors = 0
        qs = self.get_queryset()
        for publication in qs:
            n_citations += len(publication.primary_citations)
            n_authors += publication.n_authors
        n_publications = len(qs)

        normalized_citations = n_citations / n_authors
        citation_count = n_citations
        average_citations_per_publication = n_citations / n_publications
        return normalized_citations, citation_count, average_citations_per_publication
