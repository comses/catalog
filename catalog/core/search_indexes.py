import logging
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import QueryDict
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from elasticsearch_dsl import analyzer, tokenizer
from haystack import indexes
from typing import Dict, List

from citation.models import Publication, Platform, Sponsor, Tag, ModelDocumentation, Container, Author

logger = logging.getLogger(__name__)


##########################################
#  Publication query seach/filter index  #
##########################################

class PublicationIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    title = indexes.CharField(model_attr='title')
    date_published = indexes.DateField(model_attr='date_published', null=True)
    last_modified = indexes.DateTimeField(model_attr='date_modified')
    contact_email = indexes.BooleanField(model_attr='contact_email')
    status = indexes.CharField(model_attr='status', faceted=True)
    container = indexes.CharField(model_attr='container__name', null=True)
    tags = indexes.EdgeNgramField(model_attr='tags__name', null=True)
    sponsors = indexes.CharField(model_attr='sponsors__name', null=True)
    platforms = indexes.CharField(model_attr='platforms__name', null=True)
    model_documentation = indexes.CharField(model_attr='model_documentation__name', null=True)
    authors = indexes.CharField(model_attr='creators__name', null=True)
    assigned_curator = indexes.CharField(model_attr='assigned_curator', null=True)
    flagged = indexes.BooleanField(model_attr='flagged')
    is_primary = indexes.BooleanField(model_attr='is_primary')
    is_archived = indexes.BooleanField(model_attr='is_archived')
    contributor_data = indexes.MultiValueField(model_attr='contributor_data', null=True)

    def prepare_last_modified(self, obj):
        last_modified = self.prepared_data.get('last_modified')
        if last_modified:
            return last_modified.strftime('%Y-%m-%dT%H:%M:%SZ')
        return ''

    def prepare_contributor_data(self, obj):
        contributor_data = self.prepared_data.get('contributor_data')
        if contributor_data:
            return '{0} ({1})%'.format(contributor_data[0]['creator'], contributor_data[0]['contribution'])
        return ''

    def get_model(self):
        return Publication

    def index_queryset(self, using=None):
        return Publication.objects.filter(is_primary=True)


##########################################
#       AutoComplete Index Fields        #
##########################################

class NameAutocompleteIndex(indexes.SearchIndex):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    class Meta:
        abstract = True


class PlatformIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return Platform


class SponsorIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return Sponsor


class TagIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return Tag


class ModelDocumentationIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return ModelDocumentation


##########################################
#           Bulk Index Updates           #
##########################################

def bulk_index_update():
    PublicationIndex().update()
    PlatformIndex().update()
    SponsorIndex().update()
    TagIndex().update()
    ModelDocumentationIndex().update()


##########################################
#           Public Indices               #
##########################################

from datetime import datetime, timezone

from elasticsearch import NotFoundError
from elasticsearch.helpers import bulk
from elasticsearch_dsl import Document, InnerDoc, connections, aggs, query
import elasticsearch_dsl as edsl

from django.conf import settings

ALL_DATA_FIELD = 'all_data'


_ES_CLIENT = None


def get_es_client():
    """
    Lazily build (and cache) the Elasticsearch 8 client from
    ``settings.ELASTICSEARCH`` and register it as the elasticsearch-dsl
    ``default`` connection.

    No Elasticsearch configuration happens at Django startup: the client
    is only constructed on first use, and ``connections.configure`` merely
    stores options (no network I/O).
    """
    global _ES_CLIENT
    if _ES_CLIENT is None:
        connections.configure(default=dict(settings.ELASTICSEARCH))
        _ES_CLIENT = connections.get_connection()
    return _ES_CLIENT


##########################################
#     Generation-based index rebuilds    #
##########################################
#
# Reads always go through stable aliases (the ``Index.name`` of each doc
# class: publication, author, container, platform, sponsor, tag).
# Rebuilds write to a fresh generation index per alias
# (``<alias>-<utc-stamp>``) and validate each one; only after *every*
# generation validates are the stable aliases moved onto the new
# generations in one atomic multi-alias ``update_aliases`` call. The
# previous generation of each alias is retained for rollback; anything
# older is pruned.

class SearchRebuildError(Exception):
    """Raised when a generation index cannot be built or validated."""


