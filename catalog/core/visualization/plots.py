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


def code_availability_timeseries_plot(publication_df: pd.DataFrame, publication_pks=None):
    if publication_pks is not None:
        publication_df = publication_df.loc[publication_pks]
    df = publication_df.groupby('year_published') \
        .agg({'year_published': 'count', 'has_available_code': 'sum'}) \
        .rename(columns={'year_published': 'count', 'has_available_code': 'available'})

    data = [
        go.Scatter(
            x=list(df.index),
            y=list(df['count']),
            name='All'
        ),
        go.Scatter(
            x=list(df.index),
            y=list(df['available']),
            name='Available Code'
        )
    ]

    layout = go.Layout(
        legend=go.Legend(orientation='h'),
        title='Publication Code Availability',
        yaxis=go.YAxis(title='Count'),
        xaxis=go.XAxis(title='Year')
    )

    return go.Figure(data=data, layout=layout)


def archival_timeseries_plot(publication_df: pd.DataFrame, code_archive_urls_df: pd.DataFrame, publication_pks):
    matching_publication_df = publication_df.loc[publication_pks]
    year_published_index = pd.RangeIndex(1990.0, publication_df['year_published'].max() + 1.0)
    year_counts_df = matching_publication_df \
        .groupby(['year_published'])[['year_published']] \
        .count() \
        .rename(columns={'year_published': ('publications', 'count')}) \
        .reindex(year_published_index) \
        .fillna(0.0)
    df = matching_publication_df \
        .join(code_archive_urls_df) \
        .groupby(['category', 'year_published'])[['category']] \
        .count() \
        .unstack('category') \
        .reindex(year_published_index) \
        .fillna(0.0) \
        .join(year_counts_df)

    df_percent = df.apply(lambda x: x / x[('publications', 'count')], axis=1)['category'].fillna(0.0)

    year = list(df.index)
    count_data = []
    percent_data = []
    for var_name in df_percent.keys():
        count_data.append(
            go.Scatter(
                x=year,
                y=list(df[('category', var_name)]),
                name=var_name
            )
        )
        percent_data.append(
            go.Scatter(
                x=year,
                y=list(df_percent[var_name]),
                name=var_name
            )
        )
    count_data.append(go.Scatter(
        x=year,
        y=list(df[('publications', 'count')]),
        name='Matched',
        visible='legendonly'
    ))

    count_timeseries = go.Figure(
        data=count_data,
        layout=go.Layout(
            title='Archival Location (Count)',
            xaxis=go.layout.XAxis(title='Year'),
            yaxis=go.layout.YAxis(title='Count')
        )
    )

    percent_timeseries = go.Figure(
        data=percent_data,
        layout=go.Layout(
            title='Archival Location (Proportion)',
            xaxis=go.layout.XAxis(title='Year'),
            yaxis=go.layout.YAxis(title='Proportion')
        )
    )
    return {'count': count_timeseries, 'percent': percent_timeseries}


def documentation_standards_timeseries_plot(publication_df: pd.DataFrame, publication_pks):
    matching_publication_df = publication_df.loc[publication_pks]
    df = matching_publication_df \
        .groupby('year_published') \
        .agg({'year_published': ['count'],
              'has_flow_charts': ['mean', 'sum'],
              'has_math_description': ['mean', 'sum'],
              'has_odd': ['mean', 'sum'],
              'has_pseudocode': ['mean', 'sum']}) \
        .rename(columns={'year_published': 'count'})

    year = list(df.index)

    count_timeseries = go.Figure(
        data=[
            go.Scatter(
                x=year,
                y=list(df[('has_flow_charts', 'sum')]),
                name='Flow Charts'
            ),
            go.Scatter(
                x=year,
                y=list(df[('has_math_description', 'sum')]),
                name='Math Description'
            ),
            go.Scatter(
                x=year,
                y=list(df[('has_odd', 'sum')]),
                name='ODD'
            ),
            go.Scatter(
                x=year,
                y=list(df[('has_pseudocode', 'sum')]),
                name='Pseudocode'
            ),
            go.Scatter(
                x=year,
                y=list(df[('count', 'count')]),
                name='Matched'
            ),
        ],

        layout=go.Layout(
            title='Documentation Techniques and Standards (Count)',
            xaxis=go.layout.XAxis(title='Year'),
            yaxis=go.layout.YAxis(title='Count')
        )
    )

    percent_timeseries = go.Figure(
        data=[
            go.Scatter(
                x=year,
                y=list(df[('has_flow_charts', 'mean')]),
                name='Flow Charts'
            ),
            go.Scatter(
                x=year,
                y=list(df[('has_math_description', 'mean')]),
                name='Math Description'
            ),
            go.Scatter(
                x=year,
                y=list(df[('has_odd', 'mean')]),
                name='ODD'
            ),
            go.Scatter(
                x=year,
                y=list(df[('has_pseudocode', 'mean')]),
                name='Pseudocode'
            )
        ],

        layout=go.Layout(
            title='Documentation Techniques and Standards (Proportion)',
            xaxis=go.layout.XAxis(title='Year'),
            yaxis=go.layout.YAxis(title='Proportion')
        )
    )

    return {'count': count_timeseries, 'percent': percent_timeseries}


def top_author_plot(publication_author_df, publication_pks):
    matching_authors_df = publication_author_df.loc[publication_pks]
    df = matching_authors_df.groupby('author_id') \
             .agg({'name': ['first', 'count']}) \
             .sort_values(by=('name', 'count'), ascending=False).iloc[:10]

    data = [
        go.Bar(
            x=df.loc[:, ('name', 'first')].to_list(),
            y=df.loc[:, ('name', 'count')].to_list(),
        )
    ]

    layout = go.Layout(
        title='Top 10 most published authors',
        yaxis=go.layout.YAxis(title='# of publications')
    )

    return go.Figure(data=data, layout=layout)


def top_journal_plot(container_df, publication_pks):
    matching_container_df = container_df.loc[publication_pks]
    df = matching_container_df.groupby()