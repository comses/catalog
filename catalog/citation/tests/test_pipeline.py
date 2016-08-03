# Test the Metadata Extraction Pipeline Beginning to End

from django.contrib.auth.models import User
from django.test import TestCase
from ..management.commands.load_bibtex import Command
from .. import models


class TestPipeline(TestCase):
    def test_ingest(self):
        user = User.objects.create_user(username='foo', email='a@b.com', password='test')
        cmd = Command()
        cmd.handle(file_name="catalog/citation/tests/load_bibtex.json", user_name='foo')

        self.assertEqual(models.AuditCommand.objects.count(), 23)
        self.assertEqual(models.Publication.objects.count(), 5)
        self.assertEqual(models.Author.objects.count(), 15)