def _utc_generation_timestamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def generation_index_name(alias):
    return '{0}-{1}'.format(alias, _utc_generation_timestamp())


def _alias_target(client, alias):
    """Return the physical index currently serving ``alias`` (or None)."""
    try:
        return next(iter(client.indices.get_alias(name=alias)))
    except NotFoundError:
        return None


def _index_doc_count(client, index_name):
    # The ES8 client returns a mapping-backed response object
    # (``elastic_transport.ObjectApiResponse``) whose body is a plain
    # dict, so the count must be read with mapping access. Attribute
    # access on that object falls through to the raw body dict and
    # raises ``AttributeError`` for a ``count`` key.
    response = client.count(index=index_name)
    return response.get('count')


def _delete_index_quietly(client, index_name):
    # The ES8 client takes ignore_status as a request option, not a kwarg.
    client.options(ignore_status=[400, 404]).indices.delete(index=index_name)


def _create_generation_index(client, doc_class, index_name):
    # ``clone()`` carries the doc class's mappings, analyzers and index
    # settings (e.g. number_of_shards) onto the generation name.
    gen_index = doc_class._index.clone(name=index_name)
    client.indices.create(index=index_name, body=gen_index.to_dict())


def _prune_old_generations(client, alias, keep):
    """Delete generation indices of ``alias`` that are not in ``keep``."""
    keep = {name for name in keep if name}
    try:
        existing = client.indices.get(index='{0}-*'.format(alias))
    except NotFoundError:
        return
    for name in existing:
        if name not in keep:
            _delete_index_quietly(client, name)


def _force_actions_to_generation_index(documents):
    """
    Return bulk actions with any per-action ``_index`` removed.

    Actions built with ``Document.to_dict(include_meta=True)`` (see the
    ``from_instance`` classmethods) stamp the stable read *alias* onto
    ``_index``. If that survives into the bulk request,
    ``elasticsearch.helpers.bulk`` honors the per-action index and the
    documents land in whatever the alias currently points at (the
    *previous* generation) instead of the new one. Stripping the key
    forces every action onto the ``index=`` argument of the bulk call.
    """
    forced = []
    for action in documents:
        action = dict(action)
        action.pop('_index', None)
        forced.append(action)
    return forced


def build_document_generation(client, doc_class, documents, expected_count):
    """
    Build and validate one fresh generation index for ``doc_class``.

    Creates ``<alias>-<utc-stamp>`` carrying the doc class mappings
    (including the ``InnerDoc`` definitions for the embedded
    Object/Nested fields) and the single-node index settings, forces
    every bulk action onto that physical generation index, refreshes
    it, and validates the document count against the ES8 count
    response.

    ``documents`` is an iterable of ready-to-bulk action dicts. Any
    bulk error (``elasticsearch.helpers.bulk`` raises ``BulkIndexError``
    on partial failure by default) or a document-count mismatch deletes
    the new generation and re-raises. Stable aliases are never touched
    here: swapping is done by ``swap_generation_aliases``.

    Returns the new generation index name.
    """
    alias = doc_class._index._name
    index_name = generation_index_name(alias)
    try:
        _create_generation_index(client, doc_class, index_name)
        bulk(client=client,
             actions=_force_actions_to_generation_index(documents),
             index=index_name)
        client.indices.refresh(index=index_name)
        actual_count = _index_doc_count(client, index_name)
        if actual_count != expected_count:
            raise SearchRebuildError(
                'index {0} validation failed: expected {1} documents, found {2}'.format(
                    index_name, expected_count, actual_count))
    except Exception:
        _delete_index_quietly(client, index_name)
        raise
    return index_name


def swap_generation_aliases(client, alias_to_index):
    """
    Point every stable read alias at its new generation index.

    A single atomic ``update_aliases`` call removes each alias from its
    current target (if any) and adds it to the new generation, so
    readers see either the old set of generations or the new set, never
    a mix. After the swap, generation indices older than the retained
    previous generation are pruned per alias (pruning failures are
    logged and do not roll back the completed swap).
    """
    actions = []
    previous = {}
    for alias, index_name in alias_to_index.items():
        current = _alias_target(client, alias)
        if current is not None:
            previous[alias] = current
            actions.append({'remove': {'index': current, 'alias': alias}})
        actions.append({'add': {'index': index_name, 'alias': alias}})
    client.indices.update_aliases(actions=actions)
    for alias in alias_to_index:
        try:
            _prune_old_generations(client, alias,
                                   keep=(alias_to_index[alias], previous.get(alias)))
        except Exception:
            logger.exception('failed to prune old generations for alias %s', alias)
    return alias_to_index


