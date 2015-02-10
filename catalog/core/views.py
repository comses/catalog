from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.generic import FormView, TemplateView
from django.utils.decorators import method_decorator
from django.core.urlresolvers import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.template import Context
from django.template.loader import get_template

from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .forms import LoginForm, PublicationDetailForm, JournalArticleDetailForm, AuthorInvitationForm
from .models import Publication, JournalArticle
from .serializers import PublicationSerializer, InvitationSerializer
from .http import JsonResponse, dumps

import django_filters
import markdown


class LoginRequiredMixin(object):
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(LoginRequiredMixin, cls).as_view(**initkwargs)
        return login_required(view)


class LoginView(FormView):
    form_class = LoginForm
    template_name = 'accounts/login.html'

    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
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


def index(request):
    return render(request, 'index.html', {})


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"


class BooleanFilter(django_filters.BooleanFilter):

    def filter(self, qs, value):
        if value is True:
            return qs.exclude(**{self.name+"__exact": ''})
        elif value is False:
            return qs.filter(**{self.name+"__exact": ''})
        return qs


class PublicationFilter(django_filters.FilterSet):
    contact_email = BooleanFilter()

    def __init__(self, *args, **kwargs):
        super(PublicationFilter, self).__init__(*args, **kwargs)

        for name, field in self.filters.iteritems():
            if isinstance(field, django_filters.ChoiceFilter):
                # Add "Any" entry to choice fields.
                field.extra['choices'] = tuple([("", "Any"), ] + list(field.extra['choices']))

    class Meta:
        model = Publication
        """ Fields by which user can filter the publications """
        fields = {'status': ['exact'], 'email_sent_count': ['gte']}


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

class InviteAuthors(LoginRequiredMixin, APIView):
    """
    Send out invitations to authors
    """
    renderer_classes = (JSONRenderer, )

    def post(self, request, format=None):
        serializer = InvitationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save("from_email", "to_email")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicationDetail(LoginRequiredMixin, APIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get_object(self, pk):
        try:
            return Publication.objects.get_subclass(pk=pk)
        except Publication.DoesNotExist:
            raise Http404

    def get(self, request, pk, format=None):
        publication = self.get_object(pk)
        if request.accepted_renderer.format == 'html':
            if isinstance(publication, JournalArticle):
                form = JournalArticleDetailForm(instance=publication)
            else:
                form = PublicationDetailForm(instance=publication)

            data = {'form': form}
            return Response(data, template_name='publication_detail.html')

        serializer = PublicationSerializer(publication)
        return Response(serializer.data)

    def put(self, request, pk, format=None):
        publication = self.get_object(pk)
        serializer = PublicationSerializer(publication, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        publication = self.get_object(pk)
        publication.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmailPreview(LoginRequiredMixin, APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        form = AuthorInvitationForm(request.GET or None)
        if form.is_valid():
            plaintext_template = get_template('email/invitation-email.txt')
            c = Context({
                'invitation_text': form.cleaned_data.get('invitation_text'),
            })
            plaintext_content = plaintext_template.render(c)
            html_content = markdown.markdown(plaintext_content)
            return Response({'success': True, 'content': html_content})
        return Response({'success': False, 'errors': form.errors})

