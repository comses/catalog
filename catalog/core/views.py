import json
import logging
import time
from collections import Counter
from datetime import timedelta, datetime
from hashlib import sha1

from dateutil.parser import parse as datetime_parse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME, login as auth_login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Count, Q, F, Value as V, Max
from django.db.models.functions import Concat
from django.http import JsonResponse, HttpResponseRedirect, StreamingHttpResponse, QueryDict
from django.shortcuts import resolve_url, render, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import is_safe_url
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView, FormView, DetailView
from haystack.generic_views import SearchView
from haystack.query import SearchQuerySet
from rest_framework import status, renderers, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from citation.export_data import PublicationCSVExporter
from citation.graphviz.data import (generate_aggregated_code_archived_platform_data,
                                    generate_aggregated_distribution_data, generate_network_graph)
from citation.graphviz.globals import RelationClassifier, CacheNames
from citation.models import (Publication, Platform, Sponsor, ModelDocumentation, Tag, Container,
                             URLStatusLog, SuggestedMerge, Submitter, AuthorCorrespondenceLog)
from citation.ping_urls import categorize_url
from citation.serializers import (CatalogPagination, PublicationListSerializer,
                                  ContactFormSerializer, UserProfileSerializer,
                                  PublicationAggregationSerializer, AuthorAggregrationSerializer,
                                  SuggestMergeSerializer)
from .forms import CatalogAuthenticationForm, CatalogSearchForm
from .forms import PublicSearchForm, SuggestedPublicationForm, SubmitterForm, ContactAuthorsForm
from .search_indexes import (PublicationDoc, PublicationDocSearch, normalize_search_querydict,
                             get_search_index)
from .visualization import plots, data_access
from .visualization.data_access import visualization_cache

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


class ContactAuthorsView(LoginRequiredMixin, FormView):

    form_class = ContactAuthorsForm
    template_name = 'publication/contact-authors.html'
    success_url = reverse_lazy('core:dashboard')

    def send_email(self, publication_status, contact_email, number_of_publications, custom_invitation_text):
        publications = Publication.api.by_code_archive_url_status(publication_status,
                                                                  contact_email=contact_email,
                                                                  count=number_of_publications)
        acls = AuthorCorrespondenceLog.objects.create_from_publications(publications,
                                                                        custom_content=custom_invitation_text,
                                                                        curator=self.request.user)
        logger.debug("generated acls %s", acls)
        """
        for acl in acls:
            acl.send_email(self.request)
        """
        return acls

    def form_valid(self, form):
        email_filter = form.cleaned_data.get('email_filter')
        status = form.cleaned_data.get('status')
        number_of_publications = form.cleaned_data.get('number_of_publications')
        custom_invitation_text = form.cleaned_data.get('custom_invitation_text')
        ready_to_send = form.cleaned_data.get('ready_to_send')
        if ready_to_send:
            self.send_email(publication_status=status,
                            contact_email=email_filter,
                            number_of_publications=number_of_publications,
                            custom_invitation_text=custom_invitation_text)
            return super().form_valid(form)
        else:
            acl = AuthorCorrespondenceLog(status=status, content=custom_invitation_text)
            preview_email_text = acl.create_email_text(preview=True)
            return self.render_to_response(self.get_context_data(form=form, preview_email=preview_email_text))


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
        last_week_datetime = timezone.now() - timedelta(days=14)
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
            is_primary=True, status=Publication.Status.REVIEWED) \
            .annotate(n_code_archive_urls=models.Count('code_archive_urls')) \
            .filter(n_code_archive_urls__gt=0).count()
        context['incomplete'] = context['status'][Publication.Status.REVIEWED] - context['complete']

        context['unreviewed_publications_count'] = Publication.objects.filter(
            status=Publication.Status.UNREVIEWED, assigned_curator=self.request.user).count()
        context['recently_author_updated'] = Publication.objects.filter(
            status=Publication.Status.AUTHOR_UPDATED)
        recently_updated_publications = Publication.objects.exclude(
            status=Publication.Status.AUTHOR_UPDATED)
        recently_updated_list = recently_updated_publications.filter(
            date_modified__gte=last_week_datetime, is_primary=True).order_by('-date_modified')
        paginator = Paginator(recently_updated_list, number_of_publications)
        page = self.request.GET.get('page')
        recently_updated = paginator.get_page(page)
        context['recently_updated'] = recently_updated
        return context


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
        return Response({'json': json.dumps(serializer.data)}, template_name='contact_us.html')

    def post(self, request):
        serializer = ContactFormSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(LoginRequiredMixin, generics.GenericAPIView):
    """
    Retrieve or Update User Profile of current logged in User
    """
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer)

    def get(self, request):
        serializer = UserProfileSerializer(instance=request.user)
        return Response({'profile': json.dumps(serializer.data)}, template_name="accounts/profile.html")

    def post(self, request):
        serializer = UserProfileSerializer(instance=request.user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'profile': json.dumps(serializer.data)})
        return Response({'errors': json.dumps(serializer.errors)}, status=status.HTTP_400_BAD_REQUEST)


