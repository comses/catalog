import networkx as nx
import plotly.graph_objs as go

from data_wrangling import PublicationQueries, data_cache


def build_network(text):
    g = nx.Graph()
    df = PublicationQueries(data_cache.publication_df).filter_by_fulltext_search(text).df

    g.add_nodes_from(zip(df.index, (dict(title=t) for t in df.title)))
    for publication_pk, publication_data in df.iterrows():
        for citation_pk in publication_data.citation_pks:
            if citation_pk in g:
                g.add_edge(publication_pk, citation_pk)
    return g


def add_node_positions(g):
    layout = nx.spring_layout(g)
    for pk, node_position in layout.items():
        g[pk]['pos'] = node_position


def build_edge_scatter(g):
    xs, ys = [], []
    positions = nx.get_node_attributes(g, 'pos')
    for edge in g.edges():
        from_pk, to_pk = edge
        x1, y1 = positions[from_pk]
        x2, y2 = positions[to_pk]
        xs += [x1, x2, None]
        ys += [y1, y2, None]
    return go.Scatter(x=xs, y=ys, line=dict(width=0.5, color='#888'), hoverinfo='none', mode='lines')


def build_node_scatter(g):
    xs, ys, titles = [], [], []
    positions = nx.get_node_attributes(g, 'pos')
    title_attr = nx.get_node_attributes(g, 'title')
    for pk in g.nodes():
        x, y = positions[pk]
        xs.append(x)
        ys.append(y)
        titles.append(title_attr[pk])
    return go.Scatter(
        x=xs,
        y=ys,
        text=titles
    )


def figure(text):
    g = build_network(text)
    add_node_positions(g)
    citation_relationships_scatter = build_edge_scatter(g)
    publication_scatter = build_node_scatter(g)
    return go.Figure(data=[citation_relationships_scatter, publication_scatter],
                     layout=go.Layout(
                         'Publication Citation Network',
                         xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                         yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
                     ))


