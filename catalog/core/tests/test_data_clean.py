from django.test import TestCase
from .. import data_clean, models
from django.contrib.auth.models import User

import logging

logger = logging.getLogger(__name__)


class SplitTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        super(SplitTests, cls).setUpTestData()
        cls.name = "C#/.NET"

        cls.user = User.objects.create_user(username='bob',
                                            email='bob@bob.com',
                                            password='bobsled')

        platform = models.Platform.objects.create(name=cls.name)
        publication = models.Publication.objects.create(title="Foo", added_by=cls.user)
        publication.platforms.add(platform)
        publication.save()

        cls.platform_dotnet = platform
        cls.publication_dotnet = publication

    def test_split_platform_different_new_names(self):
        new_names = ["C#", ".NET"]
        data_clean.split_record(name=self.name, new_names=new_names, table=models.Platform, related_name="platforms")

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#/.NET").first(), None)

    def test_split_platform_same_new_name(self):
        new_names = ["C#/.NET", ".NET"]
        data_clean.split_record(name=self.name, new_names=new_names, table=models.Platform, related_name="platforms")

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#/.NET").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)

    def test_split_plat_multiple_publications(self):
        platform_netlogo = models.Platform.objects.create(name="NetLogo")
        publication_netlogo_dotnet = models.Publication.objects.create(title="Bar", added_by=self.user)
        publication_netlogo = models.Publication.objects.create(title="Baz", added_by=self.user)

        publication_netlogo_dotnet.platforms.add(platform_netlogo, self.platform_dotnet)
        publication_netlogo_dotnet.save()

        publication_netlogo.platforms.add(platform_netlogo)
        publication_netlogo.save()

        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="C#").count(), 0)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name=self.name).first(), self.platform_dotnet)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="NetLogo").first(), platform_netlogo)

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#").count(), 0)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=self.name).first(), self.platform_dotnet)
        self.assertEqual(self.publication_dotnet.platforms.filter(name="NetLogo").first(), None)

        self.assertEqual(publication_netlogo.platforms.filter(name="C#").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=self.name).first(), None)
        self.assertEqual(publication_netlogo.platforms.filter(name="NetLogo").first(), platform_netlogo)

        data_clean.split_record(name=self.name, new_names=["C#", ".NET"], table=models.Platform, related_name="platforms")

        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="C#").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name=self.name).first(), None)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="NetLogo").first(), platform_netlogo)

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=self.name).first(), None)
        self.assertEqual(self.publication_dotnet.platforms.filter(name="NetLogo").first(), None)

        self.assertEqual(publication_netlogo.platforms.filter(name="C#").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=self.name).first(), None)
        self.assertEqual(publication_netlogo.platforms.filter(name="NetLogo").first(), platform_netlogo)


class MergeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        super(MergeTests, cls).setUpTestData()
        cls.names = ["Euro. Commission", "EC"]

        cls.user = User.objects.create_user(username='bob',
                                            email='bob@bob.com',
                                            password='bobsled')

        sponsors = [models.Sponsor.objects.create(name=name)
                   for name in cls.names]
        publication = models.Publication.objects.create(title="Foo", added_by=cls.user)
        publication.sponsors.add(*sponsors)
        publication.save()

        cls.publication = publication
        cls.sponsors = sponsors

    def test_merge_platform_different_new_name(self):
        new_name = "European Commission"
        new_sponsor = data_clean.merge_sponsors(names=self.names, new_name=new_name)

        self.assertEqual(self.publication.sponsors.filter(name__in=self.names).first(), None)
        self.assertEqual(self.publication.sponsors.get(name=new_name), new_sponsor)

    def test_merge_platform_same_new_name(self):
        new_name = "Euro. Commission"
        new_sponsor = data_clean.merge_sponsors(names=self.names, new_name=new_name)

        self.assertEqual(self.publication.sponsors.filter(name__in=self.names).first(), new_sponsor)
        self.assertEqual(self.publication.sponsors.get(name=new_name), new_sponsor)

    def test_merge_sponsor_multiple_publications(self):
        sponsor_euro_commission = self.sponsors[0]
        sponsor_nsf = models.Sponsor.objects.create(name="United States National Science Foundation (NSF)")

        publication_euro_commission_nsf = models.Publication.objects.create(title="Foo", added_by=self.user)
        publication_euro_commission_nsf.sponsors.add(sponsor_euro_commission, sponsor_nsf)

        publication_nsf = models.Publication.objects.create(title="Bar", added_by=self.user)
        publication_nsf.sponsors.add(sponsor_nsf)

        new_name = "Euro. Commission"
        new_sponsor = data_clean.merge_sponsors(names=self.names, new_name=new_name)

        self.assertEqual(models.Sponsor.objects.filter(name=new_name).first(), new_sponsor)
        self.assertNotEqual(sponsor_euro_commission, new_sponsor)
        self.assertEqual(models.Sponsor.objects.filter(name=self.names[1]).first(), None)

        self.assertListEqual(list(publication_euro_commission_nsf.sponsors.all()),
                             [sponsor_nsf, new_sponsor])
        self.assertListEqual(list(publication_nsf.sponsors.all()),
                             [sponsor_nsf])
        self.assertListEqual(list(self.publication.sponsors.all()),
                             [new_sponsor])