def rebuild_document_indices(client, builds):
    """
    Rebuild every read alias using fresh generation indices.

    ``builds`` is an iterable of ``(doc_class, documents, expected_count)``
    triples. Every generation is built and validated *before* any alias
    moves: if any build or validation fails, no alias is touched and
    only the new generations that were created are deleted. Only once
    all generations validate are the stable aliases swapped onto them
    in one atomic multi-alias operation; a failed swap likewise leaves
    the live aliases untouched and cleans up only the new generations.
    Previous generations are always retained for rollback.

    Returns a mapping of alias -> new generation index name.
    """
    built = {}
    swapped = False
    try:
        for doc_class, documents, expected_count in builds:
            built[doc_class._index._name] = build_document_generation(
                client, doc_class, documents, expected_count)
        swap_generation_aliases(client, built)
        swapped = True
    except Exception:
        if not swapped:
            for index_name in built.values():
                _delete_index_quietly(client, index_name)
        raise
    return built


class AuthorInnerDoc(InnerDoc):
    id = edsl.Integer(required=True)
    orcid = edsl.Keyword()
    researcherid = edsl.Keyword()
    email = edsl.Keyword()
    name = edsl.Text(copy_to=ALL_DATA_FIELD)


class CodeArchiveUrlInnerDoc(InnerDoc):
    id = edsl.Integer(required=True)
    url = edsl.Text()
    status = edsl.Keyword()


class ContainerInnerDoc(InnerDoc):
    id = edsl.Integer(required=True)
    name = edsl.Text(copy_to=ALL_DATA_FIELD)
    issn = edsl.Keyword()


class RelatedInnerDoc(InnerDoc):
    id = edsl.Integer(required=True)
    name = edsl.Text(copy_to=ALL_DATA_FIELD)


def normalize_search_querydict(qd: QueryDict):
    search = qd.get('search', '')
    field_names_lookup = PublicationDocSearch.get_filter_field_names()
    filters = {}
    for field_name in field_names_lookup:
        filters[field_name] = set(int(ident) for ident in qd.getlist(field_name))
    return search, filters


class TopHits:
    def __init__(self, iterable, hits):
        self.iterable = iterable
        self.hits = hits

    def __iter__(self):
        return iter(self.iterable)


class AbstractAgg:
    def __init__(self, name):
        self.name = name

    def extract(self, response, ids):
        data = self.extract_count(response, ids)
        return {self.name: {'count': data}}


# Use top hits elasticsearch aggregator to avoid hitting DB
class UnnestedAgg(AbstractAgg):
    @property
    def _terms_bucket_name(self):
        return 'top_{}_count'.format(self.name)

    _top_hit_bucket_name = 'top_hit'

    def count(self, search):
        search.aggs.bucket(self._terms_bucket_name,
                           aggs.Terms(field='{}.id'.format(self.name))) \
            .bucket(self._top_hit_bucket_name,
                    aggs.TopHits(size=1, _source={'includes': [self.name]}))

    def extract_count(self, response, ids):
        term_buckets = response.aggs[self._terms_bucket_name].buckets
        results = []
        for bucket in term_buckets:
            result = {'publication_count': bucket.doc_count}
            result.update(bucket[self._top_hit_bucket_name].hits.hits[0]['_source'][self.name])
            result['checked'] = result['id'] in ids
            results.append(result)
        return results


class NestedAgg(AbstractAgg):
    @property
    def _top_bucket_name(self):
        return '{}'.format(self.name)

    _terms_bucket_name = 'top_count'
    _top_hit_bucket_name = 'top_hit'

    def count(self, search):
        search.aggs.bucket(self._top_bucket_name, aggs.Nested(path=self.name)) \
            .bucket(self._terms_bucket_name,
                    aggs.Terms(field='{}.id'.format(self.name))) \
            .bucket(self._top_hit_bucket_name, aggs.TopHits(size=1, _source={'includes': [self.name]}))

    def extract_count(self, response, ids):
        term_buckets = response.aggs[self._top_bucket_name][self._terms_bucket_name].buckets
        results = []
        for bucket in term_buckets:
            result = {'publication_count': bucket.doc_count}
            result.update(bucket[self._top_hit_bucket_name].hits.hits[0]['_source'])
            result['checked'] = result['id'] in ids
            results.append(result)
        return results


