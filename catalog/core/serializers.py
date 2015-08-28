from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.core.mail import send_mass_mail, send_mail
from django.core.validators import URLValidator
from django.db.models import F
from django.db.models.manager import BaseManager
from django.utils.translation import ugettext as _

from rest_framework import serializers, pagination
from rest_framework.compat import OrderedDict
from rest_framework.utils import model_meta

from .models import (Tag, Sponsor, Platform, Creator, Publication, Journal, JournalArticle, InvitationEmail,
                     ModelDocumentation, Note, PublicationAuditLog, )

from collections import defaultdict
from hashlib import sha1

import logging
import time

logger = logging.getLogger(__name__)


class CatalogPagination(pagination.PageNumberPagination):
    # FIXME: review & refactor: http://www.django-rest-framework.org/api-guide/pagination/
    def get_paginated_response(self, data):
        return OrderedDict([
            ('start_index', self.page.start_index()),
            ('end_index', self.page.end_index()),
            ('num_pages', self.page.paginator.num_pages),
            ('current_page', self.page.number),
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ])

###########################
#    Model Serializers    #
###########################


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serialize users.
    """

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'username', 'email')


class NoteSerializer(serializers.ModelSerializer):
    added_by = serializers.StringRelatedField(read_only=True)
    date_added = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')
    deleted_on = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')
    deleted_by = serializers.StringRelatedField(read_only=True)
    is_deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Note
        fields = ('id', 'text',  'publication', 'added_by', 'date_added', 'deleted_on', 'deleted_by', 'is_deleted')


class PublicationAuditLogSerializer(serializers.ModelSerializer):
    creator = serializers.StringRelatedField(read_only=True)
    date_added = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')

    class Meta:
        model = PublicationAuditLog
        read_only_fields = ('id', 'message', 'action', 'date_added', 'publication')


class SemiControlledNameSerializer(serializers.ModelSerializer):

    def validate(self, data):
        name = data['name'].strip()
        if name:
            obj, created = self.Meta.model.objects.get_or_create(name=name)
            return obj
        else:
            raise serializers.ValidationError("No name specified: {}".format(data))

    class Meta:
        abstract = True


class TagSerializer(SemiControlledNameSerializer):

    class Meta:
        model = Tag
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }


class PlatformSerializer(SemiControlledNameSerializer):
    class Meta:
        model = Platform
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }


class SponsorSerializer(SemiControlledNameSerializer):

    class Meta:
        model = Sponsor
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }


class ModelDocumentationSerializer(SemiControlledNameSerializer):

    class Meta:
        model = ModelDocumentation
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }


class JournalSerializer(SemiControlledNameSerializer):

    class Meta:
        model = Journal
        extra_kwargs = {
            "name": {
                "validators": [],
            },
        }


class CreatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Creator

    def validate(self, data):
        creator, created = Creator.objects.get_or_create(first_name=data['first_name'],
                                                         last_name=data['last_name'],
                                                         creator_type=data['creator_type'])
        return creator


class PublicationSerializer(serializers.ModelSerializer):
    """
    Serializes publication querysets.
    """
    detail_url = serializers.CharField(source='get_absolute_url', read_only=True)
    curator_detail_url = serializers.CharField(source='get_curator_url', read_only=True)
    assigned_curator = serializers.StringRelatedField()
    date_modified = serializers.DateTimeField(read_only=True, format='%m/%d/%Y %H:%M')
    notes = NoteSerializer(source='note_set', many=True, read_only=True)
    activity_logs = PublicationAuditLogSerializer(source='audit_log_set', many=True, read_only=True)
    tags = TagSerializer(many=True)
    platforms = PlatformSerializer(many=True)
    sponsors = SponsorSerializer(many=True)
    journal = JournalSerializer()
    model_documentation = ModelDocumentationSerializer(many=True)
    creators = CreatorSerializer(many=True)

    """
    XXX: copy-pasted from default ModelSerializer code but omitting the raise_errors_on_nested_writes. Revisit at some
    point. See http://www.django-rest-framework.org/api-guide/serializers/#writable-nested-representations for more
    details
    """
    def update(self, instance, validated_data):
        self._modified_data = defaultdict(tuple)
        for attr, value in validated_data.items():
            modified = False
            old_value = getattr(instance, attr)
            new_value = None
            if isinstance(old_value, BaseManager):
                # compare against related manager values converted to string
                old_value = map(unicode, old_value.all())
                new_value = map(unicode, value)
                if set(old_value) != set(new_value):
                    modified = True
            elif old_value != value:
                modified = True
            if modified:
                # logger.debug("setting %s: %s => %s", attr, old_value, value)
                self._modified_data[attr] = (old_value, new_value)
                setattr(instance, attr, value)
        instance.save()
        return instance

    @property
    def modified_data(self):
        return getattr(self, '_modified_data', defaultdict(tuple))

    @property
    def modified_data_text(self):
        # md_list = [u"{}: {} -> {}".format(key, pair[0], pair[1]) for key, pair in self.modified_data.items()]
        mdl = [u"{}: {} -> {}".format(key, pair[0], pair[1]) for key, pair in self.modified_data.items()]
        return u" | ".join(mdl)

    def create(self, validated_data):
        ModelClass = self.Meta.model

        # Remove many-to-many relationships from validated_data.
        # They are not valid arguments to the default `.create()` method,
        # as they require that the instance has already been saved.
        info = model_meta.get_field_info(ModelClass)
        many_to_many = {}
        for field_name, relation_info in info.relations.items():
            if relation_info.to_many and (field_name in validated_data):
                many_to_many[field_name] = validated_data.pop(field_name)

        instance = ModelClass.objects.create(**validated_data)

        # Save many-to-many relationships after the instance is created.
        if many_to_many:
            for field_name, value in many_to_many.items():
                setattr(instance, field_name, value)

        return instance

    class Meta:
        model = Publication
        fields = ('id', 'title', 'date_published', 'date_modified', 'detail_url', 'curator_detail_url', 'status',
                  'assigned_curator', 'activity_logs', 'notes', )


class JournalArticleSerializer(PublicationSerializer):
    """
    Serializes journal article querysets
    """

    class Meta:
        model = JournalArticle
        exclude = ('date_added', 'zotero_date_added', 'zotero_date_modified', 'zotero_key',
                   'email_sent_count', 'date_published_text', 'author_comments')


class ContactFormSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.EmailField()
    message = serializers.CharField()

    security_hash = serializers.CharField()
    timestamp = serializers.CharField()
    # honeypot field
    contact_number = serializers.CharField(allow_blank=True)

    def validate_contact_number(self, value):
        if value:
            raise serializers.ValidationError("Honeypot bot alert failed.")
        return value

    def validate_timestamp(self, value):
        """ spam protection currently only accept form submissions between 3 seconds and 2 hours """
        min_seconds = 3
        max_seconds = 2 * 60 * 60
        difference = float(time.time()) - float(value)
        if min_seconds < difference < max_seconds:
            raise serializers.ValidationError("Timestamp check failed")
        return value

    def validate(self, data):
        security_hash = data['security_hash']
        timestamp = str(data['timestamp'])

        info = (timestamp, settings.SECRET_KEY)
        new_security_hash = sha1("".join(info)).hexdigest()
        if security_hash == new_security_hash:
            return data
        logger.warn("timestamp was altered, flagging as invalid")
        raise serializers.ValidationError("timestamp was tampered.")

    def save(self):
        # name = self.validated_data['name']
        email = self.validated_data['email']
        message = self.validated_data['message']

        send_mail(from_email=email,
                  message=message,
                  subject="CoMSES Catalog Feedback",
                  recipient_list=[settings.DEFAULT_FROM_EMAIL])


class InvitationSerializer(serializers.Serializer):
    invitation_subject = serializers.CharField()
    invitation_text = serializers.CharField()

    def save(self, request, pk_list):
        subject = self.validated_data['invitation_subject']
        message = self.validated_data['invitation_text']

        pub_list = Publication.objects.filter(pk__in=pk_list).exclude(contact_email__exact='')
        messages = []

        for pub in pub_list:
            token = signing.dumps(pub.pk, salt=settings.SALT)
            ie = InvitationEmail(request)
            body = ie.get_plaintext_content(message, token)
            messages.append((subject, body, settings.DEFAULT_FROM_EMAIL, [pub.contact_email]))
        send_mass_mail(messages, fail_silently=False)
        pub_list.update(email_sent_count=F('email_sent_count') + 1)


class UpdateModelUrlSerializer(serializers.ModelSerializer):
    class Meta:
        model = Publication
        fields = ('title', 'code_archive_url', 'author_comments')
        read_only_fields = ('title',)

    def validate(self, data):
        url = data['code_archive_url']
        validator = URLValidator(message=_("Please enter a valid URL for this computational model."))
        validator(url)
        return data
