import json
import logging
import time
from collections import Counter
from datetime import timedelta, datetime
from hashlib import sha1
from json import dumps
from pprint import pprint

import markdown
from bokeh.embed import server_document
from dateutil.parser import parse as datetime_parse
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME, login as auth_login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.core.cache import cache
from django.db import models
from django.db.models import Count, Q, F, Value as V, Max
from django.db.models.functions import Concat
from django.http import JsonResponse, HttpResponseRedirect, StreamingHttpResponse, QueryDict
from django.shortcuts import get_object_or_404, resolve_url, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import is_safe_url
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView, FormView, DetailView
from haystack.generic_views import SearchView
from haystack.query import SearchQuerySet
from rest_framework import status, renderers, generics
from rest_framework.response import Response

from catalog.core.forms import CONTENT_TYPE_SEARCH, PublicSearchForm, PublicExploreForm
from catalog.core.search_indexes import PublicationDoc, PublicationDocSearch
from citation.export_data import PublicationCSVExporter
from citation.graphviz.data import (generate_aggregated_code_archived_platform_data,
                                    generate_aggregated_distribution_data, generate_network_graph)
from citation.graphviz.globals import RelationClassifier, CacheNames
from citation.models import (Publication, InvitationEmail, Platform, Sponsor, ModelDocumentation, Tag, Container,
                             URLStatusLog)
from citation.ping_urls import categorize_url
from citation.serializers import (InvitationSerializer, CatalogPagination, PublicationListSerializer,
                                  UpdateModelUrlSerializer, ContactFormSerializer, UserProfileSerializer,
                                  PublicationAggregationSerializer, AuthorAggregrationSerializer)
from .forms import CatalogAuthenticationForm, CatalogSearchForm

logger = logging.getLogger(__name__)


def export_data(self):
    """A view that streams a large CSV file."""
    publication_data = PublicationCSVExporter()
    response = StreamingHttpResponse(publication_data.stream(), content_type="text/csv")
    response['Content-Disposition'] = 'attachment; filename="all_valid_data.csv"'
    return response


def queryset_gen(search_qs):
    for item in search_qs:
        yield item.pk


def visualization_query_filter(request):
    """
    It helps in generating query filter passed by the user in the request
    and stores the query filter in the session request to maintain user filters for later stage of visualization
    @:param: request: http request received
    @:return: filter_criteria dict generated from the query parameter pass in the request by the user
    """

    filter_criteria = {'is_primary': True, 'status': "REVIEWED"}
    query_param = request.query_params
    if query_param.get("sponsors"):
        filter_criteria.update(sponsors__name__in=query_param.getlist("sponsors"))
    if query_param.get("tags"):
        filter_criteria.update(tags__name__in=query_param.getlist("tags"))
    if query_param.get("start_date"):
        dt_obj = datetime.strptime(query_param.get("start_date"), '%Y')
        filter_criteria.update(date_published__gte=dt_obj.isoformat() + "Z")
    if query_param.get("end_date"):
        dt_obj = datetime.strptime(query_param.get("end_date"), '%Y')
        filter_criteria.update(date_published__lte=dt_obj.isoformat() + "Z")
    request.session['filter_criteria'] = filter_criteria
    return filter_criteria


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
            allowed_hosts=set(self.request.get_host()),
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
        if user.is_authenticated:
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
        categories = [{'Publications': reverse('core:pub-year-distribution'),
                       'Journals': reverse('core:publication-journal-relation'),
                       'Authors': reverse('core:publication-author-relation'),
                       'Sponsors': reverse('core:publication-sponsor-relation'),
                       'Platforms': reverse('core:publication-platform-relation'),
                       'Location Code Archived': reverse('core:code-archived-platform-relation'),
                       'Model Documentation': reverse('core:publication-model-documentation-relation'),
                       'Citation Network': reverse('core:network-relation')
                       }]
        request.session['filter_criteria'] = {}
        return Response({'relation_category': dumps(categories)}, template_name="visualization/visualization.html")


