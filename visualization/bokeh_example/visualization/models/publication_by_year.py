import itertools
import logging

import pandas as pd
from bokeh.colors import RGB
from bokeh.layouts import column, widgetbox
from bokeh.models import Select
from bokeh.plotting import figure
from django_pandas.io import read_frame

from citation.models import Publication, PublicationPlatforms, PublicationAuthors, PublicationSponsors
from widgets.vue_multiselect import VueMultiselectWidget

logger = logging.getLogger(__name__)


def publication_as_dict(p: Publication):
    return {'id': p.id,
            'container': p.container.id,
            'date_published': p.date_published,
            'year_published': p.date_published.year if p.date_published is not None else None,
            'flagged': p.flagged,
            'is_archived': p.is_archived,
            'status': p.status,
            'title': p.title}


reviewed_primary_publications = Publication.api.primary().filter(status='REVIEWED')

publication_df = pd.DataFrame.from_records([publication_as_dict(p) for p in
                                            reviewed_primary_publications
                                           .select_related('container')], index='id')
publication_df.rename(index=str, columns={'id': 'publication__id'}, inplace=True)
publication_df.year_published = publication_df.year_published.astype('category')

publication_authors_df = read_frame(PublicationAuthors.objects.filter(publication__in=reviewed_primary_publications),
                                    fieldnames=['publication__id', 'author__id'], index_col='publication__id')
publication_authors_df.rename(index=str, columns={'author__id': 'author'}, inplace=True)

publication_platforms_df = read_frame(PublicationPlatforms.objects.filter(publication__in=reviewed_primary_publications),
                                      fieldnames=['publication__id', 'platform__id'], index_col='publication__id')
publication_platforms_df.rename(index=str, columns={'platform__id': 'platform'}, inplace=True)

publication_sponsor_df = read_frame(PublicationSponsors.objects.filter(publication__in=reviewed_primary_publications),
                                    fieldnames=['publication__id', 'sponsor__id'], index_col='publication__id')
publication_sponsor_df.rename(index=str, columns={'sponsor__id': 'sponsor'}, inplace=True)


class ColorStreamIterator:
    def __init__(self, size):
        levels = range(0, 256, 255//size)
        self.iterator = iter(filter(lambda rgb: any(c > 31 for c in rgb), itertools.product(levels, levels, levels)))

    def __next__(self):
        color = RGB(*next(self.iterator))
        return color


class ColorStream:
    def __init__(self, size):
        self.size = size

    def __iter__(self):
        return ColorStreamIterator(self.size)



class PublicationCountsByYear:
    title = 'Publication Added Counts by Year'
    x_axis = 'Year'
    y_axis = 'Publication Added Count'

    DEFAULT_MODEL_NAME = 'none'
    NONE_LABEL = 'All publications'

    model_name_lookup = {
        'author': publication_authors_df,
        'platform': publication_platforms_df,
        'sponsor': publication_sponsor_df
    }

    def __init__(self):
        self.selected_options_widget = VueMultiselectWidget(selectedOptions=[])
        self.model_name_widget = Select(title='Model Name', value='none',
                                        options=['none', 'author', 'container', 'platform', 'sponsor'])
        self.selected_options_widget.on_change('selectedOptions', lambda attr, old, new: self.render_plot())
        self.model_name_widget.on_change('value', lambda attr, old, new: self.clear_options())
        self.layout = column(widgetbox(self.model_name_widget,
                                       self.selected_options_widget, width=800),
                             self.create_plot())

    def create_plot(self):
        df = self.create_dataset(modelName=self.model_name_widget.value,
                                 selectedOptions=self.selected_options_widget.selectedOptions)
        p = figure(tools='pan,wheel_zoom,save', title=self.title, plot_width=800)
        p.outline_line_color = None
        p.grid.grid_line_color = None
        p.xaxis.axis_label = self.x_axis
        p.yaxis.axis_label = self.y_axis
        logger.info(df)
        grouped = df.groupby('group')
        logger.info(grouped.groups)
        cs = itertools.cycle(ColorStream(1))
        for color, (name, dfg) in zip(cs, df.groupby('group')):
            logger.info('name: %s', name)
            logger.info(dfg)
            p.line(x=dfg.year_published, y=dfg['count'], legend=name, line_width=2, color=color)
            p.line(x=dfg.year_published, y=dfg.is_archived, legend='{} (Archived)'.format(name), line_width=2, color=color, line_dash='dashed')
        return p

    def clear_options(self):
        modelName = self.model_name_widget.value
        self.selected_options_widget.selectedOptions = []
        self.selected_options_widget.options = []
        self.selected_options_widget.modelName = modelName
        self.render_plot()

    def render_plot(self):
        self.layout.children[1] = self.create_plot()

    @staticmethod
    def build_dense_year_published_df(df, modelName='none'):
        groupings = ['year_published']
        if modelName is not 'none':
            groupings.append(modelName)
        df_count = df.groupby(groupings)[['title']].count()
        df_is_archived = df.groupby(groupings)[['is_archived']].sum()
        result_df = df_count.join(df_is_archived)
        result_df.rename(index=str, columns={'title': 'count'}, inplace=True)
        result_df.fillna(0, inplace=True)
        result_df.reset_index(inplace=True)
        return result_df

    @classmethod
    def create_dataset(cls, modelName, selectedOptions):
        logger.info('selectedOptions: %s', selectedOptions)
        logger.info('modelName: %s', modelName)
        if modelName == 'none' or not selectedOptions:
            grouped = publication_df.groupby(['year_published'])
            df = (grouped[['title']].count()).join(grouped[['is_archived']].sum())
            df.rename(index=str, columns={'title': 'count'}, inplace=True)
            df.fillna(0, inplace=True)
            df.reset_index(inplace=True)
            df['group'] = 'All publications'
            return df

        pks = [o['value'] for o in selectedOptions]

        if modelName == 'container':
            df = publication_df.loc[publication_df[modelName].isin(pks)]
        else:
            related_df = cls.model_name_lookup[modelName]
            related_df = related_df.loc[related_df[modelName].isin(pks)]
            df = publication_df.join(related_df, how='inner')

        df = cls.build_dense_year_published_df(df, modelName)
        df.rename(index=str, columns={modelName: 'group'}, inplace=True)
        df['group'] = df['group'].astype('int')
        label_lookup = {o['value']: o['label'] for o in selectedOptions}
        df['group'] = [label_lookup[pk] for pk in df['group']]
        return df

    def render(self):
        return self.layout
