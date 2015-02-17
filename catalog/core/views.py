from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.sites.models import Site, RequestSite
from django.core import signing
from django.core.mail import send_mass_mail
from django.core.urlresolvers import reverse
from django.shortcuts import redirect, get_object_or_404
from django.template import Context
from django.template.loader import get_template
from django.utils.decorators import method_decorator
from django.views.decorators import cache, csrf
from django.views.generic import FormView, TemplateView

from haystack.views import SearchView
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .filters import PublicationFilter
from .forms import LoginForm, PublicationDetailForm, JournalArticleDetailForm, AuthorInvitationForm, ArchivePublicationForm
from .http import dumps
from .models import Publication, JournalArticle
from .serializers import PublicationSerializer, JournalArticleSerializer, InvitationSerializer

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
    List all publications
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request, format=None):
        publication_list = Publication.objects.all()
        f = PublicationFilter(request.GET, queryset=publication_list)
        serializer = PublicationSerializer(f.qs, many=True)
        if request.accepted_renderer.format == 'html':
            return Response({
                'view_model_json': dumps(serializer.data),
                'filter': f,
                'form': AuthorInvitationForm()
            }, template_name="publications.html")

        return Response(serializer.data)


class ContactAuthor(LoginRequiredMixin, APIView):
    """
    Send out invitations to authors to archive their work
    """
    renderer_classes = (JSONRenderer, )

    def get_site(self):
        if Site._meta.installed:
            return Site.objects.get_current()
        else:
            return RequestSite(self.request)

    def post(self, request, format=None):
        serializer = InvitationSerializer(data=request.data)
        if serializer.is_valid():
            subject = serializer.validated_data['invitation_subject']
            message = serializer.validated_data['invitation_text']
            publication_pk_list = serializer.validated_data['pub_pk_list'].split(",")
            pub_list = Publication.objects.filter(pk__in=publication_pk_list).exclude(contact_email__exact= '')

            messages = []
            for pub in pub_list:
                token = signing.dumps(pub.pk, salt=settings.SALT)
                body = get_invitation_email_content(message, token, self.request.is_secure(), self.get_site())
                messages.append((subject, body, settings.DEFAULT_FROM_EMAIL, [pub.contact_email]))
            send_mass_mail(messages, fail_silently=False)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ArchivePublication(APIView):

    renderer_classes = (TemplateHTMLRenderer,)
    token_expires = 3600 * 168  # Seven days

    def get_object(self, token):
        try:
            pk = signing.loads(token, max_age=self.token_expires, salt=settings.SALT)
        except signing.BadSignature:
            pk = None
        return get_object_or_404(Publication, pk=pk)

    def get(self, request, token, format=None):
        instance = self.get_object(token)
        form = ArchivePublicationForm(instance=instance)
        return Response({'form': form}, template_name='publication_detail.html')

    def post(self, request, token, format=None):
        instance = self.get_object(token)
        form = ArchivePublicationForm(request.POST or None, instance=instance)
        if form.is_valid():
            form.save()
            return Response({'form': form}, template_name='publication_detail.html')


class PublicationDetail(LoginRequiredMixin, APIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request, pk, format=None):
        publication = Publication.objects.get_subclass(id=pk)
        if request.accepted_renderer.format == 'html':
            form = JournalArticleDetailForm(instance=publication)
            return Response({'form': form}, template_name='publication_detail.html')
        serializer = JournalArticleSerializer(publication)
        return Response(serializer.data)


def get_invitation_email_content(message, token, secure, site):
    plaintext_template = get_template('email/invitation-email.txt')
    c = Context({
        'invitation_text': message,
        'site': site,
        'token': token,
        'secure': secure,
    })
    plaintext_content = plaintext_template.render(c)
    return plaintext_content


class EmailPreview(LoginRequiredMixin, APIView):

    renderer_classes = (JSONRenderer,)

    def get_site(self):
        if Site._meta.installed:
            return Site.objects.get_current()
        else:
            return RequestSite(self.request)

    def get(self, request, format=None):
        form = AuthorInvitationForm(request.GET or None)
        if form.is_valid():
            message = form.cleaned_data.get('invitation_text')
            plaintext_content = get_invitation_email_content(message, "valid:token", self.request.is_secure(), self.get_site())
            html_content = markdown.markdown(plaintext_content)
            return Response({'success': True, 'content': html_content})
        return Response({'success': False, 'errors': form.errors})


class CustomSearchView(SearchView):
    template = 'search/search.html'
