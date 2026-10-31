import pandas as pd
from django.test import SimpleTestCase

from catalog.core.visualization.plots import archival_timeseries_plot, top_sponsor_plot, two_line_label


class TopTenBarPlotTest(SimpleTestCase):
    def test_ranks_long_names_as_labeled_horizontal_bars(self):
        long_name = 'Australian National Health and Medical Research Council'
        sponsor_df = pd.DataFrame.from_records([
            {'publication_id': 1, 'sponsor_id': 10, 'sponsor_name': long_name},
            {'publication_id': 2, 'sponsor_id': 10, 'sponsor_name': long_name},
            {'publication_id': 2, 'sponsor_id': 20, 'sponsor_name': 'NSF'},
        ]).set_index('publication_id')

        figure = top_sponsor_plot(sponsor_df, [1, 2])

        bar = figure.data[0]
        yaxis = figure.layout.yaxis
        self.assertEqual(bar.orientation, 'h')
        self.assertEqual(list(bar.x), [2, 1])
        self.assertEqual(list(bar.y), [0, 1])
        self.assertEqual(list(bar.hovertext), [long_name, 'NSF'])
        self.assertEqual(list(yaxis.tickvals), [0, 1])
        self.assertEqual(yaxis.ticktext[0].replace('<br>', ' '), long_name)
        self.assertEqual(yaxis.autorange, 'reversed')
        self.assertEqual(figure.layout.xaxis.dtick, 1)

    def test_labels_are_capped_at_two_lines(self):
        label = two_line_label('National Centre for Epidemiology and Population Health, Australian National University')

        lines = label.split('<br>')
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].endswith('…'))
        self.assertTrue(all(len(line) <= 28 for line in lines))


class ArchivalTimeseriesPlotTest(SimpleTestCase):
    def test_combines_archive_categories_with_publication_totals(self):
        publication_df = pd.DataFrame.from_records([
            {'id': 1, 'year_published': 2020},
            {'id': 2, 'year_published': 2020},
            {'id': 3, 'year_published': 2021},
        ]).set_index('id')
        archive_df = pd.DataFrame.from_records([
            {'publication_id': 1, 'category': 'Archive'},
            {'publication_id': 2, 'category': 'Repository'},
        ]).set_index('publication_id')

        result = archival_timeseries_plot(publication_df, archive_df, [1, 2])

        count_traces = {trace.name: trace for trace in result['count'].data}
        year_2020 = list(count_traces['Total'].x).index(2020)
        self.assertEqual(count_traces['Archive'].y[year_2020], 1)
        self.assertEqual(count_traces['Repository'].y[year_2020], 1)
        self.assertEqual(count_traces['Total'].y[year_2020], 2)
