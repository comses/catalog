import logging
from typing import List

import dash_core_components as dcc
import dash_html_components as html
import plotly.graph_objs as go
from dash.dependencies import Output, Input

import data_wrangling as dw
from data_wrangling import data_cache
from citation.models import Author, Sponsor, Platform, Container
from common import app

logger = logging.getLogger(__name__)

PARENT_INSTANCE_DROPDOWN_ID = 'archival-status-model-options-parent'
INSTANCE_DROPDOWN_ID = 'archival-status-model-options'
MODEL_DROPDOWN_ID = 'archival-status-model-selected'


def author_dropdown():
    authors = data_cache.authors.options
    return dcc.Dropdown(id=INSTANCE_DROPDOWN_ID,
                        options=authors,
                        multi=True,
                        placeholder='Select authors')


def container_dropdown():
    containers = data_cache.containers.options
    return dcc.Dropdown(id=INSTANCE_DROPDOWN_ID,
                        options=containers,
                        multi=True,
                        placeholder='Select journals, books and other media')


def platform_dropdown():
    platform_options = data_cache.platforms.options
    return dcc.Dropdown(id=INSTANCE_DROPDOWN_ID,
                        options=platform_options,
                        multi=True,
                        placeholder='Select platforms')


def sponsor_dropdown():
    qs = data_cache.sponsors.objs
    sponsor_options = [{'label': s.name, 'value': s.id} for s in qs]
    return dcc.Dropdown(id=INSTANCE_DROPDOWN_ID,
                        options=sponsor_options,
                        multi=True,
                        placeholder='Select sponsors')


def no_dropdown():
    return dcc.Dropdown(id=INSTANCE_DROPDOWN_ID,
                        disabled=True)


class ModelDispatcher:
    def __init__(self):
        self.view_dispatcher = {}
        self.options = []

    def add_lookup(self, label, value, view):
        self.view_dispatcher[value] = view
        self.options.append(dict(label=label, value=value))

    def dispatch(self, value):
        return self.view_dispatcher[value]()


model_dispatcher = ModelDispatcher()
model_dispatcher.add_lookup(label='None', value='', view=no_dropdown)
model_dispatcher.add_lookup(label='Authors', value=Author._meta.model_name, view=author_dropdown)
model_dispatcher.add_lookup(label='Journal, Books and Other Media', value=Container._meta.model_name, view=container_dropdown)
model_dispatcher.add_lookup(label='Platforms', value=Platform._meta.model_name, view=platform_dropdown)
model_dispatcher.add_lookup(label='Sponsors', value=Sponsor._meta.model_name, view=sponsor_dropdown)


def variable_dropdown():
    return dcc.Dropdown(id=MODEL_DROPDOWN_ID,
                        options=model_dispatcher.options,
                        placeholder='Select a model to filter by',
                        value='')


def model_options_dropdown(model_name):
    return [
        model_dispatcher.dispatch(model_name)
    ]


def figure(model_name, pks: List[int]):
    df = data_cache.publication_df
    pq = dw.PublicationQueries(df)
    data = []
    if pks:
        for pk in pks:
            df_counts = pq.filter_by_pk(model_name=model_name, pk=pk).to_is_archived()
            print(df_counts)
            scatter = go.Scatter(
                x=df_counts.year_published.index,
                y=df_counts.year_published,
                mode='lines',
                name=data_cache.publication_lookup(model_name, pk)['obj'].name,
                hoverinfo='name',
            )
            data.append(scatter)
    else:
        df = pq.to_is_archived()
        data.append(go.Scatter(
            x=df.year_published.index,
            y=df.year_published,
            mode='lines',
            name='Count',
            hoverinfo='name',
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
        dcc.Markdown('''Select a variable split publications by (or leave it None)
        
If a variable is selected then select variable instances to compare (authors with authors etc)'''),
        variable_dropdown(),
        html.Div(id=PARENT_INSTANCE_DROPDOWN_ID, children=model_options_dropdown('')),
        dcc.Graph(id='publication-counts-by-year', figure=figure('', values))])


app.callback(Output('publication-counts-by-year', 'figure'),
             [Input(MODEL_DROPDOWN_ID, 'value'),
              Input(INSTANCE_DROPDOWN_ID, 'value')])(figure)
app.callback(Output(PARENT_INSTANCE_DROPDOWN_ID, 'children'),
             [Input(MODEL_DROPDOWN_ID, 'value')])(model_options_dropdown)
app.callback(Output(INSTANCE_DROPDOWN_ID, 'value'),
             [Input(MODEL_DROPDOWN_ID, 'value')])(lambda v: [])
