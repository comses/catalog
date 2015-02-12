from django.forms import widgets
from django.core import signing
from django.core.mail import send_mass_mail
from django.contrib.auth.models import User
from django.template import loader

from rest_framework import serializers, pagination

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
    publications = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'publications')


class InvitationSerializer(serializers.Serializer):
    invitation_subject = serializers.CharField()
    invitation_text = serializers.CharField()
    pub_pk_list = serializers.CharField()

    def save(self, site, secure=True, salt="default_salt"):
        subject = self.validated_data['invitation_subject']
        message = self.validated_data['invitation_text']
        publication_pk_list = self.validated_data['pub_pk_list'].split(",")
        pub_list = Publication.objects.filter(pk__in=publication_pk_list)

        messages = []
        for pub in pub_list:
            context = {
                'invitation_text': message,
                'site': site,
                'token': signing.dumps(pub.pk, salt=salt),
                'secure': secure,
            }
            body = loader.render_to_string('email/invitation-email.txt',context).strip()
            messages.append((subject, body, "hello@mailinator.com", [pub.contact_email]))
        send_mass_mail(messages, fail_silently=False)
