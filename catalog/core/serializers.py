from django.contrib.auth.models import User
from rest_framework import serializers
from .models import Publication


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
    Serializes user querysets.
    """
    class Meta:
        model = Publication
        fields = ('id', 'title', 'date_published')


class InvitationSerializer(serializers.Serializer):
    invitation_subject = serializers.CharField()
    invitation_text = serializers.CharField()
    pub_pk_list = serializers.CharField()

