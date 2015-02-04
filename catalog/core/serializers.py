from django.forms import widgets
from rest_framework import serializers, pagination

from django.contrib.auth.models import User
from .models import Publication

class PublicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Publication
        fields = ('id', 'title', 'date_published')


class PaginatedPublicationSerializer(pagination.PaginationSerializer):
    """
        Serializes page objects of user querysets.
    """

    start_index = serializers.SerializerMethodField('get_start_index')
    end_index = serializers.SerializerMethodField('get_end_index')
    num_pages = serializers.Field(source='paginator.num_pages')
    current_page = serializers.SerializerMethodField('get_curr_page')

    class Meta:
        object_serializer_class = PublicationSerializer

    def get_start_index(self, page):
        return page.start_index()

    def get_end_index(self, page):
        return page.end_index()

    def get_curr_page(self, page):
        return page.number


class UserSerializer(serializers.ModelSerializer):
    """
        Serializes user querysets.
    """
    publications = serializers.PrimaryKeyRelatedField(many=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'publications')
