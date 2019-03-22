import pandas as pd
import plotly.graph_objs as go
import plotly.figure_factory as ff


from django.db import models
from django.db.models.functions import Concat

from citation.models import Publication, CodeArchiveUrl, Author


def get_publication_queryset(pks):
    return Publication.api.primary().reviewed().filter(pk__in=pks)


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
    models.Case(
        models.When(category__category__in=['Unknown', 'Other'], then=models.Value('Uncategorized')),
        default=models.F('category__category'))) \
        .values('label') \
        .annotate(count=models.Count('category'))
    return count_bar_plot(records=archive_url_counts, title='Archival Location',
                          yaxis=go.layout.YAxis(title='# of URLs'))


def archive_url_status_plot():
    archive_url_status_counts = list(CodeArchiveUrl.objects
                                     .values('status')
                                     .annotate(label=models.F('status'))
                                     .annotate(count=models.Count('status')))
    return count_bar_plot(records=archive_url_status_counts, title='Archival Status',
                          yaxis=go.layout.YAxis(title='# of URLs'))


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


def publication_counts_over_time(publication_df: pd.DataFrame):
    df = publication_df.groupby('year_published') \
        .agg({'year_published': 'count', 'has_available_code': 'sum'}) \
        .rename(columns={'year_published': 'count', 'has_available_code': 'available'})

    data = [
        go.Scatter(
            x=list(df.index),
            y=list(df['count']),
            name='All publications'
        ),
        go.Scatter(
            x=list(df.index),
            y=list(df['available']),
            name='Publications with available code'
        )
    ]

    layout = go.Layout(
        legend=go.Legend(orientation='h'),
        title='Publications',
        yaxis=go.YAxis(title='Count'),
        xaxis=go.XAxis(title='Year')
    )

    return go.Figure(data=data, layout=layout)


def archival_timeseries_plot(publication_df: pd.DataFrame, code_archive_urls_df: pd.DataFrame, publication_pks):
    matching_publication_df = publication_df.loc[publication_pks].join(code_archive_urls_df)
    df = matching_publication_df \
        .groupby(['year_published', 'category'])['category'] \
        .count() \
        .unstack('category') \
        .fillna(0.0)

    year = list(df.index)
    data = []
    for var_name, var in df.items():
        data.append(
            go.Scatter(
                x=year,
                y=list(var),
                name=var_name
            )
        )

    layout = go.Layout(
        title='Archival Location',
        xaxis=go.layout.XAxis(title='Year'),
        yaxis=go.layout.YAxis(title='Count')
    )
    return go.Figure(data=data, layout=layout)


def documentation_standards_timeseries_plot(publication_df: pd.DataFrame, publication_pks):
    matching_publication_df = publication_df.loc[publication_pks]
    df = matching_publication_df \
        .groupby('year_published') \
        .agg({'year_published': 'count',
              'has_flow_charts': 'sum',
              'has_math_description': 'sum',
              'has_odd': 'sum',
              'has_pseudocode': 'sum'}) \
        .rename(columns={'year_published': 'count'})


    year = list(df.index)
    data = [
        go.Scatter(
            x=year,
            y=list(df['count']),
            name='All Publications'
        ),
        go.Scatter(
            x=year,
            y=list(df['has_flow_charts']),
            name='Flow Charts'
        ),
        go.Scatter(
            x=year,
            y=list(df['has_math_description']),
            name='Math Description'
        ),
        go.Scatter(
            x=year,
            y=list(df['has_odd']),
            name='ODD'
        ),
        go.Scatter(
            x=year,
            y=list(df['has_pseudocode']),
            name='Pseudocode'
        )
    ]

    layout = go.Layout(
        title='Documentation Standards',
        xaxis=go.layout.XAxis(title='Year'),
        yaxis=go.layout.YAxis(title='Count')
    )

    return go.Figure(
        data=data,
        layout=layout
    )