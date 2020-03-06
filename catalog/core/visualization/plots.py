import pandas as pd
import plotly.graph_objs as go
import plotly.figure_factory as ff

from django.db import models
from django.db.models.functions import Concat
from plotly.subplots import make_subplots

from citation.models import Publication, CodeArchiveUrl, Author


def get_publication_queryset(pks):
    return Publication.api.primary().reviewed().filter(pk__in=pks)


def home_page_plot(publication_df: pd.DataFrame):
    df = publication_df.groupby('year_published') \
        .agg({'year_published': ['count'], 'has_available_code': ['sum', 'mean']}) \
        .reindex(pd.RangeIndex(1990.0, publication_df['year_published'].max() + 1.0), fill_value=0.0)
    year = list(df.index)
    figure = make_subplots(specs=[[{'secondary_y': True}]])
    figure.add_trace(
        go.Bar(
            x=year,
            y=df[('year_published', 'count')].to_list(),
            name='# of Publications'
        ),
        secondary_y=False
    )
    figure.add_trace(
        go.Scatter(
            x=year,
            y=df[('has_available_code', 'mean')].to_list(),
            name='% Code Available'
        ),
        secondary_y=True
    )
    figure.update_layout(
        title_text='Publication Code Availability'
    )
    figure.update_layout(
        legend=go.layout.Legend(
            x=0,
            y=1,
            traceorder="normal",
            font=dict(
                family="sans-serif",
                size=12,
                color="black"
            ),
            borderwidth=1
        )
    )

    figure.update_xaxes(
        title_text='Year'
    )
    figure.update_yaxes(
        title_text='Publication Count',
        secondary_y=False
    )
    figure.update_yaxes(
        title_text='Proportion of Publications with Code',
        range=[0,0.20],
        secondary_y=True
    )
    return figure


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


def programming_platform_count_plot():
    platform_counts = list(Publication.api.primary()
                           .filter(status='REVIEWED')
                           .values('platforms__name')
                           .annotate(count=models.Count('platforms__name'))
                           .annotate(label=models.F('platforms__name'))
                           .order_by('-count')[:10])

    return count_bar_plot(records=platform_counts, title='Most Popular Platforms')


def code_availability_timeseries_plot(publication_df: pd.DataFrame, publication_pks=None):
    if publication_pks is not None:
        publication_df = publication_df.loc[publication_df.index.intersection(publication_pks)]
    df = publication_df.groupby('year_published') \
        .agg({'year_published': ['count'], 'has_available_code': ['sum', 'mean']}) \
        .reindex(pd.RangeIndex(1990.0, publication_df['year_published'].max() + 1.0), fill_value=0.0)
    year = list(df.index)
    count_data = [
        go.Scatter(
            x=year,
            y=df[('has_available_code', 'sum')].to_list(),
            name='Available Code'
        ),
        go.Scatter(
            x=year,
            y=df[('year_published','count')].to_list(),
            name='Total'
        )
    ]
    count_layout = go.Layout(
        legend=go.Legend(orientation='h'),
        title='Publication Code Availability',
        yaxis=go.layout.YAxis(title='Count'),
        xaxis=go.layout.XAxis(title='Year')
    )
    count_figure = go.Figure(data=count_data, layout=count_layout)

    percent_data = [
        go.Scatter(
            x=year,
            y=df[('has_available_code', 'mean')].to_list()
        )
    ]
    percent_layout = go.Layout(
        legend=go.Legend(orientation='h'),
        title='Publication Code Availability (Proportion)',
        yaxis=go.layout.YAxis(title='Proportion'),
        xaxis=go.layout.XAxis(title='Year')
    )
    percent_figure = go.Figure(data=percent_data, layout=percent_layout)

    return {
        'count': count_figure,
        'percent': percent_figure
    }


def archival_timeseries_plot(publication_df: pd.DataFrame, code_archive_urls_df: pd.DataFrame, publication_pks):
    matching_publication_df = publication_df.loc[publication_df.index.intersection(publication_pks)]
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
        name='Total',
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
    year_published_index = pd.RangeIndex(1990.0, publication_df['year_published'].max() + 1.0)
    matching_publication_df = publication_df.reindex(publication_pks)
    df = matching_publication_df \
        .groupby('year_published') \
        .agg({'year_published': ['count'],
              'has_flow_charts': ['mean', 'sum'],
              'has_math_description': ['mean', 'sum'],
              'has_odd': ['mean', 'sum'],
              'has_pseudocode': ['mean', 'sum']}) \
        .rename(columns={'year_published': 'count'}) \
        .reindex(year_published_index, fill_value=0.0)

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
                name='Total'
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
    matching_authors_df = publication_author_df.loc[publication_author_df.index.intersection(publication_pks)]
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
    matching_container_df = container_df.loc[container_df.index.intersection(publication_pks)]
    df = matching_container_df.groupby('container_id') \
             .agg({'container_name': ['first'], 'container_id': ['count']}) \
             .sort_values(by=('container_id', 'count'), ascending=False).iloc[:10]

    data = [
        go.Bar(
            x=df.loc[:, ('container_name', 'first')].to_list(),
            y=df.loc[:, ('container_id', 'count')].to_list(),
        )
    ]

    layout = go.Layout(
        title='Top 10 most published journals',
        yaxis=go.layout.YAxis(title='# of publications')
    )

    return go.Figure(data=data, layout=layout)


def top_platform_plot(publication_platform_df, publication_pks):
    matching_platform_df = publication_platform_df.loc[publication_platform_df.index.intersection(publication_pks)]
    df = matching_platform_df.groupby('platform_id') \
        .agg({'platform_id': ['count'], 'platform_name': ['first']}) \
        .sort_values(by=('platform_id', 'count'), ascending=False).iloc[:10]

    data = [
        go.Bar(
            x=df.loc[:, ('platform_name', 'first')].to_list(),
            y=df.loc[:, ('platform_id', 'count')].to_list()
        )
    ]

    layout = go.Layout(
        title='Top 10 most popular platforms',
        yaxis=go.layout.YAxis(title='# of publications')
    )

    return go.Figure(data=data, layout=layout)


def top_sponsor_plot(publication_sponsor_df, publication_pks):
    matching_sponsor_df = publication_sponsor_df.loc[publication_sponsor_df.index.intersection(publication_pks)]
    df = matching_sponsor_df.groupby('sponsor_id') \
        .agg({'sponsor_id': ['count'], 'sponsor_name': ['first']}) \
        .sort_values(by=('sponsor_id', 'count'), ascending=False).iloc[:10]

    data = [
        go.Bar(
            x=df.loc[:, ('sponsor_name', 'first')].to_list(),
            y=df.loc[:, ('sponsor_id', 'count')].to_list()
        )
    ]

    layout = go.Layout(
        title='Top 10 sponsors',
        yaxis=go.layout.YAxis(title='# of publications')
    )

    return go.Figure(data=data, layout=layout)