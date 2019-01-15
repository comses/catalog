from bokeh.models import Legend
from bokeh.palettes import Spectral10
from bokeh.plotting import figure

from data_access import data_cache, IncludedStatistics


def create_chart(query, statistic_indices, publication_count_df):
    p = figure(
        tools='pan,wheel_zoom,save',
        title='Publication Counts By {} Over Time'.format(query.content_type.title()),
        plot_width=800)
    p.outline_line_color = None
    p.grid.grid_line_color = None
    p.xaxis.axis_label = 'Year'
    p.yaxis.axis_label = 'Publication Added Count'
    color_mapper = Spectral10
    api = data_cache.get_model_data_access_api(query.content_type)

    name_legend_items = []
    for i, (related_id, dfg) in enumerate(publication_count_df.groupby('related__id')):
        name = api.get_related_names(related_id)['name']
        r = p.line(
            x=dfg.index.get_level_values('year_published'),
            y=dfg['count'],
            line_width=2,
            color=color_mapper[i])
        name_legend_items.append((name, [r]))
        for statistic_index in statistic_indices:
            statistic_name = IncludedStatistics.names()[statistic_index]
            statistic_style = IncludedStatistics.styles()[statistic_index]
            p.line(
                x=dfg.index.get_level_values('year_published'),
                y=dfg[statistic_name],
                line_width=2,
                color=color_mapper[i],
                line_dash=statistic_style)
    name_legend = Legend(items=name_legend_items, location='top_left')

    line_style_legend_items = []
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
