import plotly.graph_objs as go

from django.db import models
from citation.models import Publication, CodeArchiveUrl


def count_graph(records, title):
    labels = [r['label'] for r in records]
    values = [r['count'] for r in records]

    data = [
        go.Bar(
            x=labels,
            y=values
        )
    ]

    layout = go.Layout(
        title=title
    )

    return go.Figure(data=data, layout=layout)


def archive_url_category_graph():
    archive_url_counts = list(CodeArchiveUrl.objects \
                              .filter(publication__in=Publication.api.primary().filter(status='REVIEWED')) \
                              .values('category__category') \
                              .annotate(label=models.F('category__category'))
                              .annotate(count=models.Count('category')))
    return count_graph(records=archive_url_counts, title='Archive URL Category')


def archive_url_status_graph():
    archive_url_status_counts = list(CodeArchiveUrl.objects
                                     .values('status')
                                     .annotate(label=models.F('status'))
                                     .annotate(count=models.Count('status')))
    return count_graph(records=archive_url_status_counts, title='Archive URL Status')


def documentation_type_count_graph():
    documentation_counts = list(Publication.api.primary()
                                .filter(status='REVIEWED')
                                .values('model_documentation__name')
                                .annotate(count=models.Count('model_documentation__name'))
                                .annotate(label=models.F('model_documentation__name'))
                                .exclude(model_documentation__name__in=['AORML', 'Other Narrative', 'None']))
    return count_graph(records=documentation_counts, title='Documentation Type Counts')


def programming_platform_count_graph():
    platform_counts = list(Publication.api.primary()
                           .filter(status='REVIEWED')
                           .values('platforms__name')
                           .annotate(count=models.Count('platforms__name'))
                           .annotate(label=models.F('platforms__name'))
                           .order_by('-count')[:10])

    return count_graph(records=platform_counts, title='Top 10 Platform Counts')
