#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

import dash
import dash_core_components as dcc
import dash_html_components as html
import django
from dash.dependencies import Output, Input

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "catalog.settings")
sys.path.insert(2, '/code')
sys.path.insert(3, '/code/visualization/util')
django.setup()

from common import app
from publication_counts_archival_status import publication_archived_status

app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Markdown('''# Agent Based Modeling Bibliographic Visualization
    '''),
    publication_archived_status([])])

if __name__ == '__main__':
    app.run_server(debug=True, port=8000, host='0.0.0.0')
