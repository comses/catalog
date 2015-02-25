from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.core.mail import send_mass_mail
from django.db.models import F

from rest_framework import serializers
from .models import Tag, Sponsor, Platform, Creator, Publication, JournalArticle, InvitationEmail


class UserSerializer(serializers.ModelSerializer):
    """
    Serializes user querysets.
    """
    publications = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'publications')


class PublicationSerializer(serializers.ModelSerializer):
    """
    Serializes publication querysets.
    """
    class Meta:
        model = Publication
        fields = ('id', 'title', 'date_published')


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag


class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform


class CreatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Creator


class SponsorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sponsor


class JournalArticleSerializer(serializers.ModelSerializer):
    """
    Serializes journal article querysets
    """
    tags = TagSerializer(many=True, read_only=True)
    platforms = PlatformSerializer(many=True, read_only=True)
    creators = CreatorSerializer(many=True, read_only=True)
    sponsors = SponsorSerializer(many=True, read_only=True)

    class Meta:
        model = JournalArticle


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


class ArchivePublicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Publication
        fields = ('title', 'archived_url', 'author_comments')
