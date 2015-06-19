from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.urlresolvers import reverse
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators import cache, csrf
from django.views.generic import FormView, TemplateView
from haystack.query import SearchQuerySet
from haystack.generic_views import SearchView
from hashlib import sha1
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework import status
from json import dumps
from datetime import datetime, timedelta

from .forms import LoginForm, CatalogSearchForm
from .models import (Publication, InvitationEmail, Platform, Sponsor, Tag, Journal, ModelDocumentation, Note, )
from .serializers import (PublicationSerializer, CatalogPagination, JournalArticleSerializer, InvitationSerializer,
                          UpdateModelUrlSerializer, ContactFormSerializer, UserProfileSerializer, NoteSerializer, )

import logging
import markdown
import time

logger = logging.getLogger(__name__)


class LoginRequiredMixin(object):
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(LoginRequiredMixin, cls).as_view(**initkwargs)
        return login_required(view)


class LoginView(FormView):
    form_class = LoginForm
    template_name = 'accounts/login.html'

    @method_decorator(csrf.csrf_protect)
    @method_decorator(cache.never_cache)
    def dispatch(self, *args, **kwargs):
        return super(LoginView, self).dispatch(*args, **kwargs)

    def form_valid(self, form):
        login(self.request, form.get_user())
        return super(LoginView, self).form_valid(form)

    def get_success_url(self):
        next_url = self.request.GET.get('next', '')
        # if no next_url specified, redirect to dashboard page
        return next_url if next_url else reverse('core:dashboard')


class LogoutView(TemplateView):

    def get(self, request, *args, **kwargs):
        logout(request)
        return redirect('core:index')


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_context_data(self, number_of_publications=20, **kwargs):
        context = super(DashboardView, self).get_context_data(**kwargs)
        last_week_datetime = datetime.now() - timedelta(days=7)
        context['status'] = {}

        pub_count = Publication.objects.all().values('status').annotate(total=Count('status')).order_by('-total')
        context['status']['TOTAL'] = 0
        for item in pub_count:
            context['status']['TOTAL'] += item['total']
            context['status'][item['status']] = item['total']

        context['untagged_publications_count'] = Publication.objects.filter(status=Publication.Status.UNTAGGED,
                                                                            assigned_curator=self.request.user).count()
        context['recently_author_updated'] = Publication.objects.select_subclasses().filter(
            status=Publication.Status.AUTHOR_UPDATED)
        recently_updated_publications = Publication.objects.select_subclasses().exclude(
            status=Publication.Status.AUTHOR_UPDATED)
        context['recently_updated'] = recently_updated_publications.filter(
            date_modified__gte=last_week_datetime).order_by('-date_modified')[:number_of_publications]
        return context


