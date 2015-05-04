from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.urlresolvers import reverse
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect, get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators import cache, csrf
from django.views.generic import FormView, TemplateView

from haystack.query import SearchQuerySet
from haystack.views import SearchView
from hashlib import sha1
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from json import dumps
from datetime import datetime, timedelta

from .forms import LoginForm, JournalArticleDetailForm, CustomSearchForm
from .models import Publication, InvitationEmail, Platform, Sponsor, Tag, Journal, ModelDocumentation, Note
from .serializers import (PublicationSerializer, CustomPagination, JournalArticleSerializer, PlatformSerializer,
                          InvitationSerializer, ArchivePublicationSerializer, ContactUsSerializer, UserProfileSerializer,
                          NoteSerializer, )

import time
import markdown


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
        return next_url if next_url else reverse('dashboard')


class LogoutView(TemplateView):

    def get(self, request, *args, **kwargs):
        logout(request)
        return redirect('login')


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_context_data(self, **kwargs):
        context = super(DashboardView, self).get_context_data(**kwargs)
        last_week_datetime = datetime.now() - timedelta(days=7)
        context['status'] = {}

        pub_count = Publication.objects.all().values('status').annotate(total=Count('status')).order_by('-total')
        total = 0
        for item in pub_count:
            total += item['total']
            context['status'][item['status']] = item['total']
        context['status']['TOTAL'] = total

        context['untagged_publications_count'] = Publication.objects.filter(status=Publication.Status.UNTAGGED, assigned_curator=self.request.user).count()
        context['recently_author_updated'] = Publication.objects.select_subclasses().filter(status=Publication.Status.AUTHOR_UPDATED)
        context['recently_updated'] = Publication.objects.select_subclasses().exclude(status=Publication.Status.AUTHOR_UPDATED).filter(date_modified__gte=last_week_datetime).order_by('-date_modified')[:10]
        return context


