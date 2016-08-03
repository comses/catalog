from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from django.contrib.sites.requests import RequestSite
from django.core.urlresolvers import reverse
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.template import Context
from django.template.loader import get_template
from django.utils.translation import ugettext_lazy as _
from datetime import datetime, date
from collections import defaultdict

from model_utils import Choices
from model_utils.managers import InheritanceManager
from typing import Dict, Optional


class LogManager(models.Manager):
    use_for_related_fields = True

    def log_create(self, audit_command, payload):
        with transaction.atomic():
            instance = self.create(**payload)
            payload = AuditLog.objects.create(
                action='DELETE',
                table=instance._meta.db_table,
                message='',
                payload={'id': instance.id},
                audit_command=audit_command)
            return instance

    def log_get_or_create(self, audit_command, payload, **kwargs):
        with transaction.atomic():
            instance, created = self.get_or_create(defaults=payload, **kwargs)
            if created:
                action = 'DELETE'
                payload = {'id': instance.id}
            else:
                action = 'UPDATE'
                payload = {column: getattr(instance, column)
                           for column in payload.keys()}
                payload['id'] = instance.id
            payload = AuditLog.objects.create(
                action=action,
                table=instance._meta.db_table,
                message='',
                payload=payload,
                audit_command=audit_command)

        return instance, created


def datetime_json_serialize(datetime_obj: Optional[datetime]):
    if datetime_obj:
        val = {'tag': 'just',
               'value': {
                   'year': datetime_obj.year,
                   'month': datetime_obj.month,
                   'day': datetime_obj.day,
                   'hour': datetime_obj.hour,
                   'minute': datetime_obj.minute,
                   'microsecond': datetime_obj.microsecond,
                   'tzinfo': datetime_obj.tzinfo.zone}
               }
    else:
        val = {'tag': 'nothing'}
    return val


def date_json_serialize(date_obj: Optional[date]):
    if date_obj is not None:
        val = {'tag': 'just',
               'value': {
                   'year': date_obj.year,
                   'month': date_obj.month,
                   'day': date_obj.day
               }}
    else:
        val = {'tag': 'nothing'}
    return val


def identity_json_serialize(obj):
    return obj


class LogQuerySet(models.query.QuerySet):
    DISPATCH_JSON_SERIALIZE = defaultdict(lambda: identity_json_serialize,
                                          DateTimeField=datetime_json_serialize,
                                          DateField=date_json_serialize)

    def json_serialize(self, field_type, obj):
        return LogQuerySet.DISPATCH_JSON_SERIALIZE[field_type](obj)

    def log_delete(self, audit_command):
        with transaction.atomic():
            instances = self.all()

            auditlogs = []
            for instance in instances:
                payload = {field.column: self.json_serialize(field.get_internal_type(), getattr(instance, field.column))
                           for field in instance._meta.local_fields}
                auditlogs.append(
                    AuditLog(
                        action='INSERT',
                        table=instance._meta.db_table,
                        message='',
                        payload=payload,
                        audit_command=audit_command))
            AuditLog.objects.bulk_create(auditlogs)

            info = instances.delete()
            return info

    def log_update(self, audit_command, payload: Dict):
        with transaction.atomic():
            instances = self.all()

            auditlogs = []
            for instance in instances:
                old_payload = {column: getattr(instance, column)
                               for column in payload.keys()}
                old_payload['id'] = instance.id
                auditlogs.append(
                    AuditLog(
                        action='UPDATE',
                        table=instance._meta.db_table,
                        message='',
                        payload=old_payload,
                        audit_command=audit_command))
            AuditLog.objects.bulk_create(auditlogs)

            info = self.update(**payload)
            return info


class AbstractLogModel(models.Model):
    def log_delete(self, audit_command):
        with transaction.atomic():
            payload = {field.column: getattr(self, field.column)
                       for field in self._meta.local_fields}
            auditlogs = \
                AuditLog.objects.create(
                    action='INSERT',
                    table=self._meta.db_table,
                    message='',
                    payload=payload,
                    audit_command=audit_command)
            info = self.delete()
            return info

    def log_save(self, audit_command, payload: Optional[Dict] = None):
        with transaction.atomic():
            auditlog = AuditLog(
                table=self._meta.db_table,
                message='',
                audit_command=audit_command)
            if payload:
                assert self.id is not None
                payload['id'] = self.id
                auditlog.action = 'UPDATE'
                auditlog.payload = payload
                info = self.save()
                auditlog.save()
            else:
                info = self.save()
                auditlog.action = 'DELETE'
                auditlog.payload = {'id': self.id}
                auditlog.save()
            return info

    objects = LogManager.from_queryset(LogQuerySet)()

    class Meta:
        abstract = True


