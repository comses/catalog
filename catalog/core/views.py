from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.http import Http404
from django.shortcuts import redirect, get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators import cache, csrf
from django.views.generic import FormView, TemplateView

from haystack.views import SearchView
from hashlib import sha1
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from json import dumps

from .forms import LoginForm, JournalArticleDetailForm, CustomSearchForm
from .models import Publication, InvitationEmail
from .serializers import (PublicationSerializer, PaginatedPublicationSerializer, JournalArticleSerializer,
                          InvitationSerializer, ArchivePublicationSerializer, ContactUsSerializer)


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
        # if no next_url specified, redirect to index (dashboard page).
        return next_url if next_url else reverse('dashboard')


class LogoutView(TemplateView):

    def get(self, request, *args, **kwargs):
        user = request.user
        logout(request)
        return redirect('login')


class IndexView(TemplateView):
    template_name = 'index.html'


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'


class PublicationList(LoginRequiredMixin, APIView):
    """
    List all publications, or create a new publication
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request, format=None):
        publication_list = Publication.objects.all()

        paginator = Paginator(publication_list, 10) # Show 10 contacts per page
        page = request.QUERY_PARAMS.get('page')
        try:
            publications = paginator.page(page)
        except PageNotAnInteger:
            # If page is not an integer, deliver first page.
            publications = paginator.page(1)
        except EmptyPage:
            # If page is out of range (e.g. 9999), deliver last page of results.
            publications = paginator.page(paginator.num_pages)

        serializer = PaginatedPublicationSerializer(publications)
        return Response({ 'json': dumps(serializer.data) }, template_name="publications.html")
"""
    def post(self, request, format=None):
        serializer = PublicationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
"""

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
        # FIXME: make this part more rest friendly
        if request.accepted_renderer.format == 'html':
            form = JournalArticleDetailForm(instance=publication)
            return Response({'form': form}, template_name='publication_detail.html')
        serializer = JournalArticleSerializer(publication)
        return Response(serializer.data)


class EmailPreview(LoginRequiredMixin, APIView):
    """
    Preview the final email content
    """
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        serializer = InvitationSerializer(data=request.GET)
        if serializer.is_valid():
            # FIXME: Try to push below code to its serializer class
            message = serializer.validated_data['invitation_text']
            ie = InvitationEmail(self.request)
            plaintext_content = ie.get_plaintext_content(message, "valid:token")
            html_content = markdown.markdown(plaintext_content)
            return Response({'content': html_content})
        return Response({'content': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class CustomSearchView(SearchView):
    template = 'search/search.html'


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

        data = {
            'contact_number': '',
            'name': '',
            'timestamp': timestamp,
            'security_hash': security_hash,
            'message': '',
            'email': ''
        }
        return Response({'json': dumps(data)}, template_name='contact_us.html')

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
        instance = self.get_object(token)
        serializer = ArchivePublicationSerializer(instance)
        return Response({'json': dumps(serializer.data)}, template_name='archive_publication_form.html')

    def post(self, request, token, format=None):
        instance = self.get_object(token)
        serializer = ArchivePublicationSerializer(instance, data=request.data)
        if serializer.is_valid():
            serializer.validated_data['status'] = Publication.STATUS_CHOICES.AUTHOR_UPDATED
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

