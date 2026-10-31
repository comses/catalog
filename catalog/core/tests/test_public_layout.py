from unittest import mock

from .common import BaseTest


class PublicLayoutTest(BaseTest):
    @mock.patch("catalog.core.views.PublicationDocSearch")
    def test_public_search_includes_footer(self, publication_search):
        search = (
            publication_search.return_value.find.return_value.__getitem__.return_value
            .agg_by_count.return_value
        )
        results = mock.MagicMock()
        results.hits.total = 0
        results.__iter__.return_value = iter(())
        search.execute.return_value = results
        search.cache = {}

        response = self.get("core:public-search")

        self.assertContains(response, '<footer class="footer', count=1)

    def test_public_home_includes_footer_once(self):
        response = self.get("core:public-home")

        self.assertContains(response, '<footer class="footer', count=1)
