from django.db import models, transaction
from model_utils import Choices
from django.utils.translation import ugettext_lazy as _
from django.contrib.postgres.fields import JSONField

class Author(models.Model):
    """Canonical Author"""
    INDIVIDUAL = 'INDIVIDUAL'
    GROUP = 'GROUP'
    TYPE_CHOICES = Choices(
        (INDIVIDUAL, _('individual')),
        (GROUP, _('group')),
    )
    type = models.TextField(choices=TYPE_CHOICES, max_length=500)
    orcid = models.TextField(max_length=500, default='')


class AuthorAlias(models.Model):
    INDIVIDUAL = 'INDIVIDUAL'
    GROUP = 'GROUP'
    TYPE_CHOICES = Choices(
        (INDIVIDUAL, _('individual')),
        (GROUP, _('group')),
    )
    name = models.TextField(max_length=1000)

    author = models.ForeignKey(Author, on_delete=models.CASCADE)


class AbstractPublication(models.Model):
    title = models.TextField(max_length=1000, blank=True, default='')
    year = models.IntegerField(blank=True, null=True)
    doi = models.TextField(max_length=500, blank=True, default='')
    abstract = models.TextField(max_length=20000, blank=True, default='')
    primary = models.BooleanField()

    class Meta:
        abstract = True


class Container(models.Model):
    """Canonical Container"""
    issn = models.TextField(max_length=500, blank=True, default='')
    type = models.TextField(max_length=1000, blank=True, default='')


class ContainerAlias(models.Model):
    name = models.TextField(max_length=1000, blank=True, default='')

    container = models.ForeignKey(Container, on_delete=models.CASCADE)


class Publication(AbstractPublication):
    """Canonical Publication"""
    container = models.ForeignKey(Container, blank=True, null=True, on_delete=models.SET_NULL)
    authors = models.ManyToManyField(Author, related_name="publications")
    citations = models.ManyToManyField("self", symmetrical=False, related_name="referenced_by")


class Raw(models.Model):
    BIBTEX_ENTRY = "BIBTEX_ENTRY"
    BIBTEX_REF = "BIBTEX_REF"
    CROSSREF_DOI_SUCCESS = "CROSSREF_DOI_SUCCESS"
    CROSSREF_DOI_FAIL = "CROSSREF_DOI_FAIL"
    CROSSREF_SEARCH_SUCCESS = "CROSSREF_SEARCH_SUCCESS"
    CROSSREF_SEARCH_FAIL_NOT_UNIQUE = "CROSSREF_SEARCH_FAIL_NOT_UNIQUE"
    CROSSREF_SEARCH_FAIL_OTHER = "CROSSREF_SEARCH_FAIL_OTHER"
    CROSSREF_SEARCH_CANDIDATE = "CROSSREF_SEARCH_CANDIDATE"

    SOURCE_CHOICES = Choices(
        (BIBTEX_ENTRY, "BibTeX Entry"),
        (BIBTEX_REF, "BibTeX Reference"),
        (CROSSREF_DOI_SUCCESS, "CrossRef lookup succeeded"),
        (CROSSREF_DOI_FAIL, "CrossRef lookup failed"),
        (CROSSREF_SEARCH_SUCCESS, "CrossRef search succeeded"),
        (CROSSREF_SEARCH_FAIL_NOT_UNIQUE, "CrossRef search failed - not unique"),
        (CROSSREF_SEARCH_FAIL_OTHER, "CrossRef search failed - other"),
        (CROSSREF_SEARCH_CANDIDATE, "CrossRef search match candidate")
    )
    key = models.TextField(choices=SOURCE_CHOICES, max_length=100)
    value = JSONField()
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT)


class PublicationRaw(AbstractPublication):
    raw = models.OneToOneField(Raw, primary_key=True, related_name="raw_publication")
    referenced_by = models.ForeignKey("self", blank=True, null=True, related_name="citations")


class AuthorRaw(models.Model):
    INDIVIDUAL = 'INDIVIDUAL'
    GROUP = 'GROUP'
    TYPE_CHOICES = Choices(
        (INDIVIDUAL, _('individual')),
        (GROUP, _('group')),
    )
    name = models.TextField(max_length=1000)
    type = models.TextField(choices=TYPE_CHOICES, max_length=500)
    orcid = models.TextField(max_length=500, default='')

    raw = models.ForeignKey(Raw, related_name="raw_authors")
    publication_raw = models.ForeignKey(PublicationRaw, related_name="raw_authors")
    author_alias = models.ForeignKey(AuthorAlias, on_delete=models.PROTECT)


class ContainerRaw(models.Model):
    name = models.TextField(max_length=1000, blank=True, default='')
    type = models.TextField(max_length=1000, blank=True, default='')
    issn = models.TextField(max_length=500, blank=True, default='')

    raw = models.OneToOneField(Raw, primary_key=True, related_name="raw_container")
    publication_raw = models.OneToOneField(PublicationRaw)
    container_alias = models.ForeignKey(ContainerAlias, on_delete=models.PROTECT)