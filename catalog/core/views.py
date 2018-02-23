import csv
import json
import logging
import time
from collections import Counter
from datetime import timedelta
from hashlib import sha1
from json import dumps

import markdown
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME, login as auth_login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.core.cache import cache
from django.db import models
from django.db.models import Count, Q, F, Value as V
from django.db.models.functions import Concat
from django.http import HttpResponse
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, resolve_url, render_to_response
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import is_safe_url
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView, FormView
from haystack.generic_views import SearchView
from haystack.query import SearchQuerySet
from rest_framework import status, renderers, generics
from rest_framework.response import Response

from citation.export_data import create_csv
from citation.models import Publication, InvitationEmail, Platform, Sponsor, ModelDocumentation, Tag, Container
from citation.serializers import (InvitationSerializer,CatalogPagination, PublicationListSerializer,
                                  UpdateModelUrlSerializer, ContactFormSerializer, UserProfileSerializer,
                                  RelationSerializer, AuthorRelationSerializer)

from .forms import CatalogAuthenticationForm, CatalogSearchForm

logger = logging.getLogger(__name__)


def export_data(self):
    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="all_valid_data.csv"'
    writer = csv.writer(response)
    create_csv(writer)
    return response


class LoginView(FormView):
    """
    Pulled from github django master, replace when django.contrib.auth.views.LoginView is available in release.
    """
    form_class = CatalogAuthenticationForm
    template_name = 'accounts/login.html'
    authentication_form = None
    redirect_field_name = REDIRECT_FIELD_NAME
    redirect_authenticated_user = False
    extra_context = None

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        if self.redirect_authenticated_user and self.request.user.is_authenticated:
            redirect_to = self.get_success_url()
            if redirect_to == self.request.path:
                raise ValueError(
                    "Redirection loop for authenticated user detected. Check that "
                    "your LOGIN_REDIRECT_URL doesn't point to a login page."
                )
            return HttpResponseRedirect(redirect_to)
        return super(LoginView, self).dispatch(request, *args, **kwargs)

    def get_success_url(self):
        """Ensure the user-originating redirection URL is safe."""
        redirect_to = self.request.POST.get(
            self.redirect_field_name,
            self.request.GET.get(self.redirect_field_name, '')
        )
        url_is_safe = is_safe_url(
            url=redirect_to,
            host=self.request.get_host(),
        )
        if not url_is_safe:
            return resolve_url(settings.LOGIN_REDIRECT_URL)
        return redirect_to

    def get_form_class(self):
        return self.authentication_form or self.form_class

    def form_valid(self, form):
        """Security check complete. Log the user in."""
        auth_login(self.request, form.get_user())
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super(LoginView, self).get_context_data(**kwargs)
        context.update({
            self.redirect_field_name: self.get_success_url(),
        })
        if self.extra_context is not None:
            context.update(self.extra_context)
        return context


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_context_data(self, number_of_publications=25, **kwargs):
        context = super(DashboardView, self).get_context_data(**kwargs)
        last_week_datetime = timezone.now() - timedelta(days=7)
        context['status'] = Counter()

        pub_count = Publication.objects.filter(is_primary=True).values('status').annotate(
            total=Count('status')).order_by('-total')
        for item in pub_count:
            total_count = item['total']
            context['status'][item['status']] = total_count
            context['status']['TOTAL'] += total_count
        n_flagged = Publication.objects.filter(is_primary=True, flagged=True).count()
        context['flagged'] = n_flagged

        context['complete'] = Publication.objects.filter(
            is_primary=True, status=Publication.Status.REVIEWED).exclude(code_archive_url='').count()
        context['incomplete'] = context['status'][Publication.Status.REVIEWED] - context['complete']

        context['unreviewed_publications_count'] = Publication.objects.filter(
            status=Publication.Status.UNREVIEWED, assigned_curator=self.request.user).count()
        context['recently_author_updated'] = Publication.objects.filter(
            status=Publication.Status.AUTHOR_UPDATED)
        recently_updated_publications = Publication.objects.exclude(
            status=Publication.Status.AUTHOR_UPDATED)
        recently_updated = recently_updated_publications.filter(
            date_modified__gte=last_week_datetime, is_primary=True).order_by('-date_modified')[:number_of_publications]
        context['recently_updated'] = recently_updated
        list = [pub.id for pub in recently_updated]
        cache_dct = cache.get_many(list)
        context['contribution'] = cache_dct
        return context


