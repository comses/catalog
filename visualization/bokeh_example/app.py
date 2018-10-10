#!/usr/bin/env python3
import os
import pprint
import sys

import django
from bokeh.command.util import build_single_handler_application
from bokeh.embed import server_document
from bokeh.server.server import Server
from django.apps import apps
from django.db.models import Q
from flask import Flask, abort, render_template, request, jsonify
from tornado.ioloop import IOLoop

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "catalog.settings")
sys.path.insert(2, '/code')
sys.path.insert(3, '/code/visualization/util')
pprint.pprint(sys.path)
django.setup()

from haystack.query import SearchQuerySet
from citation.models import Author, Container, Platform, Sponsor, Tag, Publication

app = Flask(__name__)


@app.route('/autocomplete/<string:model_name>')
def autocomplete(model_name):
    model_names = [m._meta.model_name for m in [Author, Container, Platform, Sponsor, Tag]]
    if model_name not in model_names:
        abort(404)
    model = apps.get_model('citation', model_name)

    q = request.args.get('q')
    if model == Container:
        containers = Container.objects.filter(id__in=Publication.api.primary().values_list('container', flat=True))
        if q:
            containers = containers.filter(Q(name__iregex=q) | Q(issn__iexact=q))
        return jsonify([dict(value=c.pk, label=c.name) for c in containers[:20]])

    search_results = SearchQuerySet().models(model).order_by('name')
    if q:
        search_results = search_results.autocomplete(name=q)
    pks = [int(pk) for pk in search_results.values_list('pk', flat=True)]
    results = model.objects.filter(pk__in=pks)[:20]
    return jsonify([dict(value=r.pk, label=r.name) for r in results])


@app.route('/', methods=['GET'])
def visualization_page():
    script = server_document('http://localhost:5006/visualization')
    return render_template('embed.html', script=script, template='Flask')


def bk_worker():
    # path = os.path.abspath('visualization')
    visualization = build_single_handler_application('visualization')
    server = Server({'/visualization': visualization}, io_loop=IOLoop(), allow_websocket_origin=['localhost:8001'],
                    address='0.0.0.0')
    server.start()
    server.io_loop.start()


from threading import Thread

Thread(target=bk_worker).start()

if __name__ == '__main__':
    app.run(port=8001, host='0.0.0.0', debug=True)