class FilterQuery:
    def __init__(self, name):
        self.field = '{}.id'.format(name)

    def by_ids(self, ids):
        return query.Q('terms', **{self.field: list(ids)})


class NestedFilterQuery:
    def __init__(self, name):
        self.path = name
        self.field = '{}.id'.format(name)

    def by_ids(self, ids):
        return query.Nested(path=self.path, query=query.Q('terms', **{self.field: list(ids)}))


class PublicationDocSearch:
    AUTHOR_FIELD_NAME = 'authors'
    CONTAINER_FIELD_NAME = 'container'
    PLATFORM_FIELD_NAME = 'platforms'
    SPONSOR_FIELD_NAME = 'sponsors'
    TAG_FIELD_NAME = 'tags'

    aggs = {
        AUTHOR_FIELD_NAME: NestedAgg(AUTHOR_FIELD_NAME),
        CONTAINER_FIELD_NAME: UnnestedAgg(CONTAINER_FIELD_NAME),
        PLATFORM_FIELD_NAME: NestedAgg(PLATFORM_FIELD_NAME),
        SPONSOR_FIELD_NAME: NestedAgg(SPONSOR_FIELD_NAME),
        TAG_FIELD_NAME: NestedAgg(TAG_FIELD_NAME)
    }

    filters = {
        AUTHOR_FIELD_NAME: NestedFilterQuery(AUTHOR_FIELD_NAME),
        CONTAINER_FIELD_NAME: FilterQuery(CONTAINER_FIELD_NAME),
        PLATFORM_FIELD_NAME: NestedFilterQuery(PLATFORM_FIELD_NAME),
        SPONSOR_FIELD_NAME: NestedFilterQuery(SPONSOR_FIELD_NAME),
        TAG_FIELD_NAME: NestedFilterQuery(TAG_FIELD_NAME)
    }

    def __init__(self, search=None, cache=None):
        self.search = PublicationDoc.search() if search is None else search
        self.cache = {} if cache is None else cache

    def __getitem__(self, val):
        return PublicationDocSearch(self.search[val])

    def _full_text(self, q):
        return query.QueryString(**{'query': q, 'default_field': ALL_DATA_FIELD})

    def _filter(self, facet_filters: Dict[str, List[int]]):
        queries = []
        for field_name in facet_filters:
            ids = facet_filters[field_name]
            if ids:
                queries.append(self.filters[field_name].by_ids(ids))
        return queries

    def find(self, q, facet_filters):
        logger.info('filters: %s', facet_filters)
        queries = self._filter(facet_filters)
        full_text = self._full_text(q) if q else query.MatchAll()
        if queries:
            return PublicationDocSearch(self.search.query(
                query.Bool(should=queries, must=[full_text], minimum_should_match=1)))
        elif q:
            return PublicationDocSearch(self.search.query(full_text))
        else:
            return PublicationDocSearch(self.search.sort('-incomplete_date_published'))

    def source(self, fields=None, **kwargs):
        return PublicationDocSearch(self.search.source(fields=fields, **kwargs))

    def scan(self):
        # ensure the dsl default connection is configured (no network I/O)
        get_es_client()
        return self.search.scan()

    def agg_by_count(self):
        s = self.search._clone()
        for agg in self.aggs.values():
            agg.count(s)
        return PublicationDocSearch(s)

    @classmethod
    def get_filter_field_names(cls):
        return [cls.AUTHOR_FIELD_NAME, cls.CONTAINER_FIELD_NAME,
                cls.PLATFORM_FIELD_NAME, cls.SPONSOR_FIELD_NAME, cls.TAG_FIELD_NAME]

    def execute(self, facet_filters):
        # ensure the dsl default connection is configured (no network I/O)
        get_es_client()
        response = self.search.execute()
        for name in self.aggs:
            ids = facet_filters.get(name, [])
            agg = self.aggs[name]
            self.cache.update(agg.extract(response, ids))
        return response