# Other Views
class AutocompleteView(LoginRequiredMixin, generics.GenericAPIView):
    renderer_classes = (renderers.JSONRenderer,)

    def get(self, request, format=None):
        query = request.GET.get('q', '').strip()
        sqs = SearchQuerySet().models(self.model_class)
        if query:
            sqs = sqs.autocomplete(name=query)
        data = [{'id': int(result.pk), 'name': result.name} for result in sqs]
        return Response(json.dumps(data))


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
        return Response({'relation_category': json.dumps(categories)}, template_name="visualization/visualization.html")


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
        return Response({'json': json.dumps(response)}, template_name="visualization/publication_relationlist.html")


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
        return Response({'json': json.dumps(response)}, template_name="visualization/publication_relationlist.html")


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
        return Response({'json': json.dumps(response)}, template_name="visualization/publication_relationlist.html")


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
        return Response({'json': json.dumps(response)}, template_name="visualization/publication_relationlist.html")


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
        return Response({'json': json.dumps(dct)},
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
        return Response({'json': json.dumps(response)}, template_name="publication/list.html")


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
        return Response({'result': json.dumps(res), 'description': json.dumps(message)},
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


def create_paginator_url(page: int, query_dict: QueryDict):
    url = '?page={}'.format(page)
    if query_dict:
        url += '&{}'.format(query_dict.urlencode())
    return url


def create_paginator(current_page: int, query_dict: QueryDict, total_hits, page_size=10):
    n_pages = -(-total_hits // page_size)
    paginator = {}
    if current_page - 1 > 0:
        paginator['previous'] = create_paginator_url(current_page - 1, query_dict)
    if current_page + 1 <= n_pages:
        paginator['next'] = create_paginator_url(current_page + 1, query_dict)
    paginator['range'] = [{'page': page, 'url': create_paginator_url(page, query_dict)} for page in
                          range(max(current_page - 5, 1), min(current_page + 5, n_pages + 1))]
    if current_page - 5 > 1:
        paginator['min'] = {'page': 1, 'url': create_paginator_url(1, query_dict)}
        paginator['min_exact'] = current_page - 5 == 2
    if current_page + 5 <= n_pages:
        paginator['max'] = {'page': n_pages, 'url': create_paginator_url(n_pages, query_dict)}
        paginator['max_exact'] = current_page + 5 == n_pages
    return paginator


def public_search_view(request):
    search, filters = normalize_search_querydict(request.GET)
    query_dict = request.GET.copy()
    current_page = int(query_dict.pop('page', [1])[0])

    from_qs = (current_page - 1) * 10
    to_qs = from_qs + 10
    publication_query = PublicationDocSearch().find(q=search, facet_filters=filters)[from_qs:to_qs].agg_by_count()
    publications = publication_query.execute(facet_filters=filters)
    facets = publication_query.cache

    total_hits = publications.hits.total
    paginator = create_paginator(current_page=current_page, query_dict=query_dict, total_hits=total_hits)
    form = PublicSearchForm(initial={'search': search})

    visualization_url = reverse('core:public-visualization')
    if search or filters:
        query_dict.pop('page', None)
        visualization_url += '?{}'.format(query_dict.urlencode())

    context = {'publications': publications, 'facets': facets, 'query': search, 'from': from_qs, 'to': to_qs,
               'form': form, 'paginator': paginator, 'current_page': current_page, 'total_hits': total_hits,
               'visualization_url': visualization_url, 'suggested_merge_url': reverse('core:public-merge')}
    context.update(PublicationDoc.get_breadcrumb_data())
    return render(request, 'public/search.html', context)


def public_visualization_view(request):
    content_type = request.GET.get('content_type', 'sponsors')
    search, filters = normalize_search_querydict(request.GET)
    publication_query = PublicationDocSearch().find(q=search, facet_filters=filters)[:0].agg_by_count()
    publication_pks = data_access.get_publication_pks_matching_search_criteria(query=search, facet_filters=filters)
    publication_query.execute(facet_filters=filters)
    facets = publication_query.cache
    arguments = request.GET.copy()
    arguments.pop('page', None)

    breadcrumb_trail = [
        {'link': reverse('core:public-home'), 'text': 'Home'},
        {'text': 'Visualization'},
    ]
    if search:
        breadcrumb_trail.append({'text': search})

    content_type_options = [
        {'value': 'authors', 'label': 'Authors'},
        {'value': 'container', 'label': 'Journals'},
        {'value': 'platforms', 'label': 'Platforms'},
        {'value': 'sponsors', 'label': 'Sponsors'},
        {'value': 'tags', 'label': 'Tags'}
    ]

    cache_key = '/visualization/{}'.format(request.GET.urlencode())
    plot_items = cache.get(cache_key)
    if not plot_items:
        cached_dfs = visualization_cache.get_or_create_many()
        publication_df = cached_dfs['publications']
        code_archive_urls_df = cached_dfs['code_archive_urls']
        author_df = cached_dfs['authors']
        platform_df = cached_dfs['platforms']
        sponsor_df = cached_dfs['sponsors']

        archival_timeseries_plots = plots.archival_timeseries_plot(publication_df, code_archive_urls_df,
                                                                   publication_pks)
        code_availability_timeseries_plots = plots.code_availability_timeseries_plot(publication_df, publication_pks)
        documentation_timeseries_plots = plots.documentation_standards_timeseries_plot(publication_df, publication_pks)

        plot_items = {
            'top_author_plot': {
                'data': plots.top_author_plot(author_df, publication_pks).to_plotly_json(),
                'data_id': 'top-author-plot-data',
                'id': 'top-author-plot'
            },
            'top_journal_plot': {
                'data': plots.top_journal_plot(publication_df, publication_pks).to_plotly_json(),
                'data_id': 'top-journal-plot-data',
                'id': 'top-journal-plot'
            },
            'top_platform_plot': {
                'data': plots.top_platform_plot(platform_df, publication_pks).to_plotly_json(),
                'data_id': 'top-platform-plot-data',
                'id': 'top-platform-plot'
            },
            'top_sponsor_plot': {
                'data': plots.top_sponsor_plot(sponsor_df, publication_pks).to_plotly_json(),
                'data_id': 'top-sponsor-plot-data',
                'id': 'top-sponsor-plot'
            },
            'archival_timeseries_count_plot': {
                'data': archival_timeseries_plots['count'].to_plotly_json(),
                'data_id': 'archival-timeseries-count-plot-data',
                'id': 'archival-timeseries-count-plot'
            },
            'archival_timeseries_percent_plot': {
                'data': archival_timeseries_plots['percent'].to_plotly_json(),
                'data_id': 'archival-timeseries-percent-plot-data',
                'id': 'archival-timeseries-percent-plot'
            },
            'code_availability_timeseries_count_plot': {
                'data': code_availability_timeseries_plots['count'].to_plotly_json(),
                'data_id': 'code-availability-timeseries-count-plot-data',
                'id': 'code-availability-timeseries-count-plot'
            },
            'code_availability_timeseries_percent_plot': {
                'data': code_availability_timeseries_plots['percent'].to_plotly_json(),
                'data_id': 'code-availability-timeseries-percent-plot-data',
                'id': 'code-availability-timeseries-percent-plot'
            },
            'documentation_timeseries_count_plot': {
                'data': documentation_timeseries_plots['count'].to_plotly_json(),
                'data_id': 'documentation-timeseries-count-plot-data',
                'id': 'documentation-timeseries-count-plot'
            },
            'documentation_timeseries_percent_plot': {
                'data': documentation_timeseries_plots['percent'].to_plotly_json(),
                'data_id': 'documentation-timeseries-percent-plot-data',
                'id': 'documentation-timeseries-percent-plot'
            }
        }
        cache.set(cache_key, plot_items, 300)

    return render(request, 'public/visualization.html',
                  context={
                      'plots': plot_items,
                      'breadcrumb_trail': breadcrumb_trail,
                      'content_type_options': content_type_options,
                      'n_matches': len(publication_pks),
                      'search': search, 'content_type': content_type,
                      'facets': facets})


def public_home(request):
    publication_df = visualization_cache.get_publications()
    plot = {
        'id': 'agent-based-modeling-tile',
        'data': plots.code_availability_timeseries_plot(publication_df)['count'].to_plotly_json(),
        'data_id': 'agent-based-modeling-tile-data'
    }

    search = request.GET.get('search')
    if search is not None:
        return redirect(PublicationDoc.get_public_list_url(search=search))
    return render(request, 'public/home.html',
                  context={'plot': plot,
                           'n_publications': Publication.api.primary().reviewed().count()})


def suggest_a_publication(request):
    def render_page(submitter_form, suggested_publication_form):
        return render(request, template_name='public/suggest_a_publication.html', context={
            'breadcrumb_trail': [
                {'link': reverse('core:public-home'), 'text': 'Home'},
                {'link': PublicationDoc.get_public_list_url(), 'text': 'Publications'},
                {'text': 'Suggest'}
            ],
            'submitter_form': submitter_form,
            'suggested_publication_form': suggested_publication_form
        })

    user = request.user if not request.user.is_anonymous else None

    if request.POST:
        submitter_form = SubmitterForm(request.POST, user=user)
        if not submitter_form.is_valid():
            suggested_publication_form = SuggestedPublicationForm(request.POST)
            return render_page(submitter_form=submitter_form, suggested_publication_form=suggested_publication_form)
        submitter = submitter_form.save()

        suggested_publication_form = SuggestedPublicationForm(request.POST, submitter=submitter)
        if not suggested_publication_form.is_valid():
            return render_page(submitter_form=submitter_form, suggested_publication_form=suggested_publication_form)

        suggested_publication = suggested_publication_form.save()
        messages.add_message(request, messages.SUCCESS, 'Successful publication addition request for {}'.format(
            suggested_publication.doi or suggested_publication.title))
        send_mail(subject='Suggested publication {}'.format(suggested_publication.short_name),
                  message='You suggested adding publication {} to the catalog'.format(suggested_publication.short_name),
                  from_email=settings.DEFAULT_FROM_EMAIL,
                  recipient_list=[submitter.get_email()])
        return HttpResponseRedirect(redirect_to=reverse('core:public-search'))
    else:
        return render_page(submitter_form=SubmitterForm(), suggested_publication_form=SuggestedPublicationForm())


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


def autocomplete(request):
    qd = request.GET
    try:
        model_name = qd['model_name']
    except KeyError:
        raise ValidationError(_('Missing model_name query param'), code='invalid')

    try:
        search = qd['search']
    except KeyError:
        raise ValidationError(_('Missing search query param'), code='invalid')

    content_type = ContentType.objects.get(model=model_name)
    model = content_type.model_class()
    model_doc = get_search_index(model)
    response = model_doc.search().query('match', name=search).execute()
    return JsonResponse({'matches': [h.to_dict(include_meta=False, skip_empty=False) for h in response.hits]})


class SuggestedMergeView(APIView):
    renderer_classes = (renderers.TemplateHTMLRenderer, renderers.JSONRenderer,)

    def get(self, request):
        return self.retrieve_create_suggested_merge_page(request)

    def post(self, request):
        user = request.user
        data = request.data
        return self.create_suggested_merge(data, user)

    def create_suggested_merge(self, data, user):
        serializer = SuggestMergeSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        content_type = ContentType.objects.get(model=validated_data['model_name'])
        creator, created = Submitter.get_or_create(user=user, email=data.get('email', ''))
        duplicates = [instance['id'] for instance in validated_data['instances']]
        new_content = validated_data['new_content']

        suggested_merge = SuggestedMerge(
            content_type=content_type,
            creator=creator,
            duplicates=duplicates,
            new_content=new_content)
        suggested_merge.save()
        return Response(data=status.HTTP_200_OK)

    def retrieve_create_suggested_merge_page(self, request):
        context = {
            'breadcrumb_trail': [
                {'link': reverse('core:public-home'), 'text': 'Home'},
                {'link': PublicationDoc.get_public_list_url(), 'text': 'Publications'},
                {'text': 'Suggest Duplicates'}
            ]
        }
        return render(request, 'public/suggestedmerge/create.html', context=context)


def suggested_merge_list_view(request):
    suggested_merge_list = SuggestedMerge.objects.order_by('-date_added')
    paginator = Paginator(suggested_merge_list, 20)

    page = request.GET.get('page')
    suggested_merges = paginator.get_page(page)
    suggested_merges.object_list = SuggestedMerge.annotate_names(list(suggested_merges.object_list))
    breadcrumb_trail = [
        {'link': reverse('core:public-home'), 'text': 'Home'},
        {'link': PublicationDoc.get_public_list_url(), 'text': 'Publications'},
        {'text': 'Duplicates'}
    ]
    return render(request, 'public/suggestedmerge/list.html',
                  {'suggested_merges': suggested_merges, 'breadcrumb_trail': breadcrumb_trail})
