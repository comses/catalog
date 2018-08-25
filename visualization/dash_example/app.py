# -*- coding: utf-8 -*-
import os
import sys
from pprint import pprint

import dash
import dash_core_components as dcc
import dash_html_components as html
import django
import pandas as pd
import plotly.graph_objs as go

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "catalog.settings")
sys.path.insert(2, '/code')
django.setup()

app = dash.Dash()

app.config.supress_callback_exceptions = True

from haystack.query import SearchQuerySet
from citation.models import Publication


def publication_as_dict(p: Publication):
    field_names = ['id', 'container', 'date_published', 'flagged', 'is_archived', 'status', 'tags', 'title']
    result = {}
    for name in field_names:
        result[name] = getattr(p, name)
    return result


publication_df = pd.DataFrame.from_records(
    publication_as_dict(p) for p in SearchQuerySet().models(Publication).filter(is_primary=True))
publication_df['year_published'] = [t.year if t is not None else None for t in publication_df.date_published]

publication_count_by_year_df = publication_df.groupby('year_published')['year_published'].count()
pprint(publication_count_by_year_df)

app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Graph(id='publication-counts-by-year',
              figure=go.Figure(data=[
                  go.Scatter(x=publication_count_by_year_df.index, y=publication_count_by_year_df,
                             mode='lines+markers',
                             name="'linear'",
                             hoverinfo='name',
                             line=dict(
                                 shape='linear'
                             ))
              ]))])

if __name__ == '__main__':
    app.run_server(debug=True, port=8000, host='0.0.0.0')