class PublicationDoc(Document):
    all_data = edsl.Text()
    id = edsl.Integer()
    title = edsl.Text(copy_to=ALL_DATA_FIELD)
    incomplete_date_published = edsl.Keyword()
    last_modified = edsl.Date()
    code_archive_urls = edsl.Nested(CodeArchiveUrlInnerDoc)
    doi = edsl.Keyword()
    contact_email = edsl.Keyword(copy_to=ALL_DATA_FIELD)
    container = edsl.Object(ContainerInnerDoc)
    tags = edsl.Nested(RelatedInnerDoc)
    sponsors = edsl.Nested(RelatedInnerDoc)
    platforms = edsl.Nested(RelatedInnerDoc)
    model_documentation = edsl.Keyword()
    authors = edsl.Nested(AuthorInnerDoc)

    @classmethod
    def from_instance(cls, publication):
        container = publication.container
        doc = cls(meta={'id': publication.id},
                  id=publication.id,
                  title=publication.title,
                  incomplete_date_published=publication.incomplete_date_published,
                  last_modified=publication.date_modified,
                  code_archive_urls=[CodeArchiveUrlInnerDoc(id=c.id, url=c.url, status=c.status)
                                     for c in publication.code_archive_urls.all()],
                  contact_email=publication.contact_email,
                  container=ContainerInnerDoc(id=container.id, name=container.name, issn=container.issn),
                  doi=publication.doi,
                  tags=[RelatedInnerDoc(id=t.id, name=t.name) for t in publication.tags.all()],
                  sponsors=[RelatedInnerDoc(id=s.id, name=s.name) for s in publication.sponsors.all()],
                  platforms=[RelatedInnerDoc(id=p.id, name=p.name) for p in publication.platforms.all()],
                  model_documentation=[md.name for md in publication.model_documentation.all()],
                  authors=[
                      AuthorInnerDoc(id=a.id, name=a.name, orcid=a.orcid, researcherid=a.researcherid, email=a.email)
                      for a in publication.creators.all()])
        return doc.to_dict(include_meta=True)

    def get_public_detail_url(self):
        return reverse('core:public-publication-detail', kwargs={'pk': self.meta.id})

    @classmethod
    def get_breadcrumb_data(cls):
        return {'breadcrumb_trail': [
            {'link': reverse('core:public-home'), 'text': 'Home'},
            {'text': 'Publications'}
        ]}

    @classmethod
    def get_public_list_url(cls, search=None):
        location = reverse('core:public-search')
        if search:
            query_string = urlencode({'search': search})
            location += '?{}'.format(query_string)
        return location

    class Index:
        name = 'publication'
        settings = {
            'number_of_shards': 1,
            # single-node cluster: replicas only add write overhead
            'number_of_replicas': 0
        }


autocomplete_analyzer = analyzer('autocomplete_analyzer',
                                 tokenizer=tokenizer(
                                    'edge_ngram_tokenizer',
                                    type='edge_ngram',
                                    min_gram=3,
                                    max_gram=10,
                                    token_chars=[
                                        "letter",
                                        "digit"
                                    ]),
                                 filter=['lowercase', 'asciifolding', 'trim'])


def get_search_index(model):
    # ensure the dsl default connection is configured so that
    # ``Document.search().execute()`` resolves it (no network I/O)
    get_es_client()
    lookup = {
        Author: AuthorDoc,
        Container: ContainerDoc,
        Platform: PlatformDoc,
        Sponsor: SponsorDoc,
        Tag: TagDoc,
    }
    try:
        return lookup[model]
    except KeyError:
        raise ValidationError(_('Invalid model_name'), code='invalid')


class AuthorDoc(Document):
    id = edsl.Integer(required=True)
    orcid = edsl.Keyword()
    researcherid = edsl.Keyword()
    email = edsl.Keyword()
    name = edsl.Text(copy_to=ALL_DATA_FIELD,
                     analyzer=autocomplete_analyzer,
                     search_analyzer='standard')

    @classmethod
    def from_instance(cls, author):
        doc = cls(meta = {'id': author.id},
                  id = author.id,
                  orcid = author.orcid,
                  researcherid = author.researcherid,
                  email = author.email,
                  name = author.name)
        return doc.to_dict(include_meta=True)

    class Index:
        name = 'author'
        settings = {
            'number_of_shards': 1,
            # single-node cluster: replicas only add write overhead
            'number_of_replicas': 0
        }


