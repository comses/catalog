import pandas as pd
import plotly.graph_objs as go

from django.db import models
from django.db.models.functions import Concat

from citation.models import Publication, CodeArchiveUrl, Author


def count_bar_plot(records, title, **kwargs):
    labels = [r['label'] for r in records]
    values = [r['count'] for r in records]

    data = [
        go.Bar(
            x=labels,
            y=values,
        )
    ]

    kwargs['yaxis'] = kwargs.get('yaxis', go.layout.YAxis(title='# of Publications'))
    layout = go.Layout(
        title=title,
        **kwargs
    )

    return go.Figure(data=data, layout=layout)


def archive_url_category_plot():
    archive_url_counts = CodeArchiveUrl.objects \
            .filter(publication__in=Publication.api.primary().reviewed()) \
            .annotate(label=
                models.Case(models.When(category__category__in=['Unknown', 'Other'], then=models.Value('Uncategorized')),
                            default=models.F('category__category'))) \
            .values('label') \
            .annotate(count=models.Count('category'))
    return count_bar_plot(records=archive_url_counts, title='Archival Location', yaxis=go.layout.YAxis(title='# of URLs'))


def archive_url_status_plot():
    archive_url_status_counts = list(CodeArchiveUrl.objects
                                     .values('status')
                                     .annotate(label=models.F('status'))
                                     .annotate(count=models.Count('status')))
    return count_bar_plot(records=archive_url_status_counts, title='Archival Status', yaxis=go.layout.YAxis(title='# of URLs'))


def documentation_type_count_graph():
    documentation_counts = list(Publication.api.primary()
                                .filter(status='REVIEWED')
                                .values('model_documentation__name')
                                .annotate(count=models.Count('model_documentation__name'))
                                .annotate(label=models.F('model_documentation__name'))
                                .exclude(model_documentation__name__in=['AORML', 'Other Narrative', 'None']))
    return count_bar_plot(records=documentation_counts, title='Documentation Type Counts')


def most_prolific_authors_plot():
    top_10_authors = Publication.api.primary().reviewed() \
        .values('creators') \
        .annotate(count=models.Count('creators')) \
        .annotate(label=Concat(models.F('creators__given_name'),
                               models.Value(' '),
                               models.F('creators__family_name'))) \
        .order_by('-count')[:10]
    top_10_authors = list(top_10_authors)
    return count_bar_plot(records=top_10_authors, title='Most Prolific Authors')


def programming_platform_count_plot():
    platform_counts = list(Publication.api.primary()
                           .filter(status='REVIEWED')
                           .values('platforms__name')
                           .annotate(count=models.Count('platforms__name'))
                           .annotate(label=models.F('platforms__name'))
                           .order_by('-count')[:10])

    return count_bar_plot(records=platform_counts, title='Most Popular Platforms')


def sponsor_count_plot():
    top_10_sponsors = Publication.api.primary().reviewed() \
        .values('sponsors') \
        .annotate(count=models.Count('sponsors')) \
        .annotate(label=models.F('sponsors__name')) \
        .order_by('-count')[:10]
    top_10_sponsors = list(top_10_sponsors)
    return count_bar_plot(records=top_10_sponsors, title='Largest Sponsors')


def publication_counts_over_time():
    publication_counts = Publication.api.primary().reviewed().annotate_code_availability() \
        .only('id', 'date_published_text')
    publication_counts = [
        {
            'id': p.id,
            'year': p.date_published.year if p.date_published else None,
            'available': p.n_available_code_archive_urls > 0
        } for p in publication_counts
    ]
    df = pd.DataFrame.from_records(publication_counts).groupby('year').agg({
        'id': 'count',
        'available': 'sum'
    })

    data = [
        go.Scatter(
            x=list(df.index),
            y=list(df['id']),
            name='All publications'
        ),
        go.Scatter(
            x=list(df.index),
            y=list(df['available']),
            name='Publications with available code'
        )
    ]

    layout= go.Layout(title='Publications Published Over Time', legend=go.Legend(orientation='h'))

    return go.Figure(data=data, layout=layout)