class InvitationEmail(object):
    def __init__(self, request):
        self.request = request
        self.plaintext_template = get_template('email/invitation-email.txt')

    @property
    def site(self):
        return RequestSite(self.request)

    def get_context(self, message, token):
        return Context({
            'invitation_text': message,
            'domain': self.site.domain,
            'token': token,
        })

    def get_plaintext_content(self, message, token):
        return self.plaintext_template.render(self.get_context(message, token))


class InvitationEmailTemplate(models.Model):
    name = models.CharField(max_length=32)
    text = models.TextField()
    date_added = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey(User, related_name="citation_added_by")


class Author(AbstractLogModel):
    INDIVIDUAL = 'INDIVIDUAL'
    GROUP = 'GROUP'
    TYPE_CHOICES = Choices(
        (INDIVIDUAL, _('individual')),
        (GROUP, _('group')),
    )
    CREATOR_CHOICES = Choices(
        ('AUTHOR', _('author')),
        ('REVIEWED_AUTHOR', _('reviewed author')),
        ('CONTRIBUTOR', _('contributor')),
        ('EDITOR', _('editor')),
        ('TRANSLATOR', _('translator')),
        ('SERIES_EDITOR', _('series editor')),
    )
    type = models.TextField(choices=TYPE_CHOICES, max_length=32)
    creator_type = models.CharField(choices=CREATOR_CHOICES, max_length=32)
    orcid = models.TextField(max_length=200)

    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this model was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this model was last modified on this system'))

    def __repr__(self):
        return "Author(orcid={orcid}. creator_type={creator_type})" \
            .format(orcid=self.orcid, creator_type=self.creator_type)


class AuthorAlias(AbstractLogModel):
    name = models.CharField(max_length=200)

    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name="author_aliases")

    def __repr__(self):
        return "AuthorAlias(id={id}, name={name}, author_id={author_id})" \
            .format(id=self.id, name=self.name, author_id=self.author_id)

    class Meta:
        unique_together = ('author', 'name')


class Tag(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __unicode__(self):
        return self.name


class ModelDocumentation(models.Model):
    CATEGORIES = [
        {'category': 'Narrative',
         'modelDocumentationList': [{'category': 'Narrative', 'name': 'ODD'},
                                    {'category': 'Narrative', 'name': 'Other Narrative'}]},
        {'category': 'Visual Relationships',
         'modelDocumentationList': [{'category': 'Visual Relationships', 'name': 'UML'},
                                    {'category': 'Visual Relationships', 'name': 'Flow charts'},
                                    {'category': 'Visual Relationships', 'name': 'Ontologies'},
                                    {'category': 'Visual Relationships', 'name': 'AORML'}]},
        {'category': 'Code and formal descriptions',
         'modelDocumentationList': [{'category': 'Code and formal descriptions', 'name': 'Source code'},
                                    {'category': 'Code and formal descriptions', 'name': 'Pseudocode'},
                                    {'category': 'Code and formal descriptions', 'name': 'Mathematical description'}]},
    ]
    ''' common choices: UML, ODD, Word / PDF doc '''
    name = models.CharField(max_length=255, unique=True)

    def __unicode__(self):
        return self.name


class Note(models.Model):
    text = models.TextField()
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)
    zotero_key = models.CharField(max_length=64, null=True, unique=True, blank=True)
    zotero_date_added = models.DateTimeField(null=True, blank=True)
    zotero_date_modified = models.DateTimeField(null=True, blank=True)
    added_by = models.ForeignKey(User, related_name='citation_added_note_set')
    deleted_on = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, related_name='citation_deleted_note_set', null=True, blank=True)
    publication = models.ForeignKey('Publication', null=True, blank=True)

    @property
    def is_deleted(self):
        return bool(self.deleted_on)

    def __unicode__(self):
        return self.text


class Platform(models.Model):
    """ model platform, e.g, NetLogo or RePast """
    name = models.CharField(max_length=255, unique=True)
    url = models.URLField(default='', blank=True)
    description = models.TextField(default='', blank=True)

    def __unicode__(self):
        return self.name


class Sponsor(models.Model):
    """ funding agency sponsoring this research """
    name = models.CharField(max_length=255, unique=True)
    url = models.URLField(default='', blank=True)
    description = models.TextField(default='', blank=True)

    def __unicode__(self):
        return self.name


class Container(AbstractLogModel):
    """Canonical Container"""
    issn = models.TextField(max_length=500, blank=True, default='')
    type = models.TextField(max_length=1000, blank=True, default='')

    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this container was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this container was last modified on this system'))

    def __repr__(self):
        return "Container(issn={issn}, type={type})" \
            .format(issn=self.issn, type=self.type)


