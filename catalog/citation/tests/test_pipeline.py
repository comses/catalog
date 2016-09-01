# Test the Metadata Extraction Pipeline Beginning to End

from django.contrib.auth.models import User
from django.test import TestCase
from ..management.commands.load_bibtex import Command
from .. import models


class TestPipeline(TestCase):
    def test_ingest(self):
        user = User.objects.create_user(username='foo', email='a@b.com', password='test')
        cmd = Command()
        cmd.handle(filename="catalog/citation/tests/load_bibtex.json", username='foo')

        # TODO: test actual data instead of just counts.
        self.assertEqual(models.AuditCommand.objects.count(), 23)
        self.assertEqual(models.Publication.objects.count(), 6)
        self.assertEqual(models.Author.objects.count(), 18)
