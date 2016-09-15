# Test the Metadata Extraction Pipeline Beginning to End

from django.contrib.auth.models import User
from django.db.models import Count
from django.test import TestCase
from ..management.commands.load_bibtex import Command
from .. import models


class TestPipeline(TestCase):
    def test_duplicate_citations(self):
        User.objects.create_user(username='foo', email='a@b.com', password='test')
        cmd = Command()
        cmd.handle(filename="catalog/citation/tests/data/entries_duplicate_citations.json", username='foo')

        primary_publications = [
            'Addressing Population Health and Health Inequalities: The Role of Fundamental Causes'
        ]

        secondary_publications = [
            '10.2105/ajph.2004.037705',
            '10.1177/0011128785031001004'
        ]
        self.assertListEqual(list(p.title for p in models.Publication.objects.filter(is_primary=True)),
                             primary_publications)
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(is_primary=False)),
                             secondary_publications)
        self.assertEqual(models.AuditCommand.objects.count(), 0)

    def test_ingest_different_publication_counts(self):
        User.objects.create_user(username='foo', email='a@b.com', password='test')
        cmd = Command()
        cmd.handle(filename="catalog/citation/tests/data/entries_inconsistent_publication_counts.json", username='foo')

        primary_publications = [
            'Agent-based modeling of hunting and subsistence agriculture on indigenous lands: Understanding interactions between social and ecological systems',
        ]
        secondary_publications = [
            '10.1111/j.1523-1739.2004.00520.x',
            '10.1111/j.1467-8306.2005.00450.x',
        ]

        self.assertListEqual(list(p.title for p in models.Publication.objects.filter(is_primary=True)),
                             primary_publications)

        self.assertEqual(models.AuditCommand.objects.count(), 0)
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(is_primary=False)),
                             secondary_publications)

    def test_duplicate_publications(self):
        User.objects.create_user(username='foo', email='a@b.com', password='test')
        cmd = Command()
        cmd.handle(filename="catalog/citation/tests/data/entries_duplicate_publications.json", username='foo')

        primary_publications = [
            'Agent-based modeling of hunting and subsistence agriculture on indigenous lands: Understanding interactions between social and ecological systems',
        ]
        secondary_publications = [
            '10.1111/j.1523-1739.2004.00520.x'
        ]

        self.assertListEqual(list(p.title for p in models.Publication.objects.filter(is_primary=True)),
                             primary_publications)
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(is_primary=False)),
                             secondary_publications)
        self.assertEqual(models.AuditCommand.objects.count(), 0)

    def test_different_publications_same_citations(self):
        """If a citation if already in the DB, new publications with a matching citation should point to it
        and not add an additional identical citation"""
        User.objects.create_user(username='foo', email='a@b.com', password='test')
        cmd = Command()
        cmd.handle(filename="catalog/citation/tests/data/entries_different_publications_same_citations.json",
                   username='foo')

        primary_publications = [
            'Towards realistic and effective Agent-based models of crowd dynamics',
            'Spatial and temporal dynamics of cell generations within an invasion wave: A link to cell lineage tracing',

        ]

        secondary_publications = [
            '10.2105/ajph.2004.037705'
        ]

        db_primary_publications = models.Publication.objects.annotate(n_citations=Count('citations')).filter(
            is_primary=True)
        self.assertListEqual(list(p.title for p in db_primary_publications),
                             primary_publications)
        self.assertListEqual(list(p.n_citations for p in db_primary_publications),
                             [1, 1])
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(is_primary=False)),
                             secondary_publications)
        self.assertEqual(models.AuditCommand.objects.count(), 0)

    def test_citations_with_duplicates_in_db(self):
        """Make sure that a merge occurs when multiple secondary duplicates are already in the database"""
        creator = User.objects.create_user(username='foo', email='a@b.com', password='test')
        author = models.Author(family_name="Sampson", given_name="RJ")
        author.save()
        author.id = None
        author.save()

        container = models.Container(name="AM J PUBLIC HEALTH")
        container.save()
        container.id = None
        container.save()

        publication = models.Publication(added_by=creator, doi='10.2105/ajph.2004.037705', container=container,
                                         is_primary=False)
        publication.save()
        publication.id = None
        publication.save()

        cmd = Command()
        cmd.handle(filename="catalog/citation/tests/data/entries_different_publications_same_citations.json",
                   username='foo')

        primary_publications = [
            'Towards realistic and effective Agent-based models of crowd dynamics',
            'Spatial and temporal dynamics of cell generations within an invasion wave: A link to cell lineage tracing',

        ]

        secondary_publications = [
            '10.2105/ajph.2004.037705'
        ]

        db_primary_publications = models.Publication.objects.annotate(n_citations=Count('citations')).filter(
            is_primary=True)
        self.assertListEqual(list(p.title for p in db_primary_publications),
                             primary_publications)
        self.assertListEqual(list(p.n_citations for p in db_primary_publications),
                             [1, 1])
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(is_primary=False)),
                             secondary_publications)
        self.assertTrue(models.AuditCommand.objects.count() > 0)

    def test_publication_with_duplicates_in_db(self):
        """Make sure that a merge occurs when multiple secondary duplicates are already in the database"""
        creator = User.objects.create_user(username='foo', email='a@b.com', password='test')
        author = models.Author(family_name="Jaroslaw", given_name="Was")
        author.save()
        author.id = None
        author.save()

        container = models.Container(name="ELSEVIER SCIENCE BV", issn='0925-2312')
        container.save()
        container.id = None
        container.save()

        publication = models.Publication(added_by=creator, doi='10.1016/j.neucom.2014.04.057',
                                         title='Towards realistic and effective Agent-based models of crowd dynamics',
                                         date_published_text='2014',
                                         container=container,
                                         isi='ISI:000347438600035')
        publication.save()
        publication.id = None
        publication.save()

        cmd = Command()
        cmd.handle(filename="catalog/citation/tests/data/entries_different_publications_same_citations.json",
                   username='foo')

        primary_publications = [
            'Towards realistic and effective Agent-based models of crowd dynamics',
            'Spatial and temporal dynamics of cell generations within an invasion wave: A link to cell lineage tracing',
        ]

        secondary_publications = [
            '10.2105/ajph.2004.037705'
        ]

        db_primary_publications = models.Publication.objects.annotate(
            n_citations=Count('citations')).filter(is_primary=True)
        self.assertListEqual(list(p.title for p in db_primary_publications),
                             primary_publications)
        self.assertListEqual(list(p.n_citations for p in db_primary_publications),
                             [1, 1])
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(is_primary=False)),
                             secondary_publications)
        self.assertTrue(models.AuditCommand.objects.count() > 0)