class EmailPreview(LoginRequiredMixin, generics.GenericAPIView):
    """
    Preview the final email content
    """
    renderer_classes = (renderers.JSONRenderer,)

    def get(self, request, format=None):
        serializer = InvitationSerializer(data=request.GET)
        if serializer.is_valid():
            message = serializer.validated_data['invitation_text']
            ie = InvitationEmail(self.request)
            plaintext_content = ie.get_plaintext_content(message, "valid:token")
            html_content = markdown.markdown(plaintext_content)
            return Response({'content': html_content})
        return Response({'content': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class ContactAuthor(LoginRequiredMixin, generics.GenericAPIView):
    """
    Emails invitations to authors to archive their work
    """
    renderer_classes = (renderers.JSONRenderer,)

    def post(self, request, format=None):
        serializer = InvitationSerializer(data=request.data)
        pk_list = CatalogSearchForm(request.GET or None).search().values_list('pk', flat=True)
        if serializer.is_valid():
            serializer.save(self.request, pk_list)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContactFormView(generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        timestamp = str(time.time())
        info = (timestamp, settings.SECRET_KEY)
        security_hash = sha1("".join(info).encode("ascii"), ).hexdigest()

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


class UpdateModelUrlView(generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)
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


class UserProfileView(LoginRequiredMixin, generics.GenericAPIView):
    """
    Retrieve or Update User Profile of current logged in User
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        serializer = UserProfileSerializer(instance=request.user)
        return Response({'profile': dumps(serializer.data)}, template_name="accounts/profile.html")

    def post(self, request):
        serializer = UserProfileSerializer(instance=request.user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'profile': dumps(serializer.data)})
        return Response({'errors': dumps(serializer.errors)}, status=status.HTTP_400_BAD_REQUEST)


# Other Views
class AutocompleteView(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.JSONRenderer,)

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
        return Container


class CatalogSearchView(LoginRequiredMixin, SearchView):
    """ generic django haystack SearchView using a custom form """
    form_class = CatalogSearchForm
    """ Retrieving the tags value from request and passing it to the CatalogSearchForm"""
    def get_form_kwargs(self):
        kw = super(CatalogSearchView, self).get_form_kwargs()
        kw['tag_list'] = self.request.GET.getlist('tags')
        return kw


class CuratorWorkflowView(LoginRequiredMixin, SearchView):
    """ django haystack searchview """
    template_name = 'workflow/curator.html'
    form_class = CatalogSearchForm

    def get_context_data(self, **kwargs):
        context = super(CuratorWorkflowView, self).get_context_data(**kwargs)
        sqs = SearchQuerySet().filter(assigned_curator=self.request.user, is_primary=True).facet('status')
        context.update(facets=sqs.facet_counts(),
                       total_number_of_records=Publication.objects.filter(assigned_curator=self.request.user).count())
        return context

    def get_queryset(self):
        sqs = super(CuratorWorkflowView, self).get_queryset()
        return sqs.filter(assigned_curator=self.request.user, is_primary=True).order_by('-last_modified', '-status')


############################################  VISUALIZATION   ##########################################################


class VisualizationWorkflowView(LoginRequiredMixin, generics.GenericAPIView):
    def get(self, request):
        return render_to_response("visualization/viz_index.html")


# Generates journal relation - the number of paper published having same journal info to the code made available
class JournalPublicationRelation(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)
    pagination_class = CatalogPagination

    def get(self, request):
        response = cache.get('JournalPublicationRelation')
        if response is None:
            pubs = Publication.api.primary(status='REVIEWED', prefetch=False).annotate(
                name=F('container__name')).values('name').order_by(
                'name').annotate(published=Count('name'),
                                 code_available=models.Sum(
                                     models.Case(models.When(~Q(code_archive_url=''), then=1),
                                                 default=0, output_field=models.IntegerField()))) \
                .values('name', 'published', 'code_available').order_by('-published')

            paginator = CatalogPagination()
            result_page = paginator.paginate_queryset(pubs, request)
            serializer = RelationSerializer(result_page, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response['id'] = "Journal"
            cache.set('JournalPublicationRelation', response, 86600)
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


# Generates sponsor relation - the number of paper published having same sponsor info to the code made available
class SponsorPublicationRelation(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)
    pagination_class = CatalogPagination

    def get(self, request):
        response = cache.get('SponsorPublicationRelation')
        if response is None:
            pubs = Publication.api.primary(status='REVIEWED', prefetch=False).annotate(
                name=F('sponsors__name')).values('name').order_by(
                'name').annotate(published=Count('name'),
                                 code_available=models.Sum(
                                     models.Case(models.When(~Q(code_archive_url=''), then=1),
                                                 default=0, output_field=models.IntegerField()))) \
                .values('name', 'published', 'code_available').order_by('-published')

            paginator = CatalogPagination()
            result_page = paginator.paginate_queryset(pubs, request)
            serializer = RelationSerializer(result_page, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response['id'] = "Sponsor"
            cache.set('SponsorPublicationRelation', response, 86600)
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


# Generates platform relation - the number of paper published having same platform info to the code made available
class PlatformPublicationRelation(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)
    pagination_class = CatalogPagination

    def get(self, request):
        response = cache.get('PlatformPublicationRelation')
        if response is None:
            pubs = Publication.api.primary(status='REVIEWED', prefetch=False).annotate(
                name=F('platforms__name')).values('name').order_by(
                'name').annotate(published=Count('name'),
                                 code_available=models.Sum(
                                     models.Case(models.When(~Q(code_archive_url=''), then=1),
                                                 default=0, output_field=models.IntegerField()))) \
                .values('name', 'published', 'code_available').order_by('-published')

            paginator = CatalogPagination()
            result_page = paginator.paginate_queryset(pubs, request)
            serializer = RelationSerializer(result_page, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response['id'] = "Platform"
            cache.set('PlatformPublicationRelation', response, 86600)
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


# Generates author relation - the number of paper published to the code made available
class AuthorPublicationRelation(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)
    pagination_class = CatalogPagination

    def get(self, request):
        response = cache.get('AuthorPublicationRelation')
        if response is None:
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True). \
                annotate(given_name=F('creators__given_name'), family_name=F('creators__family_name')).values(
                'given_name',
                'family_name').order_by(
                'given_name', 'family_name').annotate(published=Count('given_name'),
                                                      code_available=models.Sum(models.Case(
                                                          models.When(~Q(code_archive_url=''), then=1),
                                                          default=0,
                                                          output_field=models.IntegerField())),
                                                      name=Concat('given_name', V(' '),
                                                                  'family_name'),
                                                      ).values(
                'name', 'published', 'code_available', 'given_name', 'family_name').order_by('-published')

            paginator = CatalogPagination()
            result_page = paginator.paginate_queryset(pubs, request)
            serializer = AuthorRelationSerializer(result_page, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response['id'] = "Author"
            cache.set('AuthorPublicationRelation', response, 86600)
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


# Generates the model documentation variable relation among themselves throughout dataset distribution
class ModelDocumentationPublicationRelation(LoginRequiredMixin, TemplateView):
    template_name = 'visualization/model_documentation_publication_relation.html'

    def get_context_data(self, **kwargs):
        context = super(ModelDocumentationPublicationRelation, self).get_context_data(**kwargs)
        response = cache.get('ModelDocumentationPublicationRelation')
        if response is not None:
            context['value'] = response
        else:
            md = ModelDocumentation.objects.all().values_list('name')
            total = Publication.objects.filter(is_primary=True, status='REVIEWED').count()
            value = []
            for name in list(md):
                if name[0] is not None:
                    value.append({'name': name[0], 'count': "{0:.2f}".format(
                        Publication.objects.filter(is_primary=True, status='REVIEWED',
                                                   model_documentation__name=name[
                                                       0]).count() * 100 / total)})
            context['value'] = value
            cache.set('ModelDocumentationPublicationRelation', value, 86600)
        return context

# Generates the staged distribution of the requested id : Journal, Sponsor, Platform, Model Doc, Author
class RelationDetail(LoginRequiredMixin, generics.GenericAPIView):
    def get(self, request, id=None, name=None):
        pubs = None
        if id == 'Journal':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, container__name=name)
        elif id == 'Sponsor':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, sponsors__name=name)
        elif id == 'Platform':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, platforms__name=name)
        elif id == 'Modeldoc':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, model_documentation__name=name)
        elif id == 'Author':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True,
                                              creators__given_name=name.split('/')[0],
                                              creators__family_name=name.split('/')[1])
            name = name.replace(r"/", " ")
        else:
            name = 'All Publication'
            id = 'general'
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True)

        availability = []
        non_availability = []
        all = []
        openABM_counter = 0
        sourceForge_counter = 0
        github_counter = 0
        netlogo_counter = 0
        cormas_counter = 0
        ccpforge_counter = 0
        bitbucket_counter = 0
        dataverse_counter = 0
        dropbox_counter = 0
        googlecode_counter = 0
        researchgate_counter = 0
        platform_dct = {}

        for pub in pubs:
            if pub.year_published is not None and pub.code_archive_url:
                if "https://www.openabm.org/" in pub.code_archive_url:
                    openABM_counter += 1
                    platform_dct.update({'openABM': openABM_counter})
                elif "https://sourceforge.net/" in pub.code_archive_url:
                    sourceForge_counter += 1
                    platform_dct.update({'sourceForge': sourceForge_counter})
                elif "https://github.com/" in pub.code_archive_url:
                    github_counter += 1
                    platform_dct.update({'openABM': openABM_counter})
                elif "http://modelingcommons.org/" in pub.code_archive_url \
                        or "https://ccl.northwestern.edu/netlogo/models/community" in pub.code_archive_url:
                    netlogo_counter += 1
                    platform_dct.update({'netlogo': netlogo_counter})
                elif "http://cormas.cirad.fr/" in pub.code_archive_url:
                    cormas_counter += 1
                    platform_dct.update({'openABM': openABM_counter})
                elif "https://ccpforge.cse.rl.ac.uk/" in pub.code_archive_url:
                    ccpforge_counter += 1
                    platform_dct.update({'ccpforge': ccpforge_counter})
                elif "https://bitbucket.org/" in pub.code_archive_url:
                    bitbucket_counter += 1
                    platform_dct.update({'bitbucket': bitbucket_counter})
                elif "https://dataverse.harvard.edu/" in pub.code_archive_url:
                    dataverse_counter += 1
                    platform_dct.update({'dataverse': dataverse_counter})
                elif "dropbox.com" in pub.code_archive_url:
                    dropbox_counter += 1
                    platform_dct.update({'dropbox': dropbox_counter})
                elif "https://code.google.com/" in pub.code_archive_url:
                    googlecode_counter += 1
                    platform_dct.update({'googlecode': googlecode_counter})
                elif "https://www.researchgate.net" in pub.code_archive_url:
                    researchgate_counter += 1
                    platform_dct.update({'researchgate': researchgate_counter})
                availability.append(pub.year_published)
            else:
                non_availability.append(pub.year_published)
            all.append(pub.year_published)

        response = []
        for year in set(all):
            if year is not None:
                present = availability.count(year) * 100 / len(all)
                absent = non_availability.count(year) * 100 / len(all)
                total = present + absent
                response.append({'id': id, 'name': name, 'date': year, 'Code Available': availability.count(year),
                                 'Code Not Available': non_availability.count(year),
                                 'Code Available Per': present * 100 / total,
                                 'Code Not Available Per': absent * 100 / total})

        return render_to_response("visualization/pubvsyear.html",
                                  {"obj_as_json": json.dumps(response), "code_platform": json.dumps(platform_dct)})


# Generate linked or associated list of publication for the requested Id
class PublicationListDetail(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)
    pagination_class = CatalogPagination

    def get(self, request, id=None, name=None, year=None):
        pubs = None
        if id == 'Journal':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, container__name=name,
                                              date_published_text__contains=year)
        elif id == 'Sponsor':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, sponsors__name=name,
                                              date_published_text__contains=year)
        elif id == 'Platform':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, platforms__name=name,
                                              date_published_text__contains=year)
        elif id == 'modeldoc':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True, model_documentation__name=name,
                                              date_published_text__contains=year)
        elif id == 'Author':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True,
                                              creators__given_name=name.split('/')[0],
                                              creators__family_name=name.split('/')[1],
                                              date_published_text__contains=year)
        elif id == 'general':
            pubs = Publication.objects.filter(status='REVIEWED', is_primary=True,
                                              date_published_text__contains=year)

        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
        serializer = PublicationListSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        return Response({'json': dumps(response)}, template_name="publication/list.html")
