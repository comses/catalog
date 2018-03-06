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
from django.shortcuts import get_object_or_404, resolve_url
from django.urls import reverse
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
from citation.models import Publication, InvitationEmail, Platform, Sponsor, ModelDocumentation, Tag, Container, \
    URLStatusLog
from citation.serializers import (InvitationSerializer, CatalogPagination, PublicationListSerializer,
                                  UpdateModelUrlSerializer, ContactFormSerializer, UserProfileSerializer,
                                  PublicationAggregationSerializer, AuthorAggregrationSerializer)

from citation.graphviz.globals import RelationClassifier, CacheNames
from citation.graphviz.data import (generate_publication_code_platform_data,
                                                generate_network_graph_group_by_sponsors,
                                                generate_network_graph_group_by_tags)

from .forms import CatalogAuthenticationForm, CatalogSearchForm

logger = logging.getLogger(__name__)


def export_data(self):
    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="all_valid_data.csv"'
    writer = csv.writer(response)
    create_csv(writer)
    return response


def visualization_query_filter(request):
    """
    It helps in generating query filter passed by the user in the request
    and stores the query filter in the session request to maintain user filters for later stage of visualization
    @:param: request: http request received
    @:return: criteria dict generated from the query parameter pass in the request by the user
    """

    criteria = {}
    query_param = request.query_params
    if query_param.get("sponsors"):
        criteria.update(sponsors__name__in=query_param.getlist("sponsors"))
    if query_param.get("tags"):
        criteria.update(tags__name__in=query_param.getlist("tags"))
    if query_param.get("start_date"):
        criteria.update(query_param.get(publication_start_date="start_date"))
    if query_param.get("end_date"):
        criteria.update(query_param.get(publication_end_date="end_date"))
    request.session['criteria'] = criteria
    return criteria


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
        list = [CacheNames.CONTRIBUTION_DATA.value + str(pub.id) for pub in recently_updated]
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


class VisualizationSearchView(LoginRequiredMixin, generics.GenericAPIView):
    """
        Search View for Visualization
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        RELATION = [{'Publications': reverse('core:pub-year-distribution'),
                     'Journals': reverse('core:publication-journal-relation'),
                     'Authors': reverse('core:publication-author-relation'),
                     'Sponsors': reverse('core:publication-sponsor-relation'),
                     'Platforms': reverse('core:publication-platform-relation'),
                     'Code Archived Platform': reverse('core:code-archived-platform-relation'),
                     'Model platforms and Programming Languages': reverse(
                         'core:publication-model-documentation-relation'),
                     'Network Relation': reverse('core:network-relation')}]
        request.session['criteria'] = {}
        return Response({'relation_category': dumps(RELATION)}, template_name="visualization/visualization.html")


class AggregatedJournalRelationList(LoginRequiredMixin, generics.GenericAPIView):
    """
        Aggregates the publication data having same journal name
        attaching count values for the code availability for the total published paper
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        queryset = Publication.api.aggregated_list(identifier='container', **visualization_query_filter(request))
        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(queryset, request)
        serializer = PublicationAggregationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        response['relation'] = RelationClassifier.JOURNAL.value
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


class AggregatedSponsorRelationList(LoginRequiredMixin, generics.GenericAPIView):
    """
        Aggregates the publication data having same Sponsors name
        attaching count values for the code availability for the total published paper
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        pubs = Publication.api.aggregated_list(identifier='sponsors', **visualization_query_filter(request))
        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
        serializer = PublicationAggregationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        response['relation'] = RelationClassifier.SPONSOR.value
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


class AggregatedPlatformRelationList(LoginRequiredMixin, generics.GenericAPIView):
    """
        Aggregates the publication data having same platform name
        attaching count values for the code availability for the total published paper
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        pubs = Publication.api.aggregated_list(identifier='platforms', **visualization_query_filter(request))
        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
        serializer = PublicationAggregationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        response['relation'] = RelationClassifier.PLATFORM.value
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


