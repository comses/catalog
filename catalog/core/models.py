from django.db import models
from django.utils.translation import ugettext_lazy as _

from model_utils import Choices
from model_utils.managers import InheritanceManager


STATUS_CHOICES = Choices(
    ('INCOMPLETE', _('Archive URL not present.')),
    ('INVALID_URL', _('Invalid Archive URL')),
    ('EMAIL_SENT', _('Email Sent')),
    ('COMPLETE', _('Archived')),
)

CREATOR_CHOICES = Choices(
    ('AUTHOR', _('author')),
    ('REVIEWED_AUTHOR', _('reviewed author')),
    ('CONTRIBUTOR', _('contributor')),
    ('EDITOR', _('editor')),
    ('TRANSLATOR', _('translator')),
    ('SERIES_EDITOR', _('series editor')),
)


class Creator(models.Model):
    creator_type = models.CharField(choices=CREATOR_CHOICES, max_length=32)
    first_name = models.CharField(max_length=200)
    last_name = models.CharField(max_length=200)

    def __unicode__(self):
        return u'{0} {1} ({2})'.format(self.first_name, self.last_name, self.creator_type)


class Tag(models.Model):
    key = models.CharField(max_length=100)
    value = models.CharField(max_length=100)

    def __unicode__(self):
        if self.key:
            return u'{0}: {1}'.format(self.key, self.value)
        else:
            return u'{0}'.format(self.value)


class Note(models.Model):
    note = models.TextField()
    date_added = models.DateTimeField()
    date_modified = models.DateTimeField()

    tags = models.ManyToManyField('Tag')
    publication = models.ForeignKey('Publication', null=True)

    def __unicode__(self):
        return u'{0}'.format(self.note)


class Platform(models.Model):
    """ model platform, e.g, NetLogo or RePast """
    name = models.CharField(max_length=256)
    url = models.URLField()
    description = models.TextField()

    def __unicode__(self):
        return u'{0}'.format(self.name)


class Sponsor(models.Model):
    """ funding agency sponsoring this research """
    name = models.CharField(max_length=256)
    url = models.URLField()
    description = models.TextField()

    def __unicode__(self):
        return u'{0}'.format(self.name)


class Publication(models.Model):
    objects = InheritanceManager()

    title = models.TextField()
    abstract = models.TextField()
    short_title = models.CharField(max_length=200)
    url = models.URLField()
    archived_url = models.URLField()
    contact_email = models.EmailField()
    model_docs = models.CharField(max_length=32)
    date_published_text = models.CharField(max_length=32)
    date_published = models.DateField(null=True, blank=True)
    # FIXME Should we add default date (i.e today) to date_accessed
    date_accessed = models.DateField(null=True, blank=True)
    archive = models.CharField(max_length=200)
    archive_location = models.CharField(max_length=200)
    library_catalog = models.CharField(max_length=200)
    call_number = models.CharField(max_length=200)
    rights = models.CharField(max_length=200)
    extra = models.TextField()
    published_language = models.CharField(max_length=200, default='English')
    date_added = models.DateTimeField()
    date_modified = models.DateTimeField()
    status = models.CharField(choices=STATUS_CHOICES, max_length=32)

    platforms = models.ManyToManyField('Platform', null=True)
    sponsors = models.ManyToManyField('Sponsor', null=True)
    tags = models.ManyToManyField('Tag')
    creators = models.ManyToManyField('Creator')
    added_by = models.ForeignKey('auth.User')

    def __unicode__(self):
        return u'{0}'.format(self.title)


class Journal(models.Model):
    name = models.CharField(max_length=256)
    url = models.URLField(max_length=256)
    abbreviation = models.CharField(max_length=256)

    def __unicode__(self):
        return u'{0}'.format(self.name)


class JournalArticle(Publication):
    journal = models.ForeignKey(Journal)
    pages = models.CharField(max_length=200)
    issn = models.CharField(max_length=200)
    volume = models.CharField(max_length=200)
    issue = models.CharField(max_length=200)
    series = models.CharField(max_length=200)
    series_title = models.CharField(max_length=200)
    series_text = models.CharField(max_length=200)
    doi = models.CharField(max_length=200)


class Book(Publication):
    series = models.CharField(max_length=200)
    series_number = models.CharField(max_length=32)
    volume = models.CharField(max_length=32)
    num_of_volume = models.CharField(max_length=32)
    edition = models.CharField(max_length=32)
    place = models.CharField(max_length=32)
    publisher = models.CharField(max_length=200)
    num_of_pages = models.CharField(max_length=32)
    isbn = models.CharField(max_length=200)

"""
class Report(Publication):
    report_number = models.PositiveIntegerField(null=True, blank=True)
    report_type = models.CharField(max_length=200)
    series_title = models.CharField(max_length=200)
    place = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    pages = models.PositiveIntegerField(null=True, blank=True)


class Thesis(Publication):
    thesis_type = models.CharField(max_length=200)
    university = models.CharField(max_length=200)
    place = models.CharField(max_length=200)
    num_of_pages = models.PositiveIntegerField(null=True, blank=True)
"""
