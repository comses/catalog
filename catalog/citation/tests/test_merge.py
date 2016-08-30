from django.contrib.auth.models import User
from django.test import TestCase
from .. import models, merger
import copy


def sort_by_id(instance):
    return instance.id


class MetadataObjectGraph:
    """A self contained object graph. Copying the object graph requires that no object references an object outside the
    the object graph
    """

    def __init__(self,
                 user,
                 containers, container_aliases,
                 authors, author_aliases,
                 publications,
                 raws,
                 publication_authors,
                 publication_citations):

        containers.sort(key=sort_by_id)
        container_aliases.sort(key=sort_by_id)
        authors.sort(key=sort_by_id)
        author_aliases.sort(key=sort_by_id)
        publications.sort(key=sort_by_id)
        raws.sort(key=sort_by_id)

        self.user = user
        self.containers = containers
        self.container_aliases = container_aliases
        self.authors = authors
        self.author_aliases = author_aliases
        self.publications = publications
        self.raws = raws
        self.publication_authors = publication_authors
        self.publication_citations = publication_citations

    def copy_containers(self):
        new_containers = []
        for container in self.containers:
            new_container = copy.copy(container)
            new_container.id = None
            new_container.save()
            new_containers.append(new_container)
        return new_containers

    def copy_container_aliases(self, new_containers):
        new_container_aliases = []
        for container_alias in self.container_aliases:
            new_container_alias = copy.copy(container_alias)
            container = new_container_alias.container
            new_container = new_containers[self.containers.index(container)]
            new_container_alias.id = None
            new_container_alias.container = new_container
            new_container_alias.save()
            new_container_aliases.append(new_container_alias)

        return new_containers

    def copy_authors(self):
        new_authors = []
        for author in self.authors:
            new_author = copy.copy(author)
            new_author.id = None
            new_author.save()
            new_authors.append(new_author)
        return new_authors

    def copy_author_aliases(self, new_authors):
        new_author_aliases = []
        for author_alias in self.author_aliases:
            new_author_alias = copy.copy(author_alias)
            author = author_alias.author
            new_author = new_authors[self.authors.index(author)]
            new_author_alias.id = None
            new_author_alias.author = new_author
            new_author_alias.save()
            new_author_aliases.append(new_author_alias)
        return new_author_aliases

    def copy_publications(self, new_user, new_containers):
        new_publications = []
        for publication in self.publications:
            container = publication.container
            new_container = new_containers[self.containers.index(container)]

            new_publication = copy.copy(publication)
            new_publication.id = None
            new_publication.added_by = new_user
            new_publication.container = new_container
            new_publication.save()
            new_publications.append(new_publication)
        return new_publications

    def copy_raws(self, new_publications, new_containers, new_authors):
        new_raws = []
        new_raw_authors = []
        for raw in self.raws:
            publication = raw.publication
            new_publication = new_publications[self.publications.index(publication)]

            container = raw.container
            new_container = new_containers[self.containers.index(container)]

            new_raw = copy.copy(raw)
            new_raw.id = None
            new_raw.publication = new_publication
            new_raw.container = new_container
            new_raw.save()
            new_raws.append(new_raw)

            authors = raw.authors.all()
            for author in authors:
                new_author = new_authors[self.authors.index(author)]
                models.RawAuthors.objects.create(author=new_author, raw=new_raw)

        return new_raws, new_raw_authors

    def copy_publication_authors(self, new_publications, new_authors):
        new_publication_authors = []
        for publication_author in self.publication_authors:
            publication = publication_author.publication
            new_publication = new_publications[self.publications.index(publication)]

            author = publication_author.author
            new_author = new_authors[self.authors.index(author)]

            new_publication_author = copy.copy(publication_author)
            new_publication_author.id = None
            new_publication_author.publication = new_publication
            new_publication_author.author = new_author
            new_publication_author.save()

            new_publication_authors.append(new_publication_author)

        return new_publication_authors

    def copy_publication_citations(self, new_publications):
        new_publication_citations = []
        for publication_citation in self.publication_citations:
            publication = publication_citation.publication
            new_publication = new_publications[self.publications.index(publication)]

            citation = publication_citation.citation
            new_citation = new_publications[self.publications.index(citation)]

            new_publication_citation = copy.copy(publication_citation)
            new_publication_citation.id = None
            new_publication_citation.publication = new_publication
            new_publication_citation.citation = new_citation
            new_publication_citation.save()

            new_publication_citations.append(new_publication_citation)

        return new_publication_citations

    def __deepcopy__(self, memo):
        new_user = self.user
        new_containers = self.copy_containers()
        new_container_aliases = self.copy_container_aliases(new_containers)
        new_authors = self.copy_authors()
        new_author_aliases = self.copy_author_aliases(new_authors)
        new_publications = self.copy_publications(new_user, new_containers)
        new_raws, new_raw_authors = self.copy_raws(new_publications, new_containers, new_authors)
        new_publication_authors = self.copy_publication_authors(new_publications, new_authors)
        new_publication_citations = self.copy_publication_citations(new_publications)

        return MetadataObjectGraph(
            user=new_user,
            containers=new_containers,
            container_aliases=new_container_aliases,
            authors=new_authors,
            author_aliases=new_author_aliases,
            publications=new_publications,
            raws=new_raws,
            publication_authors=new_publication_authors,
            publication_citations=new_publication_citations)


