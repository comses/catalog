from bokeh.models import ColumnDataSource
from bokeh.plotting import figure
from data_wrangling import data_cache

from citation.models import Publication


class PublicationCountsByYear:
    title = 'Publication Added Counts by Year'
    x_axis = 'Year'
    y_axis = 'Publication Added Count'

    def get_dataframe(self):
        return data_cache.publication_df

    def render(self):
        df = self.get_dataframe()
        ds = ColumnDataSource(df)
        min_year, max_year = df['year_published'].min(), df['year_published'].max()
        min_count, max_count = df['n'].min(), df['n'].max()
        p = figure(x_range=(min_year, max_year), y_range=(0, max_count),
                   toolbar_location=None, title=self.title)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = self.x_axis
        p.yaxis.axis_label = self.y_axis
        p.line('year_added', 'n', line_width=3, source=ds)
        return p