class ContainerDoc(Document):
    id = edsl.Integer(required=True)
    name = edsl.Text(copy_to=ALL_DATA_FIELD,
                     analyzer=autocomplete_analyzer,
                     search_analyzer='standard')
    issn = edsl.Keyword()

    @classmethod
    def from_instance(cls, container):
        doc = cls(meta = {'id': container.id},
                  id = container.id,
                  name = container.name,
                  issn = container.issn)
        return doc.to_dict(include_meta=True)

    class Index:
        name = 'container'
        settings = {
            'number_of_shards': 1,
            # single-node cluster: replicas only add write overhead
            'number_of_replicas': 0
        }


class PlatformDoc(Document):
    id = edsl.Integer(required=True)
    name = edsl.Text(copy_to=ALL_DATA_FIELD,
                     analyzer=autocomplete_analyzer,
                     search_analyzer='standard')

    @classmethod
    def from_instance(cls, instance):
        doc = cls(meta = {'id': instance.id},
                  id = instance.id,
                  name = instance.name)
        return doc.to_dict(include_meta=True)

    class Index:
        name = 'platform'
        settings = {
            'number_of_shards': 1,
            # single-node cluster: replicas only add write overhead
            'number_of_replicas': 0
        }


class SponsorDoc(Document):
    id = edsl.Integer(required=True)
    name = edsl.Text(copy_to=ALL_DATA_FIELD,
                     analyzer=autocomplete_analyzer,
                     search_analyzer='standard')

    @classmethod
    def from_instance(cls, instance):
        doc = cls(meta = {'id': instance.id},
                  id = instance.id,
                  name = instance.name)
        return doc.to_dict(include_meta=True)

    class Index:
        name = 'sponsor'
        settings = {
            'number_of_shards': 1,
            # single-node cluster: replicas only add write overhead
            'number_of_replicas': 0
        }


class TagDoc(Document):
    id = edsl.Integer(required=True)
    name = edsl.Text(copy_to=ALL_DATA_FIELD)

    @classmethod
    def from_instance(cls, instance):
        doc = cls(meta={'id': instance.id},
                  id = instance.id,
                  name = instance.name)
        return doc.to_dict(include_meta=True)

    class Index:
        name = 'tag'
        settings = {
            'number_of_shards': 1,
            # single-node cluster: replicas only add write overhead
            'number_of_replicas': 0
        }


def bulk_index_public():
    """
    Rebuild the public search indices from PostgreSQL.

    Every document class (author, container, platform, sponsor, tag and
    publication) is built into a fresh generation index under its stable
    read alias and validated; only after *all* generations validate are
    the stable aliases swapped onto the new generations in one atomic
    multi-alias operation (see ``rebuild_document_indices``). Any bulk
    failure, document-count mismatch, or failed swap leaves the live
    aliases untouched and cleans up only the new generations; previous
    generations are retained so the swap can be rolled back.
    """
    client = get_es_client()
    public_publications = Publication.api.primary().filter(status='REVIEWED')
    publication_ids = list(public_publications.values_list('id', flat=True))

    related_documents = (
        (AuthorDoc, Author.objects.filter(publications__id__in=publication_ids).distinct()),
        (ContainerDoc, Container.objects.filter(publications__id__in=publication_ids).distinct()),
        (PlatformDoc, Platform.objects.filter(publications__id__in=publication_ids).distinct()),
        (SponsorDoc, Sponsor.objects.filter(publications__id__in=publication_ids).distinct()),
        (TagDoc, Tag.objects.filter(publications__id__in=publication_ids).distinct()),
    )
    builds = [(doc_class,
               (doc_class.from_instance(instance) for instance in queryset),
               queryset.count())
              for doc_class, queryset in related_documents]
    builds.append((PublicationDoc,
                   (PublicationDoc.from_instance(publication) for publication in public_publications
                    .select_related('container')
                    .prefetch_related('code_archive_urls', 'tags', 'sponsors', 'platforms',
                                      'creators', 'model_documentation').iterator()),
                   len(publication_ids)))
    rebuild_document_indices(client, builds)
