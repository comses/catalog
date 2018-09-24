import itertools
import logging
import pickle
from pathlib import Path

import networkx as nx
import pandas as pd
from bokeh.colors import RGB
from bokeh.layouts import column, widgetbox
from bokeh.models import Select, TableColumn, ColumnDataSource, DataTable, from_networkx, NodesAndLinkedEdges, \
    HoverTool, WheelZoomTool, PanTool
from bokeh.plotting import figure
from django_pandas.io import read_frame

from citation.models import Publication, PublicationPlatforms, PublicationAuthors, PublicationSponsors, Sponsor, \
    PublicationCitations
from widgets.vue_multiselect import VueMultiselectWidget

logger = logging.getLogger(__name__)


def publication_as_dict(p: Publication):
    return {'id': p.id,
            'container': p.container.id,
            'date_published': p.date_published,
            'year_published': p.date_published.year if p.date_published is not None else None,
            'flagged': p.flagged,
            'is_archived': p.is_archived,
            'status': p.status,
            'title': p.title}


reviewed_primary_publications = Publication.api.primary().filter(status='REVIEWED')

publication_df = pd.DataFrame.from_records([publication_as_dict(p) for p in
                                            reviewed_primary_publications
                                           .select_related('container')], index='id')
publication_df.rename(index=str, columns={'id': 'publication__id'}, inplace=True)
publication_df.index = publication_df.index.astype(int)
publication_df.year_published = publication_df.year_published.astype('category')

publication_authors_df = read_frame(PublicationAuthors.objects.filter(publication__in=reviewed_primary_publications),
                                    fieldnames=['publication__id', 'author__id'], index_col='publication__id')
publication_authors_df.rename(index=str, columns={'author__id': 'author'}, inplace=True)

publication_platforms_df = read_frame(
    PublicationPlatforms.objects.filter(publication__in=reviewed_primary_publications),
    fieldnames=['publication__id', 'platform__id'], index_col='publication__id')
publication_platforms_df.rename(index=str, columns={'platform__id': 'platform'}, inplace=True)

publication_sponsor_df = read_frame(PublicationSponsors.objects.filter(publication__in=reviewed_primary_publications),
                                    fieldnames=['publication__id', 'sponsor__id'], index_col='publication__id')
publication_sponsor_df.rename(index=str, columns={'sponsor__id': 'sponsor'}, inplace=True)

publication_citation_df = read_frame(PublicationCitations.objects.filter(publication__in=reviewed_primary_publications,
                                                                         citation__in=reviewed_primary_publications),
                                     fieldnames=['publication__id', 'citation__id'], index_col='publication__id')