class ContainerAlias(AbstractLogModel):
    name = models.TextField(max_length=1000, blank=True, default='')
    container = models.ForeignKey(Container, on_delete=models.PROTECT, related_name="container_aliases")

    def __repr__(self):
        return "ContainerAlias(name={name}, container={container})" \
            .format(name=self.name, container=self.container)

    class Meta:
        unique_together = ('container', 'name')


class Publication(AbstractLogModel):
    Status = Choices(
        ('UNTAGGED', _('Not reviewed')),
        ('NEEDS_AUTHOR_REVIEW', _('Curator has reviewed publication, requires author intervention.')),
        ('FLAGGED', _('Flagged for further internal review by CoMSES staff')),
        ('AUTHOR_UPDATED', _('Updated by author, needs CoMSES review')),
        ('INVALID', _('Publication record is not applicable or invalid')),
        ('COMPLETE', _('Reviewed and verified by CoMSES')),
    )
    ResourceType = Choices(
        ('JOURNAL_ARTICLE', _('Journal Article')),
    )

    # zotero publication metadata
    title = models.TextField()
    abstract = models.TextField(blank=True)
    short_title = models.CharField(max_length=255, blank=True)
    zotero_key = models.CharField(max_length=64, null=True, unique=True, blank=True)
    url = models.URLField(blank=True)
    date_published_text = models.CharField(max_length=32, blank=True)
    date_published = models.DateField(null=True, blank=True)
    date_accessed = models.DateField(null=True, blank=True)
    archive = models.CharField(max_length=255, blank=True)
    archive_location = models.CharField(max_length=255, blank=True)
    library_catalog = models.CharField(max_length=255, blank=True)
    call_number = models.CharField(max_length=255, blank=True)
    rights = models.CharField(max_length=255, blank=True)
    extra = models.TextField(blank=True)
    published_language = models.CharField(max_length=255, default='English', blank=True)
    zotero_date_added = models.DateTimeField(help_text=_('date added field from zotero'), null=True, blank=True)
    zotero_date_modified = models.DateTimeField(help_text=_('date modified field from zotero'), null=True, blank=True)
    creators = models.ManyToManyField(Author, related_name='publications', through='PublicationAuthors')

    # custom incoming tags set by zotero data entry to mark the code archive url, contact author's email, the ABM platform
    # used, research sponsors (funding agencies, etc.), documentation, and other research keyword tags
    code_archive_url = models.URLField(max_length=255, blank=True)
    contact_author_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    platforms = models.ManyToManyField(Platform, blank=True, related_name='publications')
    sponsors = models.ManyToManyField(Sponsor, blank=True, related_name='publications')
    model_documentation = models.ManyToManyField(ModelDocumentation, blank=True, related_name='publications')
    tags = models.ManyToManyField(Tag, blank=True)
    added_by = models.ForeignKey(User, related_name='citation_added_publication_set')

    # custom fields used by catalog internally
    status = models.CharField(choices=Status, max_length=32, default=Status.UNTAGGED)
    date_added = models.DateTimeField(auto_now_add=True,
                                      help_text=_('Date this publication was imported into this system'))
    date_modified = models.DateTimeField(auto_now=True,
                                         help_text=_('Date this publication was last modified on this system'))

    author_comments = models.TextField(blank=True)
    email_sent_count = models.PositiveIntegerField(default=0)
    assigned_curator = models.ForeignKey(User,
                                         null=True,
                                         blank=True,
                                         help_text=_("Currently assigned curator"),
                                         related_name='citation_assigned_publication_set')

    # type fields
    resource_type = models.CharField(choices=ResourceType, max_length=255, default=ResourceType.JOURNAL_ARTICLE)
    is_primary = models.BooleanField(default=True)

    # journal specific fields
    journal = models.ForeignKey(Container, null=True, blank=True, on_delete=models.SET_NULL)
    pages = models.CharField(max_length=255, default='', blank=True)
    issn = models.CharField(max_length=255, default='', blank=True)
    volume = models.CharField(max_length=255, default='', blank=True)
    issue = models.CharField(max_length=255, default='', blank=True)
    series = models.CharField(max_length=255, default='', blank=True)
    series_title = models.CharField(max_length=255, default='', blank=True)
    series_text = models.CharField(max_length=255, default='', blank=True)
    doi = models.CharField(max_length=255, default='', blank=True)

    citations = models.ManyToManyField(
        "self", symmetrical=False, related_name="referenced_by",
        through='PublicationCitations', through_fields=('publication', 'citation'))

    def is_editable_by(self, user):
        # eventually consider having permission groups or per-object permissions
        return self.assigned_curator == user

    def _pk_url(self, name):
        return reverse(name, args=[self.pk])

    def get_absolute_url(self):
        return self._pk_url('citation:publication_detail')

    def get_curator_url(self):
        return self._pk_url('citation:curator_publication_detail')

    def __str__(self):
        return "Primary: {}; Date Published: {}; Title: {}; DOI: {}" \
            .format(self.is_primary,
                    self.date_published_text,
                    self.title,
                    self.doi)


