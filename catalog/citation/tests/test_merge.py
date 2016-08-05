from django.contrib.auth.models import User
from django.test import TestCase
from .. import models, merger


class TestMergers(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', email='a@b.com', password='test')
        self.audit_command = models.AuditCommand.objects.create(
            creator=self.user,
            action='merge',
            role=models.AuditCommand.Role.CURATOR_EDIT)

        self.container_jasss = models.Container.objects.create(type='journal', issn='')
        self.container_alias_jasss = models.ContainerAlias.objects.create(name='jasss', container=self.container_jasss)
        self.container_jasss_copy = models.Container.objects.create(type='journal', issn='')
        self.container_alias_jasss_copy = models.ContainerAlias.objects.create(
            name='jasss',
            container=self.container_jasss_copy)

        self.author_bob = models.Author.objects.create(type='INDIVIDUAL', orcid='', primary_given_name='Bob',
                                                       primary_family_name='Smith')
        self.author_alias_bob = models.AuthorAlias.objects.create(author=self.author_bob, given_name='Bob',
                                                                  family_name='Smith')
        self.author_bob_copy = models.Author.objects.create(type='INDIVIDUAL', orcid='', primary_given_name='Bob',
                                                            primary_family_name='Smith')
        self.author_alias_bob_copy = models.AuthorAlias.objects.create(author=self.author_bob_copy, given_name='Bob',
                                                                       family_name='Smith')

        self.publication_foo = models.Publication.objects.create(
            title='''Agent-based modeling of hunting and subsistence agriculture on indigenous lands:
            Understanding interactions between social and ecological systems''',
            date_published_text='2014',
            abstract='',
            container=self.container_jasss,
            added_by=self.user)
        self.publication_foo_copy = models.Publication.objects.create(
            title='''Agent-based modeling of hunting and subsistence agriculture on indigenous lands:
            Understanding interactions between social and ecological systems''',
            date_published_text='2014',
            abstract='',
            container=self.container_jasss_copy,
            added_by=self.user)

        self.raw = models.Raw.objects.create(key=models.Raw.BIBTEX_ENTRY, value={},
                                             container=self.container_jasss,
                                             publication=self.publication_foo)
        self.raw_copy = models.Raw.objects.create(key=models.Raw.BIBTEX_ENTRY, value={},
                                                  container=self.container_jasss_copy,
                                                  publication=self.publication_foo_copy)

        models.PublicationAuthors.objects.create(author=self.author_bob, publication=self.publication_foo)
        models.PublicationAuthors.objects.create(author=self.author_bob_copy, publication=self.publication_foo_copy)

        models.RawAuthors.objects.create(author=self.author_bob, raw=self.raw)
        models.RawAuthors.objects.create(author=self.author_bob_copy, raw=self.raw_copy)

    def test_container_merge(self):
        mergeset = merger.create_container_mergeset_by_name()
        self.assertEqual(len(mergeset), 1)
        self.assertEqual(len(mergeset[0]), 2)

        merger.merge_containers(mergeset, self.audit_command)
        self.assertEqual(models.Container.objects.count(), 1)
        self.assertEqual(models.ContainerAlias.objects.count(), 1)

    def test_author_merge(self):
        mergeset = merger.create_author_mergeset_by_name()
        self.assertEqual(len(mergeset), 1)
        self.assertEqual(len(mergeset[0]), 2)

        merger.merge_authors(mergeset, self.audit_command)
        self.assertEqual(models.Author.objects.count(), 1)
        self.assertEqual(models.AuthorAlias.objects.count(), 1)
        self.assertEqual(models.AuthorAlias.objects.first().raw.count(), 2)

    def test_publication_merge(self):
        mergeset = merger.create_publication_mergeset_by_titles()
        self.assertEqual(len(mergeset), 1)
        self.assertEqual(len(mergeset[0]), 2)

        merger.merge_publications(mergeset, self.audit_command)
        self.assertEqual(models.Publication.objects.count(), 1)
