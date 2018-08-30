import logging
from typing import List

import dash_core_components as dcc
import dash_html_components as html
import plotly.graph_objs as go
from citation.models import Author, Sponsor
from dash.dependencies import Output, Input

import data_wrangling as dw
from common import app, data_cache

logger = logging.getLogger(__name__)

VALUES_SELECTED_ID = 'archival-status-values-selected'
MODEL_SELECTED_ID = 'archival-status-model-selected'


def author_dropdown():
    qs = data_cache.authors.objs
    authors = [{'label': a.name, 'value': a.id} for a in qs]
    return dcc.Dropdown(id=VALUES_SELECTED_ID,
                        options=authors,
                        multi=True,
                        placeholder='Select authors')


def sponsor_dropdown():
    qs = data_cache.sponsors.objs
    sponsor_options = [{'label': s.name, 'value': s.id} for s in qs]
    return dcc.Dropdown(id=VALUES_SELECTED_ID,
                        options=sponsor_options,
                        multi=True,
                        placeholder='Select sponsors')


def no_dropdown():
    return dcc.Dropdown(id=VALUES_SELECTED_ID,
                        disabled=True)


DISPATCH_MODEL_OPTIONS = {
    Author._meta.model_name: author_dropdown,
    Sponsor._meta.model_name: sponsor_dropdown,
    '': no_dropdown
}


def variable_dropdown():
    return dcc.Dropdown(id=MODEL_SELECTED_ID,
                        options=[{k: k for k in DISPATCH_MODEL_OPTIONS.keys()}],
                        placeholder='Select a model to filter by',
                        value='None')


def model_options_dropdown(model_name):
    return DISPATCH_MODEL_OPTIONS[model_name]()


def figure(pks: List[int]):
    logger.error('figure: %s', pks)
    df = data_cache.publication_df
    pq = dw.PublicationQueries(df)
    # \
    #     .filter_by_date_published(start_year=year_published_range[0], end_year=year_published_range[1])
    data = []
    if pks:
        for pk in pks:
            df_author = pq.filter_by_author_pk(pk).to_is_archived()
            print(df_author)
            bar = go.Bar(
                x=df_author.year_published.index,
                y=df_author.year_published,
                # marker=dict(size=(df.is_archived / df.year_published) * 100),
                # mode='lines+markers',
                name=data_cache.authors.publication_lookup[pk]['obj'].name,
                hoverinfo='name',
                # line=dict(
                #     shape='linear'
                # )
            )
            data.append(bar)
    else:
        df = pq.to_is_archived()
        data.append(go.Bar(
            x=df.year_published.index,
            y=df.year_published,
            # marker=dict(size=(df.is_archived / df.year_published) * 100),
            # mode='lines+markers',
            name='Count',
            hoverinfo='name',
            # line=dict(
            #     shape='linear'
            # )
        ))
    return dict(
        data=data,
        layout=go.Layout(
            xaxis=dict(
                title='Year Published',
            ),
            yaxis=dict(
                title='Publications Published Count',
            )
        )
    )


def publication_archived_status(values: list):
    return html.Div([
        author_dropdown(),
        dcc.Graph(id='publication-counts-by-year', figure=figure(values))])


app.callback(Output('publication-counts-by-year', 'figure'),
             [Input(VALUES_SELECTED_ID, 'value')])(figure)