class AggregatedAuthorRelationList(LoginRequiredMixin, generics.GenericAPIView):
    """
        Aggregates the publication data having same author name
        attaching count values for the code availability for the total published paper
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        pubs = Publication.api.primary(status='REVIEWED', **visualization_query_filter(request)). \
            annotate(given_name=F('creators__given_name'), family_name=F('creators__family_name')).values(
            'given_name',
            'family_name').order_by(
            'given_name', 'family_name').annotate(published_count=Count('given_name'),
                                                  code_availability_count=models.Sum(models.Case(
                                                      models.When(~Q(code_archive_url=''), then=1),
                                                      default=0,
                                                      output_field=models.IntegerField())),
                                                  name=Concat('given_name', V(' '),
                                                              'family_name'),
                                                  ).values(
            'name', 'published_count', 'code_availability_count', 'given_name', 'family_name').order_by(
            '-published_count')

        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
        serializer = AuthorAggregrationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        response['relation'] = RelationClassifier.AUTHOR.value
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


class ModelDocumentationPublicationRelation(LoginRequiredMixin, TemplateView):
    template_name = 'visualization/model_documentation_publication_relation.html'

    def get_context_data(self, **kwargs):
        context = super(ModelDocumentationPublicationRelation, self).get_context_data(**kwargs)
        self.request.session['criteria'] = {}
        md = ModelDocumentation.objects.all().values_list('name')
        total = Publication.api.primary(status='REVIEWED').count()
        value = []
        for name in list(md):
            if name[0] is not None:
                value.append({'name': name[0], 'count': "{0:.2f}".format(
                    Publication.api.primary(status='REVIEWED',
                                            model_documentation__name=name[
                                                0]).count() * 100 / total)})
        context['value'] = value
        context['relation'] = RelationClassifier.MODELDOCUMENDTATION.value
        return context


class AggregatedCodeArchiverURLView(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        pubs = Publication.api.primary(status='REVIEWED')
        url_logs = URLStatusLog.objects.filter(publication__in=pubs)
        all_records = []
        years = []
        for pub in url_logs:
            if pub.publication.year_published is not None:
                years.append(pub.publication.year_published)
                all_records.append((pub.publication.year_published, pub.type))

        group = []
        data = [['x']]
        for name in URLStatusLog.PLATFORM_TYPES:
            group.append(name[0])
            data.append([name[0]])

        for year in sorted(set(years)):
            data[0].append(year)
            counter = 1
            for name in URLStatusLog.PLATFORM_TYPES:
                aggregate_count = all_records.count((year, name[0]))
                if aggregate_count:
                    data[counter].append(aggregate_count)
                else:
                    data[counter].append(0)
                counter += 1

        return Response({"aggregated_data": json.dumps(data), "group": json.dumps(group)},
                        template_name="visualization/code_archived_url_staged_bar.html")


class AggregatedStagedVisualizationView(LoginRequiredMixin, generics.GenericAPIView):
    """
        Generates the aggregated staged distribution of code availability and non-availability against year
        for the requested relation : Journal, Sponsor, Platform, Model Doc, Author

        @default: every reviewed primary publication will be selected
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request, relation=None, name=None):

        criteria = request.session.get("criteria", {})
        if relation == RelationClassifier.JOURNAL.value:
            criteria.update(container__name=name)
        elif relation == RelationClassifier.SPONSOR.value:
            criteria.update(sponsors__name=name)
        elif relation == RelationClassifier.PLATFORM.value:
            criteria.update(platforms__name=name)
        elif relation == RelationClassifier.MODELDOCUMENDTATION.value:
            criteria.update(model_documentation__name=name)
        elif relation == RelationClassifier.AUTHOR.value and name:
            try:
                (given_name, family_name) = name.split('/')
                criteria.update(creators__given_name=given_name, creators__family_name=family_name)
            except ValueError:
                criteria.update(creators__given_name=name)
        else:
            name = "Publication"
            relation = RelationClassifier.GENERAL.value
            distribution_data = cache.get(CacheNames.DISTRIBUTION_DATA.value)
            platform = cache.get(CacheNames.CODE_ARCHIVED_PLATFORM.value)
            if distribution_data and platform:
                return Response(
                    {"aggregated_data": json.dumps(distribution_data), "code_platform": json.dumps(platform)},
                    template_name="visualization/pubvsyear.html")
        aggregate_data = generate_publication_code_platform_data(criteria, relation, name)
        distribution_data = aggregate_data.data
        platform = aggregate_data.code_archived_platform

        return Response({"aggregated_data": json.dumps(distribution_data), "code_platform": json.dumps(platform)},
                        template_name="visualization/pubvsyear.html")


