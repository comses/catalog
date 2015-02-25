from django.contrib.sites.models import Site, RequestSite
from django.db import models
from django.template import Context
from django.template.loader import get_template
from django.utils.translation import ugettext_lazy as _

from model_utils import Choices
from model_utils.managers import InheritanceManager


class InvitationEmail(object):

    def __init__(self, request):
        self.request = request
        self.plaintext_template = get_template('email/invitation-email.txt')

    @property
    def site(self):
        if Site._meta.installed:
            return Site.objects.get_current()
        else:
            return RequestSite(self.request)

    @property
    def is_secure(self):
        return self.request.is_secure()

    def get_plaintext_content(self, message, token):
        c = Context({
            'invitation_text': message,
            'site': self.site,
            'token': token,
            'secure': self.is_secure
        })
        return self.plaintext_template.render(c)


STATUS_CHOICES = Choices(
    ('INCOMPLETE', _('Archive URL not present')),
    ('AUTHOR_UPDATED', _('Archive URL updated by Author')),
    ('INVALID_URL', _('Invalid Archive URL')),
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
    tag = models.CharField(max_length=100, unique=True)

    def __unicode__(self):
        return unicode(self.tag)


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
    name = models.CharField(max_length=256, unique=True)
    url = models.URLField()
    description = models.TextField()

    def __unicode__(self):
        return u'{0}'.format(self.name)


class Sponsor(models.Model):
    """ funding agency sponsoring this research """
    name = models.CharField(max_length=256, unique=True)
    url = models.URLField()
    description = models.TextField()

    def __unicode__(self):
        return u'{0}'.format(self.name)


class Publication(models.Model):
    objects = InheritanceManager()

    title = models.TextField()
    abstract = models.TextField()
    short_title = models.CharField(max_length=200, blank=True)
    url = models.URLField(blank=True)
    archived_url = models.URLField(blank=True)
    contact_email = models.EmailField(blank=True)
    model_docs = models.CharField(max_length=32, blank=True)
    date_published_text = models.CharField(max_length=32)
    date_published = models.DateField(null=True, blank=True)
    # FIXME Should we add default date (i.e today) to date_accessed
    date_accessed = models.DateField(null=True, blank=True)
    archive = models.CharField(max_length=200, blank=True)
    archive_location = models.CharField(max_length=200, blank=True)
    library_catalog = models.CharField(max_length=200, blank=True)
    call_number = models.CharField(max_length=200, blank=True)
    rights = models.CharField(max_length=200, blank=True)
    extra = models.TextField(blank=True)
    published_language = models.CharField(max_length=200, default='English')
    date_added = models.DateTimeField()
    date_modified = models.DateTimeField()
    status = models.CharField(choices=STATUS_CHOICES, max_length=32)

    author_comments = models.TextField(blank=True)
    email_sent_count = models.PositiveIntegerField(default=0)

    platforms = models.ManyToManyField('Platform', null=True, blank=True)
    sponsors = models.ManyToManyField('Sponsor', null=True, blank=True)
    tags = models.ManyToManyField('Tag', null=True, blank=True)
    creators = models.ManyToManyField('Creator')
    added_by = models.ForeignKey('auth.User')

    def __unicode__(self):
        return u'{0}'.format(self.title)


class Journal(models.Model):
    name = models.CharField(max_length=256)
    url = models.URLField(max_length=256, blank=True)
    abbreviation = models.CharField(max_length=256, blank=True)

    def __unicode__(self):
        return u'{0}'.format(self.name)


class JournalArticle(Publication):
    journal = models.ForeignKey(Journal)
    pages = models.CharField(max_length=200, blank=True)
    issn = models.CharField(max_length=200, blank=True)
    volume = models.CharField(max_length=200, blank=True)
    issue = models.CharField(max_length=200, blank=True)
    series = models.CharField(max_length=200, blank=True)
    series_title = models.CharField(max_length=200, blank=True)
    series_text = models.CharField(max_length=200, blank=True)
    doi = models.CharField(max_length=200, blank=True)


class Book(Publication):
    series = models.CharField(max_length=200, blank=True)
    series_number = models.CharField(max_length=32, blank=True)
    volume = models.CharField(max_length=32, blank=True)
    num_of_volume = models.CharField(max_length=32, blank=True)
    edition = models.CharField(max_length=32, blank=True)
    place = models.CharField(max_length=32, blank=True)
    publisher = models.CharField(max_length=200, blank=True)
    num_of_pages = models.CharField(max_length=32, blank=True)
    isbn = models.CharField(max_length=200, blank=True)

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
