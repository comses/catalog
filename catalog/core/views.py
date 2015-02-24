from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.sites.models import Site, RequestSite
from django.core import signing
from django.core.mail import send_mass_mail
from django.core.urlresolvers import reverse
from django.db.models import F
from django.shortcuts import redirect, get_object_or_404
from django.template import Context
from django.template.loader import get_template
from django.utils.decorators import method_decorator
from django.views.decorators import cache, csrf
from django.views.generic import FormView, TemplateView

from django_tables2.utils import A
from haystack.views import SearchView
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .forms import LoginForm, JournalArticleDetailForm, CustomSearchForm
from .http import dumps
from .models import Publication, STATUS_CHOICES
from .serializers import PublicationSerializer, JournalArticleSerializer, InvitationSerializer, ArchivePublicationSerializer


import markdown
import django_tables2 as tables


class InvitationEmail(object):

    def __init__(self, request):
        self.request = request
        self.plaintext_template = get_template('email/invitation-email.txt')

    @property
    def site(self):
        if Site._meta.installed:
            return Site.objects.get_current()
        else:
            return RequestSite(self.request)

    @property
    def is_secure(self):
        return self.request.is_secure()

    def get_plaintext_content(self, message, token):
        c = Context({
            'invitation_text': message,
            'site': self.site,
            'token': token,
            'secure': self.is_secure
        })
        return self.plaintext_template.render(c)


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


class PublicationTable(tables.Table):
    title = tables.LinkColumn('publication_detail', args=[A('pk')])
    class Meta:
        model = Publication
        """ Fields to display in the Publication table """
        fields = ('title', 'status', 'contact_email')


class PublicationList(LoginRequiredMixin, APIView):
    """
    List all publications
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request, format=None):
        publication_list = Publication.objects.all()

        if request.accepted_renderer.format == 'html':
            t = PublicationTable(publication_list)
            tables.RequestConfig(request, paginate={"per_page": 10}).configure(t)
            return Response({'table': t}, template_name="publications.html")

        serializer = PublicationSerializer(publication_list, many=True)
        return Response(serializer.data)


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


class EmailPreview(LoginRequiredMixin, APIView):

    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        serializer = InvitationSerializer(data=request.GET)
        if serializer.is_valid():
            message = serializer.validated_data['invitation_text']
            ie = InvitationEmail(self.request)
            plaintext_content = ie.get_plaintext_content(message, "valid:token")
            html_content = markdown.markdown(plaintext_content)
            return Response({'success': True, 'content': html_content})
        return Response({'success': False, 'errors': serializer.errors})


class CustomSearchView(SearchView):
    template = 'search/search.html'


class ContactAuthor(LoginRequiredMixin, APIView):
    """
    Send out invitations to authors to archive their work
    """
    renderer_classes = (JSONRenderer, )

    def post(self, request, format=None):
        serializer = InvitationSerializer(data=request.data)
        if serializer.is_valid():
            subject = serializer.validated_data['invitation_subject']
            message = serializer.validated_data['invitation_text']
            pk_list = CustomSearchForm(request.GET or None).search().values_list('pk', flat=True)

            pub_list = Publication.objects.filter(pk__in=pk_list).exclude(contact_email__exact='')
            messages = []

            for pub in pub_list:
                token = signing.dumps(pub.pk, salt=settings.SALT)
                ie = InvitationEmail(self.request)
                body = ie.get_plaintext_content(message, token)
                messages.append((subject, body, settings.DEFAULT_FROM_EMAIL, [pub.contact_email]))
            send_mass_mail(messages, fail_silently=False)
            pub_list.update(email_sent_count=F('email_sent_count') + 1)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
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
        pub = ArchivePublicationSerializer(instance)
        return Response({'json': dumps(pub.data)}, template_name='archive_publication_form.html')

    def post(self, request, token, format=None):
        instance = self.get_object(token)
        pub = ArchivePublicationSerializer(instance, data=request.data)
        if pub.is_valid():
            pub.validated_data['status'] = STATUS_CHOICES.AUTHOR_UPDATED
            pub.save()
            return Response(pub.data)
        return Response(pub.errors, status=status.HTTP_400_BAD_REQUEST)