class UserProfileView(LoginRequiredMixin, GenericAPIView):
    """
    Retrieve or Update User Profile of current logged in User
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request):
        serializer = UserProfileSerializer(instance=request.user)
        return Response({'json': dumps(serializer.data)}, template_name="accounts/profile.html")

    def post(self, request):
        serializer = UserProfileSerializer(instance=request.user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicationList(LoginRequiredMixin, GenericAPIView):
    """
    List all publications, or create a new publication
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)
    # FIXME: look into properly implementing pagination via django rest framework
    pagination_class = CatalogPagination

    def get(self, request, format=None):
        publication_list = Publication.objects.all()
        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(publication_list, request)
        serializer = PublicationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        return Response({'json': dumps(response)}, template_name="publication/list.html")

    def post(self, request, format=None):
        # adding current user to added_by field
        request.data.update({'added_by': request.user.id})
        # FIXME: hard coded JournalArticleSerializer should instead depend on incoming data
        serializer = JournalArticleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicationDetail(LoginRequiredMixin, GenericAPIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get_object(self, pk):
        return get_object_or_404(Publication.objects.select_subclasses(), pk=pk)

    def get(self, request, pk, format=None):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication)
        return Response({'json': dumps(serializer.data), 'pk': publication.pk},
                        template_name='publication/detail.html')

    def put(self, request, pk):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CuratorPublicationDetail(LoginRequiredMixin, GenericAPIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get_object(self, pk):
        return get_object_or_404(Publication.objects.select_subclasses(), pk=pk)

    def get(self, request, pk, format=None):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication)
        return Response({'json': dumps(serializer.data), 'pk': pk},
                        template_name='workflow/curator_publication_detail.html')

    def put(self, request, pk):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        logger.warn("serializer failed validation: %s", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NoteDetail(LoginRequiredMixin, GenericAPIView):
    """
    Retrieve, update or delete a note instance.
    """
    renderer_classes = (JSONRenderer, )

    def get_object(self, pk):
        return get_object_or_404(Note, pk=pk)

    def get(self, request, pk, format=None):
        note = self.get_object(pk)
        serializer = NoteSerializer(note)
        return Response({'json': dumps(serializer.data)})

    def put(self, request, pk):
        note = self.get_object(pk)
        serializer = NoteSerializer(note, data=request.data)
        logger.debug("serializer: %s", serializer)
        if serializer.is_valid():
            serializer.save(added_by=request.user)
            return Response(serializer.data)
        logger.error("serializer errors: %s", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        note = self.get_object(pk)
        note.deleted_by = request.user
        note.deleted_on = datetime.today()
        note.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NoteList(LoginRequiredMixin, GenericAPIView):
    """
    Get all the notes or create a note
    """
    renderer_classes = (JSONRenderer, )

    def get(self, request, format=None):
        note = Note.objects.all()
        serializer = NoteSerializer(note, many=True)
        return Response({'json': dumps(serializer.data)})

    def post(self, request):
        # adding current user to added_by field
        serializer = NoteSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(added_by=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EmailPreview(LoginRequiredMixin, GenericAPIView):
    """
    Preview the final email content
    """
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        serializer = InvitationSerializer(data=request.GET)
        if serializer.is_valid():
            message = serializer.validated_data['invitation_text']
            ie = InvitationEmail(self.request)
            plaintext_content = ie.get_plaintext_content(message, "valid:token")
            html_content = markdown.markdown(plaintext_content)
            return Response({'content': html_content})
        return Response({'content': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class AutocompleteView(LoginRequiredMixin, GenericAPIView):

    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        query = request.GET.get('q', '').strip()
        sqs = SearchQuerySet().models(self.model_class)
        if query:
            sqs = sqs.autocomplete(name=query)
        data = [{'id': int(result.pk), 'name': result.name} for result in sqs]
        return Response(dumps(data))


class PlatformSearchView(AutocompleteView):

    @property
    def model_class(self):
        return Platform


class SponsorSearchView(AutocompleteView):

    @property
    def model_class(self):
        return Sponsor


class TagSearchView(AutocompleteView):

    @property
    def model_class(self):
        return Tag


class ModelDocumentationSearchView(AutocompleteView):

    @property
    def model_class(self):
        return ModelDocumentation


class JournalSearchView(AutocompleteView):

    @property
    def model_class(self):
        return Journal


class CatalogSearchView(LoginRequiredMixin, SearchView):
    """ generic django haystack searchview using a custom form """
    form_class = CatalogSearchForm


class CuratorWorkflowView(LoginRequiredMixin, SearchView):
    """ django haystack searchview """
    template_name = 'workflow/curator.html'
    form_class = CatalogSearchForm

    def get_context_data(self, **kwargs):
        context = super(CuratorWorkflowView, self).get_context_data(**kwargs)
        sqs = SearchQuerySet().filter(assigned_curator=self.request.user).facet('status')
        context.update(facets=sqs.facet_counts(),
                       total_number_of_records=Publication.objects.filter(assigned_curator=self.request.user).count())
        return context

    def get_queryset(self):
        sqs = super(CuratorWorkflowView, self).get_queryset()
        return sqs.filter(assigned_curator=self.request.user).order_by('-last_modified')


class ContactAuthor(LoginRequiredMixin, GenericAPIView):
    """
    Emails invitations to authors to archive their work
    """
    renderer_classes = (JSONRenderer, )

    def post(self, request, format=None):
        serializer = InvitationSerializer(data=request.data)
        pk_list = CatalogSearchForm(request.GET or None).search().values_list('pk', flat=True)
        if serializer.is_valid():
            serializer.save(self.request, pk_list)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContactFormView(GenericAPIView):

    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request):
        timestamp = str(time.time())
        info = (timestamp, settings.SECRET_KEY)
        security_hash = sha1("".join(info)).hexdigest()

        data = {'contact_number': '',
                'name': '',
                'timestamp': timestamp,
                'security_hash': security_hash,
                'message': '',
                'email': ''}
        user = request.user
        if user.is_authenticated():
            data.update(name=user.get_full_name(), email=user.email)
        serializer = ContactFormSerializer(data)
        return Response({'json': dumps(serializer.data)}, template_name='contact_us.html')

    def post(self, request):
        serializer = ContactFormSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UpdateModelUrlView(GenericAPIView):

    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)
    token_expires = 3600 * 168  # Seven days

    def get_object(self, token):
        try:
            pk = signing.loads(token, max_age=self.token_expires, salt=settings.SALT)
        except signing.BadSignature:
            pk = None
        return get_object_or_404(Publication, pk=pk)

    def get(self, request, token, format=None):
        serializer = UpdateModelUrlSerializer(self.get_object(token))
        return Response({'json': dumps(serializer.data)}, template_name='publication/update_model_url.html')

    def post(self, request, token, format=None):
        serializer = UpdateModelUrlSerializer(self.get_object(token), data=request.data)
        if serializer.is_valid():
            serializer.validated_data['status'] = Publication.STATUS_CHOICES.AUTHOR_UPDATED
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
