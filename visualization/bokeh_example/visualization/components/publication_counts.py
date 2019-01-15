from bokeh.models import Legend
from bokeh.palettes import Spectral10
from bokeh.plotting import figure

from data_access import data_cache, IncludedStatistics


def create_chart(statistic_indices, publication_count_df):
    p = figure(
        tools='pan,wheel_zoom,save',
        title='Publication Counts Over Time',
        plot_width=800)
    p.outline_line_color = None
    p.grid.grid_line_color = None
    p.xaxis.axis_label = 'Year'
    p.yaxis.axis_label = 'Publication Added Count'
    color_mapper = Spectral10

    name_legend_items = []

    all_publication_df = publication_count_df[publication_count_df.group == 'all']
    all_publications_line = p.line(
        x=all_publication_df.index.get_level_values('year_published'),
        y=all_publication_df['count'],
        line_width=2,
        color=color_mapper[0])
    name_legend_items.append(('All publications', [all_publications_line]))

    matched_publication_df = publication_count_df[publication_count_df.group == 'matched']
    matched_publications_line = p.line(
        x=matched_publication_df.index.get_level_values('year_published'),
        y=matched_publication_df['count'],
        line_width=2,
        color=color_mapper[1])
    name_legend_items.append(('Matching publications', [matched_publications_line]))

    name_legend = Legend(items=name_legend_items, location='top_left')

    line_style_legend_items = []
    for statistic_index in statistic_indices:
        statistic_name = IncludedStatistics.names()[statistic_index]
        statistic_style = IncludedStatistics.styles()[statistic_index]
        p.line(
            x=all_publication_df.index.get_level_values('year_published'),
            y=all_publication_df[statistic_name],
            line_width=2,
            color=color_mapper[0],
            line_dash=statistic_style)

    for statistic_index in statistic_indices:
        statistic_name = IncludedStatistics.names()[statistic_index]
        statistic_style = IncludedStatistics.styles()[statistic_index]
        p.line(
            x=matched_publication_df.index.get_level_values('year_published'),
            y=matched_publication_df[statistic_name],
            line_width=2,
            color=color_mapper[1],
            line_dash=statistic_style)

    for statistic_index in statistic_indices:
        statistic_label = IncludedStatistics.labels()[statistic_index]
        statistic_style = IncludedStatistics.styles()[statistic_index]
        r = p.line(x=[], y=[], line_width=2, color='black',
                   line_dash=statistic_style)  # Fake glyphs for rendering styles
        line_style_legend_items.append((statistic_label, [r]))
    line_style_legend = Legend(items=line_style_legend_items, location='top_right')

    p.add_layout(name_legend)
    p.add_layout(line_style_legend)
    return p