class ColorStreamIterator:
    def __init__(self, size):
        levels = range(0, 256, 255 // size)
        self.iterator = iter(filter(lambda rgb: any(c > 31 for c in rgb), itertools.product(levels, levels, levels)))

    def __next__(self):
        color = RGB(*next(self.iterator))
        return color


class ColorStream:
    def __init__(self, size):
        self.size = size

    def __iter__(self):
        return ColorStreamIterator(self.size)


class PublicationCountsByYear:
    title = 'Publication Added Counts by Year'
    x_axis = 'Year'
    y_axis = 'Publication Added Count'

    DEFAULT_MODEL_NAME = 'none'
    NONE_LABEL = 'All publications'

    model_name_lookup = {
        'author': publication_authors_df,
        'platform': publication_platforms_df,
        'sponsor': publication_sponsor_df
    }

    def __init__(self):
        self.selected_options_widget = VueMultiselectWidget(selectedOptions=[])
        self.model_name_widget = Select(title='Model Name', value='none',
                                        options=['none', 'author', 'container', 'platform', 'sponsor'])
        self.selected_options_widget.on_change('selectedOptions', lambda attr, old, new: self.render_plot())
        self.model_name_widget.on_change('value', lambda attr, old, new: self.clear_options())
        self.layout = column(widgetbox(self.model_name_widget,
                                       self.selected_options_widget, width=800),
                             column(self.create_plot()),
                             self.create_code_availibility_table())

    def create_plot(self):
        df = self.create_dataset(modelName=self.model_name_widget.value,
                                 selectedOptions=self.selected_options_widget.selectedOptions)
        p = figure(tools='pan,wheel_zoom,save', title=self.title, plot_width=800)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = self.x_axis
        p.yaxis.axis_label = self.y_axis
        logger.info(df)
        grouped = df.groupby('group')
        logger.info(grouped.groups)
        cs = itertools.cycle(ColorStream(1))
        for color, (name, dfg) in zip(cs, df.groupby('group')):
            logger.info('name: %s', name)
            logger.info(dfg)
            p.line(x=dfg.year_published, y=dfg['count'], legend=name, line_width=2, color=color)
            p.line(x=dfg.year_published, y=dfg.is_archived, legend='{} (Code Available)'.format(name), line_width=2,
                   color=color, line_dash='dashed')
        return p

    def clear_options(self):
        modelName = self.model_name_widget.value
        self.selected_options_widget.selectedOptions = []
        self.selected_options_widget.options = []
        self.selected_options_widget.modelName = modelName
        self.render_plot()

    def create_code_availibility_table(self):
        columns = [
            TableColumn(field='name', title='Sponsor'),
            TableColumn(field='count', title='# of times sponsored'),
            TableColumn(field='code_availability_count', title='# of times code available')
        ]
        df = publication_df.join(publication_sponsor_df, how='inner')
        df = df.groupby('sponsor', as_index=False).agg(dict(title='count', is_archived='sum'))
        df.rename(index=str, columns={'is_archived': 'code_availability_count', 'title': 'count'}, inplace=True)
        df = df.loc[df['count'].nlargest(10).index]
        sponsor_map = Sponsor.objects.filter(id__in=df.sponsor).in_bulk()
        df['name'] = df['sponsor'].apply(lambda pk: sponsor_map[pk].name)
        return DataTable(source=ColumnDataSource(df), columns=columns, width=800)

    def render_plot(self):
        # nesting the column layout prevents multiselect widget from rerendering so ESC key exits properly
        self.layout.children[1].children[0] = self.create_plot()

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
            df = (grouped[['title']].count()).join(grouped[['is_archived']].sum())
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

    def render(self):
        return self.layout


class PublicationCocitationGraph:
    def __init__(self):
        self.layout = self.create_network_figure()

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
                citation_ids = publication_citation_df.loc[[id]]['citation__id']
            except KeyError:
                continue
            for c_id in citation_ids:
                g.add_edge(id, c_id)
        logger.info('made it')
        return g, nx.spring_layout(g)

    @staticmethod
    def _build_graph_renderer(graph, graph_layout):
        # inline import to prevent circular imports
        from bokeh.models.renderers import GraphRenderer
        from bokeh.models.graphs import StaticLayoutProvider

        # Handles nx 1.x vs 2.x data structure change
        nodes = list(graph.nodes())
        edges = list(graph.edges())

        edges_start = [edge[0] for edge in edges]
        edges_end = [edge[1] for edge in edges]

        node_source = ColumnDataSource(data=dict(index=nodes, name=list(publication_df.loc[nodes]['title'])))
        edge_source = ColumnDataSource(data=dict(
            start=edges_start,
            end=edges_end
        ))

        graph_renderer = GraphRenderer()
        graph_renderer.node_renderer.data_source.data = node_source.data
        graph_renderer.edge_renderer.data_source.data = edge_source.data

        graph_renderer.layout_provider = StaticLayoutProvider(graph_layout=graph_layout)
        graph_renderer.inspection_policy = NodesAndLinkedEdges()

        return graph_renderer

    @classmethod
    def _load_graph_from_pickle(cls, p: Path):
        with p.open('rb') as f:
            graph, graph_layout = pickle.load(f)
        logger.info('loaded from file')
        graph_renderer = cls._build_graph_renderer(graph, graph_layout)
        return graph_renderer

    @classmethod
    def create_network_figure(cls):
        f = figure(title='Publication Cocitation Network', x_range=(-1.1, 1.1), y_range=(-1.1, 1.1), tools='')

        path = Path('graph.pickle')
        if path.exists():
            logger.info('load from file')
            graph_renderer = cls._load_graph_from_pickle(path)
        else:
            logger.info('building from scratch')
            graph, graph_layout = cls._build_network()
            graph_renderer = cls._build_graph_renderer(graph, graph_layout)
            with path.open('wb') as fileobj:
                pickle.dump((graph, graph_layout), fileobj)

        hover = HoverTool(tooltips=[
            ('Name', '@name')
        ])
        f.renderers.append(graph_renderer)
        f.add_tools(hover, WheelZoomTool(), PanTool())
        logger.info('returning figure')
        return f

    def render(self):
        return self.layout