def create_publication(user=None):
    if not user:
        user = User.objects.create_user(username='user', email='a@b.com', password='test')
    container_jasss = models.Container.objects.create(type='journal', issn='')
    container_alias_jasss = models.ContainerAlias.objects.create(name='jasss', container=container_jasss)

    author_bob = models.Author.objects.create(type='INDIVIDUAL', orcid='', given_name='Bob',
                                              family_name='Smith')
    author_alias_bob = models.AuthorAlias.objects.create(author=author_bob, given_name='Robert',
                                                         family_name='Smith')
    publication = models.Publication.objects.create(
        title='''Agent-based modeling of hunting and subsistence agriculture on indigenous lands:
        Understanding interactions between social and ecological systems''',
        date_published_text='2014',
        abstract='',
        container=container_jasss,
        added_by=user)
    raw = models.Raw.objects.create(key=models.Raw.BIBTEX_ENTRY, value={},
                                    container=container_jasss,
                                    publication=publication)

    publication_author = models.PublicationAuthors.objects.create(author=author_bob, publication=publication)
    models.RawAuthors.objects.create(author=author_bob, raw=raw)

    return MetadataObjectGraph(
        user=user,
        containers=[container_jasss],
        container_aliases=[container_alias_jasss],
        authors=[author_bob],
        author_aliases=[author_alias_bob],
        publications=[publication],
        raws=[raw],
        publication_authors=[publication_author],
        publication_citations=[])


class TestMergers(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', email='a@b.com', password='test')
        self.audit_command = models.AuditCommand.objects.create(
            creator=self.user,
            action='merge')
        self.object_graph = create_publication(self.user)
        self.object_graph_copy = copy.deepcopy(self.object_graph)

    def test_merge_group_set_protocol(self):
        """Users should be prevented from merging before determining that the merge is valid"""
        merge_group_set = merger.PublicationMergeGroup.from_list(list(models.Publication.objects.all()))
        with self.assertRaises(AssertionError):
            merge_group_set.merge(self.audit_command)

    def test_container_merge(self):
        merge_group = merger.ContainerMergeGroup.from_list(list(models.Container.objects.all()))
        self.assertEqual(len(merge_group), 2)

        self.assertTrue(merge_group.is_valid())
        merge_group.merge(self.audit_command)
        self.assertEqual(models.Container.objects.count(), 1)
        self.assertEqual(models.ContainerAlias.objects.count(), 1)

    def test_author_merge(self):
        """Identical authors should not create additional author aliases when merged"""
        merge_group = merger.AuthorMergeGroup.from_list(list(models.Author.objects.all()))
        self.assertEqual(len(merge_group), 2)

        self.assertTrue(merge_group.is_valid())
        merge_group.merge(self.audit_command)
        self.assertEqual(models.Author.objects.first().raw.count(), 2)
        self.assertEqual(models.Author.objects.count(), 1)
        self.assertEqual(models.AuthorAlias.objects.count(), 1)

    def test_author_merge_different_aliases(self):
        """Authors with identical names but different aliases should result in the aliases moving to the final author"""
        merge_group = merger.AuthorMergeGroup.from_list(list(models.Author.objects.all()))
        self.assertEqual(len(merge_group), 2)
        author_alias = self.object_graph_copy.author_aliases[0]
        author_alias.given_name = 'Rob'
        author_alias.save()

        self.assertTrue(merge_group.is_valid())
        merge_group.merge(self.audit_command)
        self.assertEqual(models.Author.objects.first().raw.count(), 2)
        self.assertEqual(models.Author.objects.count(), 1)
        self.assertEqual(models.AuthorAlias.objects.count(), 2)

    def test_author_merge_different_authors(self):
        """With different auth names in the same mergeset the secondary authors should be turned in author aliases"""
        author = self.object_graph_copy.authors[0]
        author.given_name = 'Rob'
        author.save()

        merge_group = merger.AuthorMergeGroup.from_list(list(models.Author.objects.all()))
        self.assertEqual(len(merge_group), 2)

        self.assertTrue(merge_group.is_valid())
        merge_group.merge(self.audit_command)
        self.assertEqual(models.Author.objects.first().raw.count(), 2)
        self.assertEqual(models.Author.objects.count(), 1)
        self.assertEqual(models.AuthorAlias.objects.count(), 2)

    def test_publication_merge_same(self):
        """Identical publications should be merged successfully"""
        merge_group = merger.PublicationMergeGroup.from_list(list(models.Publication.objects.all()))
        self.assertEqual(len(merge_group), 2)

        self.assertTrue(merge_group.is_valid())
        merge_group.merge(self.audit_command)
        self.assertEqual(models.Publication.objects.count(), 1)

    def test_authoritative_author_merge_outside_publications(self):
        """Authors referencing publications outside their merge group is permitted"""
        all_publications = list(models.Publication.objects.all())
        publication = self.object_graph.publications[0]
        publication.id = None
        publication.save()

        author = self.object_graph.authors[0]
        models.PublicationAuthors.objects.create(publication=publication, author=author)

        pmg = merger.PublicationMergeGroup(final=all_publications[0], others=set(all_publications[1:]))
        self.assertTrue(pmg.is_valid())

    def test_authoritative_author_merge_no_outside_publications(self):
        """Authors not referencing publications outside their merge group should be ok"""
        all_publications = list(models.Publication.objects.all())

        pmg = merger.PublicationMergeGroup(final=all_publications[0], others=set(all_publications[1:]))
        self.assertTrue(pmg.is_valid())

