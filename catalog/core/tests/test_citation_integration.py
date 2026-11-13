from pathlib import Path

from django.apps import apps
from django.core.management import get_commands
from django.test import SimpleTestCase

import citation.apps


class CitationIntegrationTest(SimpleTestCase):
    def test_management_commands_are_discovered_from_nested_checkout(self):
        app_config = apps.get_app_config('citation')

        self.assertEqual(
            Path(app_config.path),
            Path(citation.apps.__file__).resolve().parent,
        )
        self.assertIn('cache_data', get_commands())
