from types import SimpleNamespace

import pandas as pd
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from catalog.core.visualization.data_access import create_publication_df


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'visualization-cache-command-tests',
    }
})
class PopulateVisualizationCacheCommandTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_populates_empty_dataframes(self):
        call_command('populate_visualization_cache')

        cached = cache.get_many({
            'authors', 'code_archive_urls', 'platforms', 'publications', 'sponsors'
        })

        self.assertEqual(
            set(cached),
            {'authors', 'code_archive_urls', 'platforms', 'publications', 'sponsors'})
        self.assertEqual(cached['authors'].index.name, 'publication_id')
        self.assertEqual(list(cached['authors'].columns), ['author_id', 'name'])
        self.assertEqual(cached['code_archive_urls'].index.name, 'publication_id')
        self.assertEqual(
            list(cached['code_archive_urls'].columns),
            ['code_archive_url_id', 'category', 'subcategory', 'available'])
        self.assertEqual(cached['publications'].index.name, 'id')
        self.assertEqual(
            list(cached['publications'].columns),
            [
                'container_id', 'container_name', 'date_published', 'year_published',
                'has_available_code', 'has_flow_charts', 'has_math_description', 'has_odd',
                'has_pseudocode', 'status', 'title'
            ])
        self.assertTrue(all(dataframe.empty for dataframe in cached.values()))

    def test_publication_dataframe_preserves_rows(self):
        model_documentation = SimpleNamespace(all=lambda: [])
        publication = SimpleNamespace(
            id=42,
            container=SimpleNamespace(id=7, name='Journal of Modeling'),
            # dateutil cannot parse "SEP-OCT 2007", but Citation persists its year
            date_published=None,
            year_published=2007,
            has_available_code=False,
            model_documentation=model_documentation,
            status='REVIEWED',
            title='A Model Publication',
        )

        dataframe = create_publication_df([publication])

        self.assertEqual(dataframe.index.name, 'id')
        self.assertEqual(dataframe.loc[42, 'container_id'], 7)
        self.assertEqual(dataframe.loc[42, 'year_published'], 2007)
        self.assertEqual(dataframe.loc[42, 'title'], 'A Model Publication')

    def test_clear_replaces_stale_cache_data(self):
        cache.set('publications', 'stale')
        cache.set('stale-derived-value', 'stale')

        call_command('populate_visualization_cache', clear=True)

        self.assertIsInstance(cache.get('publications'), pd.DataFrame)
        self.assertIsNone(cache.get('stale-derived-value'))