class AggregatedJournalRelationList(LoginRequiredMixin, generics.GenericAPIView):
    """
        Aggregates the publication data having same journal name
        attaching count values for the code availability for the total published paper
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        sqs = SearchQuerySet()
        sqs = sqs.filter(**visualization_query_filter(request))
        pub_pk = queryset_gen(sqs)
        pubs = Publication.api.aggregated_list(pk__in=pub_pk, identifier='container')
        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
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
        sqs = SearchQuerySet()
        sqs = sqs.filter(**visualization_query_filter(request))
        pub_pk = queryset_gen(sqs)
        pubs = Publication.api.aggregated_list(pk__in=pub_pk, identifier='sponsors')
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
        sqs = SearchQuerySet()
        sqs = sqs.filter(**visualization_query_filter(request)).models(Publication)
        pub_pk = queryset_gen(sqs)
        pubs = Publication.api.aggregated_list(pk__in=pub_pk, identifier='platforms')
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
        sqs = SearchQuerySet()
        sqs = sqs.filter(**visualization_query_filter(request)).models(Publication)
        pub_pk = queryset_gen(sqs)
        pubs = Publication.api.primary(pk__in=pub_pk). \
            annotate(given_name=F('creators__given_name'), family_name=F('creators__family_name')). \
            values('given_name', 'family_name'). \
            order_by('given_name', 'family_name'). \
            annotate(published_count=Count('given_name'),
                     code_availability_count=models.Sum(models.Case(
                         models.When(~Q(code_archive_url=''), then=1),
                         default=0,
                         output_field=models.IntegerField())),
                     name=Concat('given_name', V(' '), 'family_name')). \
            values('name', 'published_count', 'code_availability_count', 'given_name', 'family_name'). \
            order_by('-published_count')

        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
        serializer = AuthorAggregrationSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        response['relation'] = RelationClassifier.AUTHOR.value
        return Response({'json': dumps(response)}, template_name="visualization/publication_relationlist.html")


class ModelDocumentationPublicationRelation(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        self.request.session['filter_criteria'] = {}
        total = Publication.api.primary(status='REVIEWED').count()
        dct = {}
        for categories in ModelDocumentation.CATEGORIES:
            values = []
            for names in categories['modelDocumentationList']:
                values.append({
                    'name': names['name'],
                    'count': "{0:.2f}".format(
                        Publication.api.primary(status='REVIEWED',
                                                model_documentation__name=names['name']).count() * 100 / total
                    ),
                    'url': reverse('core:pub-year-distribution', args=['Modeldoc', names['name']])
                })
            dct[categories['category']] = values
        return Response({'json': dumps(dct)},
                        template_name="visualization/model_documentation_publication_relation.html")


class AggregatedCodeArchivedURLView(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):

        url_logs = URLStatusLog.objects.all().values('publication').order_by('publication', '-last_modified'). \
            annotate(last_modified=Max('last_modified')). \
            values_list('publication', 'type', 'publication__date_published_text').order_by('publication')
        all_records = Counter()
        years = []
        if url_logs:
            start_year = 1900
            end_year = 2100
            if request.query_params.get('start_date'):
                start_year = int(request.query_params.get('start_date'))
            if request.query_params.get('end_date'):
                end_year = int(request.query_params.get('end_date'))

            for pub, category, date in url_logs:
                try:
                    date_published = int(datetime_parse(str(date)).year)
                except:
                    date_published = None
                if date_published is not None and start_year <= date_published <= end_year:
                    years.append(date_published)
                    all_records[(date_published, category)] += 1
        else:
            sqs = SearchQuerySet()
            sqs = sqs.filter(**visualization_query_filter(request))
            filtered_pubs = queryset_gen(sqs)
            pubs = Publication.api.primary(pk__in=filtered_pubs)
            for pub in pubs:
                if pub.code_archive_url is not '' and pub.year_published is not None:
                    years.append(pub.year_published)
                    all_records[(pub.year_published, categorize_url(pub.code_archive_url))] += 1

        group = []
        data = [['x']]
        for name in URLStatusLog.PLATFORM_TYPES:
            group.append(name[0])
            data.append([name[0]])

        for year in sorted(set(years)):
            data[0].append(year)
            index = 1
            for name in URLStatusLog.PLATFORM_TYPES:
                data[index].append(all_records[(year, name[0])])
                index += 1

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

        filter_criteria = request.session.get("filter_criteria", {})
        if relation == RelationClassifier.JOURNAL.value:
            filter_criteria.update(container__name=name)
        elif relation == RelationClassifier.SPONSOR.value:
            filter_criteria.update(sponsors__name=name)
        elif relation == RelationClassifier.PLATFORM.value:
            filter_criteria.update(platforms__name=name)
        elif relation == RelationClassifier.MODELDOCUMENDTATION.value:
            filter_criteria.update(model_documentation__name=name)
        elif relation == RelationClassifier.AUTHOR.value and name:
            filter_criteria.update(authors__name__exact=name.replace("/", " "))
        else:
            name = "Publication"
            relation = RelationClassifier.GENERAL.value
            filter_criteria = visualization_query_filter(request)
            distribution_data = cache.get(CacheNames.DISTRIBUTION_DATA.value)
            platform = cache.get(CacheNames.CODE_ARCHIVED_PLATFORM.value)
            if 'date_published__gte' not in filter_criteria and 'date_published__lte' not in filter_criteria and \
                    distribution_data and platform:
                return Response(
                    {"aggregated_data": json.dumps(distribution_data), "code_platform": json.dumps([platform])},
                    template_name="visualization/pubvsyear.html")
        distribution_data = generate_aggregated_distribution_data(filter_criteria, relation, name)
        platform = generate_aggregated_code_archived_platform_data(filter_criteria)
        return Response({"aggregated_data": json.dumps(distribution_data), "code_platform": json.dumps([platform])},
                        template_name="visualization/pubvsyear.html")


class PublicationListDetail(LoginRequiredMixin, generics.GenericAPIView):
    """
        generates the list of publication that are either linked or associated with the requested publication
    """

    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request, relation=None, name=None, year=None):

        filter_criteria = request.session.get("filter_criteria", {})
        filter_criteria.update(date_published__gte=year + "-01-01T00:00:00Z",
                               date_published__lte=year + "-12-31T00:00:00Z")
        if relation == RelationClassifier.JOURNAL.value:
            filter_criteria.update(container__name=name)
        elif relation == RelationClassifier.SPONSOR.value:
            filter_criteria.update(sponsors__name=name)
        elif relation == RelationClassifier.PLATFORM.value:
            filter_criteria.update(platforms__name=name)
        elif relation == RelationClassifier.MODELDOCUMENDTATION.value:
            filter_criteria.update(model_documentation__name=name)
        elif relation == RelationClassifier.AUTHOR.value:
            filter_criteria.update(authors__name__exact=name.replace("/", " "))

        sqs = SearchQuerySet()
        sqs = sqs.filter(**filter_criteria).models(Publication)
        pubs_pk = queryset_gen(sqs)
        pubs = Publication.api.primary(pk__in=pubs_pk)
        paginator = CatalogPagination()
        result_page = paginator.paginate_queryset(pubs, request)
        serializer = PublicationListSerializer(result_page, many=True)
        response = paginator.get_paginated_response(serializer.data)
        return Response({'json': dumps(response)}, template_name="publication/list.html")


class NetworkRelationDetail(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request, pk=None):
        filter_criteria = request.session.get("filter_criteria", {})
        # fetching only filtered publication
        primary_publications = Publication.api.primary(**filter_criteria)

        # fetches links that satisfies the given filter
        links_candidates = Publication.api.primary(**filter_criteria,
                                                   citations__in=primary_publications).values_list('pk', 'citations')
        data = {}
        for source, target in links_candidates:
            target_list = data.get(str(source))
            if target_list and str(target) not in target_list:
                target_list.append(str(target))
                data[str(source)] = target_list
            else:
                data[str(source)] = [str(target)]

        res = self.generate_tree(pk, data)
        message = Publication.objects.get(pk=pk).get_message()
        return Response({'result': dumps(res), 'description': dumps(message)},
                        template_name="visualization/collapsible-tree.html")

    def generate_tree(self, root, data):
        nodes = data.get(str(root))
        if nodes is None:
            return {'name': root, 'children': []}

        children = []
        for node in nodes:
            if node != root:
                children.append(self.generate_tree(node, data))

        return {'name': root, 'children': children}


class NetworkRelation(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):

        filter_criteria = visualization_query_filter(request)
        network = cache.get(CacheNames.NETWORK_GRAPH_GROUP_BY_TAGS.value)
        filter_group = cache.get(CacheNames.NETWORK_GRAPH_TAGS_FILTER.value)

        if 'date_published__gte' in filter_criteria or 'date_published__lte' in filter_criteria or \
                not network and not filter_group:
            if 'tags__name__in' not in filter_criteria:
                filter_criteria.update(tags__name__in=Publication.api.get_top_records('tags__name', 5))
            network_data = generate_network_graph(filter_criteria)
            network = network_data.graph
            filter_group = network_data.filter_value

        return Response({"data": json.dumps(network), "group": json.dumps(filter_group)},
                        template_name="visualization/network-graph.html")


def create_paginator(current_page, total_hits, page_size=10):
    n_pages = -(-total_hits // page_size)
    paginator = {}
    if current_page - 1 > 0:
        paginator['previous'] = current_page - 1
    if current_page + 1 <= n_pages:
        paginator['next'] = current_page + 1
    paginator['range'] = range(max(current_page - 5, 1), min(current_page + 5, n_pages))
    paginator['max'] = n_pages
    return paginator


def normalize_search_querydict(qd: QueryDict):
    q = qd.get('q', '')
    field_names = PublicationDocSearch.get_filter_field_names()
    filters = {}
    for field_name in field_names:
        filters[field_name] = set(int(ident) for ident in qd.getlist(field_name))
    return q, filters


def public_search_view(request):
    q, filters = normalize_search_querydict(request.GET)
    current_page = int(request.GET.get('page', 1))

    from_qs = (current_page - 1) * 10
    to_qs = from_qs + 10
    publication_query = PublicationDocSearch().find(q=q, field_name_to_ids=filters)[from_qs:to_qs].agg_by_count()
    publications = publication_query.execute(filters=filters)
    facets = publication_query.cache

    total_hits = publications.hits.total
    paginator = create_paginator(current_page=current_page, total_hits=total_hits)
    form = PublicSearchForm(initial={'q': q})

    visualization_url = reverse('core:public-visualization')
    if q or filters:
        query_dict = request.GET.copy()
        query_dict.pop('page', None)
        visualization_url += '?{}'.format(query_dict.urlencode())

    context = {'publications': publications, 'facets': facets, 'query': q, 'from': from_qs, 'to': to_qs,
               'form': form, 'paginator': paginator, 'current_page': current_page, 'total_hits': total_hits,
               'visualization_url': visualization_url}
    context.update(PublicationDoc.get_breadcrumb_data())
    return render(request, 'public/search.html', context)


def public_visualization_view(request):
    base_url = 'http://localhost:5006/visualization'
    content_type = request.GET.get('content_type', 'sponsors')
    arguments = {'content_type': content_type}
    search = request.GET.get('search', '')
    if search:
        arguments['q'] = search
    breadcrumb_trail = [
        {'link': reverse('core:public-home'), 'text': 'Home'},
        {'text': 'Visualization'},
    ]
    if search:
        breadcrumb_trail.append({'text': search})

    content_type_options = [
        {'value': 'authors', 'label': 'Authors'},
        {'value': 'journals', 'label': 'Journals'},
        {'value': 'platforms', 'label': 'Platforms'},
        {'value': 'sponsors', 'label': 'Sponsors'},
        {'value': 'tags', 'label': 'Tags'}
    ]
    script = server_document(url=base_url, arguments=arguments)
    return render(request, 'public/visualization.html',
                  context={'script': script, 'breadcrumb_trail': breadcrumb_trail,
                           'content_type_options': content_type_options,
                           'search': search, 'content_type': content_type})


def public_explore_view(request):
    topic = request.GET.get('topic')
    content_type = request.GET.get('content_type', 'authors')
    order_by = request.GET.get('order_by', '-count')

    model = CONTENT_TYPE_SEARCH[content_type]
    matches = PublicationDoc().agg_by_model(q=topic, model=model)

    form = PublicExploreForm(initial={'content_type': content_type, 'order_by': order_by, 'topic': topic})
    return render(request, 'public/explore.html',
                  context={'content_type': content_type, 'form': form, 'matches': matches})


def public_home(request):
    q = request.GET.get('q', '')
    if q:
        return redirect(PublicationDoc.get_public_list_url(q=q))
    return render(request, 'public/home.html')


class PublicationDetailView(DetailView):
    pk_url_kwarg = 'pk'
    context_object_name = 'publication'
    model = Publication
    template_name = 'public/publication_detail.html'

    def get_queryset(self):
        return Publication.api.primary().filter(status='REVIEWED')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['breadcrumb_trail'] = [
            {'link': reverse('core:public-home'), 'text': 'Home'},
            {'link': PublicationDoc.get_public_list_url(), 'text': 'Publications'},
            {'text': self.object.title}]
        return context