class PublicationListDetail(LoginRequiredMixin, generics.GenericAPIView):
    """
        generates the list of publication that are either linked or associated with the requested publication
    """

    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request, relation=None, name=None, year=None):
        pubs = []

        # FIXME
        # there are different formats in the date_published text like AUG 26 2000, Fall 2000.
        # so below query will parse both result as its checking for contains string
        # so there will be mismatch is number of results present

        if relation == RelationClassifier.JOURNAL.value:
            pubs = Publication.api.primary(status='REVIEWED', container__name=name,
                                           date_published_text__contains=year, **request.session.get("criteria", {}))
        elif relation == RelationClassifier.SPONSOR.value:
            pubs = Publication.api.primary(status='REVIEWED', sponsors__name=name,
                                           date_published_text__contains=year, **request.session.get("criteria", {}))
        elif relation == RelationClassifier.PLATFORM.value:
            pubs = Publication.api.primary(status='REVIEWED', platforms__name=name,
                                           date_published_text__contains=year, **request.session.get("criteria", {}))
        elif relation == RelationClassifier.MODELDOCUMENDTATION.value:
            pubs = Publication.api.primary(status='REVIEWED', model_documentation__name=name,
                                           date_published_text__contains=year, **request.session.get("criteria", {}))
        elif relation == RelationClassifier.AUTHOR.value:
            pubs = Publication.api.primary(status='REVIEWED',
                                           creators__given_name=name.split('/')[0],
                                           creators__family_name=name.split('/')[1],
                                           date_published_text__contains=year, **request.session.get("criteria", {}))
        elif relation == RelationClassifier.GENERAL.value:
            pubs = Publication.api.primary(status='REVIEWED',
                                           date_published_text__contains=year, **request.session.get("criteria", {}))

        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
        serializer = PublicationListSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        return Response({'json': dumps(response)}, template_name="publication/list.html")


class NetworkRelationDetail(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request, pk=None):
        filter = request.session.get("criteria", {})
        # fetching only filtered publication
        primary_publications = Publication.api.primary(status='REVIEWED', **filter)

        # fetches links that satisfies the given filter
        links_candidates = Publication.api.primary(status='REVIEWED', **filter,
                                                   citations__in=primary_publications).values_list('pk', 'citations')
        data = {}
        for pub in links_candidates:
            id = data.get(str(pub[0]))
            if id and str(pub[1]) not in id:
                id.append(str(pub[1]))
                data[str(pub[0])] = id
            else:
                data[str(pub[0])] = [str(pub[1])]

        res = self.generate_tree(pk, data)
        message = Publication.objects.get(pk=pk).get_message()
        return Response({'result': dumps(res), 'description': dumps(message)}, template_name="visualization/collapsible-tree.html")

    def generate_tree(self, root, data):
        ids = data.get(str(root))
        if ids is None:
            return {'name': root, 'children': []}
        children = []

        for id in ids:
            if id != root:
                children.append(self.generate_tree(id, data))

        return {'name': root, 'children': children}


class NetworkRelation(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        group_by = request.GET.get('group_by')
        filter_criteria = visualization_query_filter(request)
        network = {},
        filter_group = {}
        if group_by == 'tags':
            network = cache.get(CacheNames.NETWORK_GRAPH_GROUP_BY_TAGS.value)
            filter_group = cache.get(CacheNames.NETWORK_GRAPH_TAGS_FILTER.value)
        elif group_by == 'sponsors':
            network = cache.get(CacheNames.NETWORK_GRAPH_GROUP_BY_SPONSORS.value)
            filter_group = cache.get(CacheNames.NETWORK_GRAPH_SPONSOS_FILTER.value)

        if network and filter_group:
            return Response({"data": json.dumps(network),
                             "group": json.dumps(filter_group)},
                            template_name="visualization/network-graph.html")
        else:
            if group_by == 'sponsors':
                network_data = generate_network_graph_group_by_sponsors(filter_criteria)
                network = network_data.graph
                filter_group = network_data.filter_value
            elif group_by == 'tags':
                network_data = generate_network_graph_group_by_tags(filter_criteria)
                network = network_data.graph
                filter_group = network_data.filter_value

            return Response({"data": json.dumps(network), "group": json.dumps(list(filter_group))},
                            template_name="visualization/network-graph.html")
