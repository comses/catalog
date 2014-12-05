from django.forms import widgets
from rest_framework import serializers

from django.contrib.auth.models import User
from .models import Publication

class PublicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Publication
        fields = ('id', 'title', 'abstract', 'added_by')


class UserSerializer(serializers.ModelSerializer):
    publications = serializers.PrimaryKeyRelatedField(many=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'publications')