class UserProfileView(LoginRequiredMixin, APIView):
    """
    Retrieve or Update of current logged in User
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request, format=None):
        serializer = UserProfileSerializer(instance=request.user)
        return Response({'json': dumps(serializer.data)}, template_name="accounts/profile.html")

    def post(self, request, format=None):
        serializer = UserProfileSerializer(instance=request.user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicationList(LoginRequiredMixin, APIView):
    """
    List all publications, or create a new publication
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request, format=None):
        publication_list = Publication.objects.all()
        paginator = CustomPagination()
        result_page = paginator.paginate_queryset(publication_list, request)
        serializer = PublicationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        return Response({ 'json': dumps(response) }, template_name="publications.html")

    def post(self, request, format=None):
        serializer = JournalArticleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicationDetail(LoginRequiredMixin, APIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get_object(self, pk):
        try:
            return Publication.objects.get_subclass(id=pk)
        except Publication.DoesNotExist:
            raise Http404("Publication does not exist")

    def get(self, request, pk, format=None):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication)
        return Response({ 'json': dumps(serializer.data) }, template_name='publication_detail.html')

    def put(self, request, pk):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CuraterPublicationDetail(LoginRequiredMixin, APIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get_object(self, pk):
        try:
            return Publication.objects.get_subclass(id=pk)
        except Publication.DoesNotExist:
            raise Http404("Publication does not exist")

    def get(self, request, pk, format=None):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication)
        return Response({ 'json': dumps(serializer.data) }, template_name='curator_publication_detail.html')

    def put(self, request, pk):
        publication = self.get_object(pk)
        serializer = JournalArticleSerializer(publication, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NoteDetail(LoginRequiredMixin, APIView):
    """
    Retrieve, update or delete a note instance.
    """
    renderer_classes = (JSONRenderer, )

    def get_object(self, pk):
        try:
            return Note.objects.get(id=pk)
        except Note.DoesNotExist:
            raise Http404("Note does not exist")

    def get(self, request, pk, format=None):
        note = self.get_object(pk)
        serializer = NoteSerializer(note)
        return Response({ 'json': dumps(serializer.data) })

    def put(self, request, pk):
        note = self.get_object(pk)
        serializer = NoteSerializer(note, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        serializer = self.get_object(pk)
        serializer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NoteList(LoginRequiredMixin, APIView):
    """
    Get all the notes or create a note
    """

    def get(self, request, format=None):
        note = Note.objects.all()
        serializer = NoteSerializer(note, many=True)
        return Response({ 'json': dumps(serializer.data) })

    def post(self, request):
        serializer = NoteSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EmailPreview(LoginRequiredMixin, APIView):
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


class PlatformSearchView(LoginRequiredMixin, APIView):

    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        sqs = SearchQuerySet().autocomplete(name=request.GET.get('q', '')).models(Platform)
        data = [{"id": int(result.pk), "name": result.name} for result in sqs]
        return Response(dumps(data))


class SponsorSearchView(LoginRequiredMixin, APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        sqs = SearchQuerySet().autocomplete(name=request.GET.get('q', '')).models(Sponsor)
        data = [{"id": int(result.pk), "name": result.name} for result in sqs]
        return Response(dumps(data))


class TagSearchView(LoginRequiredMixin, APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        sqs = SearchQuerySet().autocomplete(value=request.GET.get('q', '')).models(Tag)
        data = [{"id": int(result.pk), "value": result.value} for result in sqs]
        return Response(dumps(data))


class ModelDocSearchView(LoginRequiredMixin, APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        sqs = SearchQuerySet().autocomplete(value=request.GET.get('q', '')).models(ModelDocumentation)
        data = [{"id": int(result.pk), "value": result.value} for result in sqs]
        return Response(dumps(data))


class JournalSearchView(LoginRequiredMixin, APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        sqs = SearchQuerySet().autocomplete(name=request.GET.get('q', '')).models(Journal)
        data = [{"id": int(result.pk), "name": result.name} for result in sqs]
        return Response(dumps(data))


class CustomSearchView(SearchView):
    template = 'search/search.html'


class AssignedPubSearchView(SearchView):
    template = 'search/search_assigned_publication.html'

    def get_results(self):
        return self.form.search(self.request.user)


class ContactAuthor(LoginRequiredMixin, APIView):
    """
    Send out invitations to authors to archive their work
    """
    renderer_classes = (JSONRenderer, )

    def post(self, request, format=None):
        serializer = InvitationSerializer(data=request.data)
        pk_list = CustomSearchForm(request.GET or None).search().values_list('pk', flat=True)
        if serializer.is_valid():
            serializer.save(self.request, pk_list)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContactUsView(APIView):

    renderer_classes = (TemplateHTMLRenderer, JSONRenderer, )

    def get(self, request, format=None):
        timestamp = str(time.time())
        info = (timestamp, settings.SECRET_KEY)
        security_hash = sha1("".join(info)).hexdigest()

        data = {'contact_number': '', 'name': '', 'timestamp': timestamp,
                'security_hash': security_hash, 'message': '', 'email': ''}

        serializer = ContactUsSerializer(data)

        return Response({'json': dumps(serializer.data)}, template_name='contact_us.html')

    def post(self, request, format=None):
        serializer = ContactUsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ArchivePublication(APIView):

    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)
    token_expires = 3600 * 168  # Seven days

    def get_object(self, token):
        try:
            pk = signing.loads(token, max_age=self.token_expires, salt=settings.SALT)
        except signing.BadSignature:
            pk = None
        return get_object_or_404(Publication, pk=pk)

    def get(self, request, token, format=None):
        serializer = ArchivePublicationSerializer(self.get_object(token))
        return Response({'json': dumps(serializer.data)}, template_name='archive_publication_form.html')

    def post(self, request, token, format=None):
        serializer = ArchivePublicationSerializer(self.get_object(token), data=request.data)
        if serializer.is_valid():
            serializer.validated_data['status'] = Publication.STATUS_CHOICES.AUTHOR_UPDATED
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
