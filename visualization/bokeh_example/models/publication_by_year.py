import logging

from bokeh.models import ColumnDataSource
from bokeh.plotting import figure
from django.db.models import Count
from django.db.models.functions import ExtractYear
from django_pandas.io import read_frame
from haystack.query import SearchQuerySet

from citation.models import Publication


class PublicationCountsByYear:
    title = 'Publication Added Counts by Year'
    x_axis = 'Year'
    y_axis = 'Publication Added Count'

    def get_filters(self):
        return Publication.api.primary()

    def get_queryset(self):
        return self.get_filters().annotate(year_added=ExtractYear('date_added')) \
            .values('year_added').annotate(n=Count('*')).order_by('year_added')

    def get_dataframe(self):
        return read_frame(self.get_queryset())

    def render(self):
        df = self.get_dataframe()
        ds = ColumnDataSource(df)
        min_year, max_year = df['year_added'][0], df['year_added'][df.index[-1]]
        min_count, max_count = df['n'].min(), df['n'].max()
        p = figure(x_range=(min_year, max_year), y_range=(0, max_count),
                   toolbar_location=None, title=self.title)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = self.x_axis
        p.yaxis.axis_label = self.y_axis
        p.line('year_added', 'n', line_width=3, source=ds)
        return p