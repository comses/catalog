from unittest import mock

from django.core.cache import cache
from django.test import override_settings

from citation.models import Container, Publication

from .common import BaseTest


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'public-visualization-tests',
    }
})
class PublicVisualizationTest(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.publication = Publication.objects.create(
            title='A model without archived code', added_by=self.user,
            container=Container.objects.create(name='Test journal'),
            date_published_text='2020', status=Publication.Status.REVIEWED,
            is_primary=True,
        )

    def visualization(self, parameters, publication_ids):
        with (
            mock.patch('catalog.core.views.PublicationDocSearch') as publication_search,
            mock.patch('catalog.core.views.data_access.get_publication_pks_matching_search_criteria',
                       return_value=publication_ids),
        ):
            search = (
                publication_search.return_value.find.return_value.__getitem__.return_value
                .agg_by_count.return_value
            )
            search.cache = {}
            return self.get('core:public-visualization', parameters)

    def test_unmatched_search_shows_empty_state(self):
        response = self.visualization({'search': 'asdfasdfasdfasdf'}, [])

        self.assertContains(response, 'Found <b>0</b> matching publications')
        self.assertContains(response, 'No publications match your search and filters.')
        self.assertContains(response, 'value="asdfasdfasdfasdf"')
        self.assertContains(response, '<footer class="footer', count=1)
        self.assertNotContains(response, 'Plotly.newPlot')
        self.assertNotContains(response, 'id=""')

    def test_unmatched_author_filter_shows_empty_state(self):
        response = self.visualization({'authors': '89878', 'search': ''}, [])

        self.assertContains(response, 'No publications match your search and filters.')
        self.assertNotContains(response, 'Plotly.newPlot')

    def test_matching_publication_without_archival_links_renders_charts(self):
        response = self.visualization({'authors': '89878', 'search': ''}, [self.publication.pk])

        self.assertContains(response, 'Found <b>1</b> matching publications')
        self.assertContains(response, 'Plotly.newPlot', count=10)
        self.assertNotContains(response, 'No publications match your search and filters.')
        charts = response.context['plots']
        count_traces = charts['archival_timeseries_count_plot']['data']['data']
        self.assertEqual(len(count_traces), 1)
        self.assertEqual(count_traces[0]['name'], 'Total')
        self.assertEqual(count_traces[0]['y'][list(count_traces[0]['x']).index(2020)], 1)
        self.assertEqual(charts['archival_timeseries_percent_plot']['data']['data'], [])

    def test_empty_catalog_shows_empty_state(self):
        self.publication.delete()

        response = self.visualization({}, [])

        self.assertContains(response, 'No publications match your search and filters.')
        self.assertNotContains(response, 'Plotly.newPlot')