class AuditCommand(models.Model):
    Role = Choices(('AUTHOR_EDIT', _('Author edit')),
                   ('SYSTEM_LOG', _('System log')),
                   ('CURATOR_EDIT', _('Curator edit')))
    Action = Choices(('MERGE', _('Merge Records')),
                     ('LOAD', _('Load from File')),
                     ('OTHER', _('Other')))

    role = models.CharField(max_length=32, choices=Role)
    action = models.CharField(max_length=32, choices=Action)
    date_added = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(User, null=True, blank=True, related_name="citation_creator_set",
                                help_text=_('The user who initiated this action, if any.'))

    class Meta:
        ordering = ['-date_added']


class AuditLogQuerySet(models.query.QuerySet):
    pass


class AuditLogManager(models.Manager):
    def log_curator_action(self, message=None, creator=None, publication=None, modified_data=None):
        if not all([message, creator, publication]):
            raise ValidationError("Requires valid message [%s], creator [%s], and publication [%s]",
                                  message, creator, publication)
        return self.create(action=AuditLog.Action.CURATOR_EDIT,
                           message=message, creator=creator, publication=publication, modified_data=modified_data)


class AuditLog(models.Model):
    Action = Choices(('UPDATE', _('Update')),
                     ('INSERT', _('Insert')),
                     ('DELETE', _('Delete')))
    action = models.CharField(max_length=32, choices=Action)
    table = models.CharField(max_length=128)
    message = models.TextField(blank=True, help_text=_('A human readable representation of the change made'))
    payload = JSONField(blank=True, null=True,
                        help_text=_('A JSON dictionary containing modified fields, if any, for the given publication'))
    audit_command = models.ForeignKey(AuditCommand)

    objects = AuditLogManager.from_queryset(AuditLogQuerySet)()

    def __str__(self):
        return u"{} - {} performed {} on {}".format(
            self.creator,
            self.action,
            self.message,
            self.payload,
        )

    class Meta:
        ordering = ['-id']


class AbstractWithDateAddedModel(models.Model):
    date_added = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Raw(AbstractLogModel, AbstractWithDateAddedModel):
    BIBTEX_FILE = "BIBTEX_FILE"
    BIBTEX_ENTRY = "BIBTEX_ENTRY"
    BIBTEX_REF = "BIBTEX_REF"
    CROSSREF_DOI_SUCCESS = "CROSSREF_DOI_SUCCESS"
    CROSSREF_DOI_FAIL = "CROSSREF_DOI_FAIL"
    CROSSREF_SEARCH_SUCCESS = "CROSSREF_SEARCH_SUCCESS"
    CROSSREF_SEARCH_FAIL_NOT_UNIQUE = "CROSSREF_SEARCH_FAIL_NOT_UNIQUE"
    CROSSREF_SEARCH_FAIL_OTHER = "CROSSREF_SEARCH_FAIL_OTHER"
    CROSSREF_SEARCH_CANDIDATE = "CROSSREF_SEARCH_CANDIDATE"

    SOURCE_CHOICES = Choices(
        (BIBTEX_FILE, "BibTeX File"),
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

    publication = models.ForeignKey(Publication, related_name='raw', on_delete=models.PROTECT)
    container_alias = models.ForeignKey(ContainerAlias, related_name='raw', on_delete=models.PROTECT)
    author_aliases = models.ManyToManyField(AuthorAlias, related_name='raw', through='AuthorAliasRaws')


class PublicationCitations(AbstractLogModel, AbstractWithDateAddedModel):
    publication = models.ForeignKey(Publication, related_name='publicationcitations')
    citation = models.ForeignKey(Publication, related_name='publicationcitations_referenced_by')


class PublicationAuthors(AbstractLogModel, AbstractWithDateAddedModel):
    publication = models.ForeignKey(Publication, related_name='publicationauthors')
    author = models.ForeignKey(Author, related_name='publicationauthors')


class AuthorAliasRaws(AbstractLogModel, AbstractWithDateAddedModel):
    author_alias = models.ForeignKey(AuthorAlias, related_name='authoraliasraws')
    raw = models.ForeignKey(Raw, related_name='authoraliasraws')
