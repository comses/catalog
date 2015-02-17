from django.contrib.auth.models import User
from rest_framework import serializers
from .models import Tag, Sponsor, Platform, Creator, Publication, JournalArticle


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
    pub_pk_list = serializers.CharField()

