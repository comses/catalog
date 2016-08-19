from django.contrib.auth.models import User
from django.core import management
from catalog.citation.models import AuditCommand, AuditLog, Container, Publication, PublicationPlatforms, Platform, \
    Author, \
    PublicationAuthors
from catalog.citation.serializers import PublicationSerializer

from .common import BaseTest

from collections import OrderedDict

class PublicationSerializerTest(BaseTest):
    def setUp(self):
        self.user = self.create_user(username='bobsmith',
                                     email='a@b.com', password='test')
        self.author = Author.objects.create(given_name='Bob', family_name='Smith', type=Author.INDIVIDUAL)
        self.container = Container.objects.create(name='JASSS')
        self.platform = Platform.objects.create(name='JVM')
        self.publication = Publication.objects.create(
            title='Foo', added_by=self.user, container=self.container)
        self.publication_platform = PublicationPlatforms.objects.create(
            platform=self.platform, publication=self.publication)
        self.publication_author = PublicationAuthors.objects.create(
            author=self.author, publication=self.publication, role=PublicationAuthors.RoleChoices.AUTHOR)

    def test_add_platform_to_publication(self):
        serializer = PublicationSerializer(self.publication)
        serializer = PublicationSerializer(self.publication, data=serializer.data)
        if serializer.is_valid():
            serializer.save(self.user)
        # If no changes were made to the data nothing should be logged in the auditlog
        self.assertEqual(AuditLog.objects.count(), 0)
        self.assertEqual(AuditCommand.objects.count(), 1)

        platform_cpp = Platform.objects.create(name='C++')
        PublicationPlatforms.objects.create(platform=platform_cpp, publication=self.publication)
        serializer = PublicationSerializer(Publication.objects.first())
        serializer = PublicationSerializer(Publication.objects.first(), data=serializer.data)
        if serializer.is_valid():
            serializer.save(self.user)
        self.assertEqual(AuditLog.objects.filter(table='publicationplatforms').count(), 0)
        self.assertEqual(AuditLog.objects.filter(table='platform').count(), 0)
        self.assertEqual(AuditCommand.objects.count(), 2)

        platform_pascal_str = 'Pascal'
        serializer = PublicationSerializer(Publication.objects.first())
        data = serializer.data
        data['platforms'] = [OrderedDict(name=platform_pascal_str, url='', description='')]
        serializer = PublicationSerializer(Publication.objects.first(), data=data)
        if serializer.is_valid():
            serializer.save(self.user)
        # Two Deletes and One Insert
        self.assertEqual(AuditLog.objects.filter(table='publicationplatforms').count(), 3)
        self.assertEqual(AuditLog.objects.filter(table='platform').count(), 1)
        self.assertEqual(AuditCommand.objects.count(), 3)

    def test_add_creator_to_publication(self):
        pass

    def test_remove_modeldocumentation_from_publication(self):
        pass
