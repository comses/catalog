"""
Focused unit tests for the Elasticsearch 8 search index layer.

These tests never touch a live Elasticsearch cluster: the ES client is
mocked and document classes are exercised against in-memory data. They
are written as SimpleTestCase so no test database is required.
"""
import re
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

# ``ObjectApiResponse`` is the exact response object the ES8 sync client
# returns (``elastic_transport`` re-exported through
# ``elasticsearch._sync.client``); its body is a plain dict.
from elastic_transport import ObjectApiResponse
from elasticsearch import BadRequestError, NotFoundError
from elasticsearch.helpers import BulkIndexError
from elasticsearch_dsl import Document

from citation.models import (
    Author,
    Container,
    Platform,
    Publication,
    Sponsor,
    Tag,
)

from catalog.core import search_indexes
from catalog.core.search_indexes import (
    AuthorDoc,
    ContainerDoc,
    PlatformDoc,
    PublicationDoc,
    PublicationDocSearch,
    SearchRebuildError,
    SponsorDoc,
    TagDoc,
    _index_doc_count,
    build_document_generation,
    bulk_index_public,
    generation_index_name,
    get_es_client,
    get_search_index,
    rebuild_document_indices,
    swap_generation_aliases,
)

ALL_DOC_CLASSES = (PublicationDoc, AuthorDoc, ContainerDoc, PlatformDoc, SponsorDoc, TagDoc)


class ElasticsearchSettingsTest(SimpleTestCase):
    def test_single_endpoint_with_sniffing_disabled(self):
        # one endpoint only, as a full URL (scheme://host:port) as the
        # ES8 client requires
        self.assertEqual(len(settings.ELASTICSEARCH['hosts']), 1)
        self.assertRegex(settings.ELASTICSEARCH['hosts'][0],
                         r'^https?://[A-Za-z0-9.-]+:\d+$')
        self.assertFalse(settings.ELASTICSEARCH['sniff_on_start'])
        self.assertFalse(settings.ELASTICSEARCH['sniff_on_node_failure'])


class DocTypePortTest(SimpleTestCase):
    def test_public_doc_classes_are_es8_documents(self):
        for doc_class in ALL_DOC_CLASSES:
            self.assertTrue(issubclass(doc_class, Document))

    def test_stable_read_alias_names(self):
        self.assertEqual(PublicationDoc._index._name, 'publication')
        self.assertEqual(AuthorDoc._index._name, 'author')
        self.assertEqual(ContainerDoc._index._name, 'container')
        self.assertEqual(PlatformDoc._index._name, 'platform')
        self.assertEqual(SponsorDoc._index._name, 'sponsor')
        self.assertEqual(TagDoc._index._name, 'tag')

    def test_generation_index_name_format(self):
        name = generation_index_name('publication')
        self.assertRegex(name, r'^publication-\d{8}T\d{6}Z$')

    def test_publication_index_keeps_single_shard_setting(self):
        self.assertEqual(PublicationDoc._index._settings.get('number_of_shards'), 1)

    def test_all_indices_are_single_node_with_zero_replicas(self):
        for doc_class in ALL_DOC_CLASSES:
            settings = doc_class._index._settings
            self.assertEqual(settings.get('number_of_shards'), 1, doc_class.__name__)
            self.assertEqual(settings.get('number_of_replicas'), 0, doc_class.__name__)

    def test_publication_mapping_keeps_inner_doc_object_and_nested_fields(self):
        # embedded documents must keep their Object/Nested InnerDoc
        # mappings in the index body used to create generation indices
        properties = PublicationDoc._index.to_dict()['mappings']['properties']
        for nested_field in ('authors', 'tags', 'sponsors', 'platforms', 'code_archive_urls'):
            self.assertEqual(properties[nested_field]['type'], 'nested', nested_field)
        self.assertEqual(properties['container']['type'], 'object')
        self.assertIn('name', properties['authors']['properties'])
        self.assertIn('issn', properties['container']['properties'])
        self.assertIn('url', properties['code_archive_urls']['properties'])

    def test_publication_from_instance_shape(self):
        container = mock.Mock()
        container.id, container.name, container.issn = 1, 'Container', '0001-2329'
        publication = mock.Mock()
        publication.id = 7
        publication.title = 'A Title'
        publication.incomplete_date_published = '1994-01'
        publication.date_modified = None
        publication.contact_email = 'a@b.c'
        publication.doi = '10.1/example'
        publication.container = container
        publication.code_archive_urls.all.return_value = []
        publication.tags.all.return_value = []
        publication.sponsors.all.return_value = []
        publication.platforms.all.return_value = []
        publication.model_documentation.all.return_value = []
        publication.creators.all.return_value = []

        action = PublicationDoc.from_instance(publication)

        self.assertEqual(action['_id'], 7)
        self.assertEqual(action['_index'], 'publication')
        self.assertEqual(action['_source']['title'], 'A Title')
        self.assertEqual(action['_source']['container']['id'], 1)

    def test_author_from_instance_shape(self):
        author = mock.Mock()
        author.id = 3
        author.orcid = None
        author.researcherid = None
        author.email = 'a@b.c'
        author.name = 'An Author'

        action = AuthorDoc.from_instance(author)

        self.assertEqual(action['_id'], 3)
        self.assertEqual(action['_index'], 'author')
        self.assertEqual(action['_source']['name'], 'An Author')


class GetEsClientTest(SimpleTestCase):
    def tearDown(self):
        search_indexes._ES_CLIENT = None

    def test_lazy_client_uses_settings_and_wires_dsl_default(self):
        sentinel = mock.Mock(name='es_client')
        with mock.patch.object(search_indexes.connections, 'configure') as configure, \
                mock.patch.object(search_indexes.connections, 'get_connection',
                                  return_value=sentinel) as get_connection:
            client = get_es_client()
        self.assertIs(client, sentinel)
        configure.assert_called_once_with(default=settings.ELASTICSEARCH)
        get_connection.assert_called_once_with()

    def test_client_is_cached(self):
        sentinel = mock.Mock(name='es_client')
        with mock.patch.object(search_indexes.connections, 'configure'), \
                mock.patch.object(search_indexes.connections, 'get_connection',
                                  return_value=sentinel) as get_connection:
            self.assertIs(get_es_client(), get_es_client())
        get_connection.assert_called_once()


class BuildDocumentGenerationTest(SimpleTestCase):
    def _client(self, count_value):
        client = mock.MagicMock(name='es_client')
        # no live alias, no pre-existing generations
        client.indices.get_alias.side_effect = NotFoundError('no such alias', meta=None, body=None)
        client.indices.get.side_effect = NotFoundError('no such index', meta=None, body=None)
        # realistic ES8 count response: mapping-backed object, dict body
        client.count.return_value = ObjectApiResponse(
            {'count': count_value,
             '_shards': {'total': 1, 'successful': 1, 'skipped': 0, 'failed': 0}}, 200)
        return client

    def _capture_bulk(self):
        calls = []

        def fake_bulk(client=None, actions=None, index=None, **kwargs):
            calls.append({'client': client, 'index': index, 'actions': list(actions)})
            return (len(calls[-1]['actions']), [])

        return calls, fake_bulk

    def _author_actions(self, ids):
        # realistic ES8 action shape: ``Document.to_dict(include_meta=True)``
        # stamps the stable read alias onto ``_index``
        actions = []
        for doc_id in ids:
            author = mock.Mock()
            author.id = doc_id
            author.orcid = None
            author.researcherid = None
            author.email = 'author{0}@example.com'.format(doc_id)
            author.name = 'Author {0}'.format(doc_id)
            actions.append(AuthorDoc.from_instance(author))
        return actions

    def test_es8_count_response_is_read_by_mapping_access(self):
        # the real client returns an ObjectApiResponse (not a dict);
        # ``getattr(response, 'count')`` raises AttributeError on it, so
        # the count must come from mapping access
        client = mock.MagicMock(name='es_client')
        client.count.return_value = ObjectApiResponse({'count': 3}, 200)
        self.assertEqual(_index_doc_count(client, 'some-index'), 3)
        client.count.return_value = {'count': 7}
        self.assertEqual(_index_doc_count(client, 'some-index'), 7)

    def test_happy_path_builds_and_validates_without_touching_aliases(self):
        client = self._client(count_value=2)
        actions = self._author_actions([1, 2])
        calls, fake_bulk = self._capture_bulk()
        with mock.patch.object(search_indexes, 'bulk', side_effect=fake_bulk):
            index_name = build_document_generation(client, AuthorDoc, iter(actions),
                                                   expected_count=2)

        # created on a generation index carrying the doc class mappings
        # and the single-node index settings
        create_kwargs = client.indices.create.call_args.kwargs
        self.assertRegex(create_kwargs['index'], r'^author-\d{8}T\d{6}Z$')
        self.assertEqual(index_name, create_kwargs['index'])
        self.assertIn('mappings', create_kwargs['body'])
        self.assertEqual(create_kwargs['body']['settings']['number_of_shards'], 1)
        self.assertEqual(create_kwargs['body']['settings']['number_of_replicas'], 0)

        # bulk loaded into the same generation index, alias stripped
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['client'], client)
        self.assertEqual(calls[0]['index'], index_name)
        for sent, original in zip(calls[0]['actions'], actions):
            self.assertNotIn('_index', sent)
            self.assertEqual(sent.get('_id'), original['_id'])
            self.assertEqual(sent.get('_source'), original['_source'])

        client.indices.refresh.assert_called_once_with(index=index_name)

        # building never swaps or inspects aliases; nothing deleted
        client.indices.update_aliases.assert_not_called()
        client.indices.get_alias.assert_not_called()
        client.options.assert_not_called()

    def test_bulk_actions_are_forced_to_generation_physical_index(self):
        # defect guard: actions carry the stable alias ``author`` as
        # ``_index``; a bulk that honored per-action indices would load
        # the *previous* generation instead of the new one
        client = self._client(count_value=1)
        actions = self._author_actions([1])
        self.assertEqual(actions[0]['_index'], 'author')
        calls, fake_bulk = self._capture_bulk()
        with mock.patch.object(search_indexes, 'bulk', side_effect=fake_bulk):
            index_name = build_document_generation(client, AuthorDoc, iter(actions),
                                                   expected_count=1)

        call = calls[0]
        self.assertEqual(call['index'], index_name)
        self.assertNotEqual(call['index'], 'author')
        for action in call['actions']:
            self.assertNotIn('_index', action)
        # the original actions are not mutated in place
        self.assertEqual(actions[0]['_index'], 'author')

    def test_count_mismatch_aborts_and_deletes_only_new_generation(self):
        client = self._client(count_value=1)
        with mock.patch.object(search_indexes, 'bulk', return_value=(2, [])):
            with self.assertRaises(SearchRebuildError):
                build_document_generation(client, AuthorDoc,
                                          iter(self._author_actions([1, 2])),
                                          expected_count=2)

        # live alias untouched, half-loaded generation removed
        client.indices.update_aliases.assert_not_called()
        client.indices.get_alias.assert_not_called()
        client.options.assert_called_once_with(ignore_status=[400, 404])
        deleted = [c.kwargs['index']
                   for c in client.options.return_value.indices.delete.call_args_list]
        self.assertEqual(deleted, [client.indices.create.call_args.kwargs['index']])

    def test_bulk_failure_aborts_and_deletes_only_new_generation(self):
        client = self._client(count_value=1)
        with mock.patch.object(search_indexes, 'bulk',
                               side_effect=BulkIndexError('1 document failed', [{}])):
            with self.assertRaises(BulkIndexError):
                build_document_generation(client, AuthorDoc,
                                          iter(self._author_actions([1])),
                                          expected_count=1)

        client.indices.update_aliases.assert_not_called()
        client.indices.get_alias.assert_not_called()
        client.options.assert_called_once_with(ignore_status=[400, 404])
        deleted = [c.kwargs['index']
                   for c in client.options.return_value.indices.delete.call_args_list]
        self.assertEqual(deleted, [client.indices.create.call_args.kwargs['index']])


class SwapGenerationAliasesTest(SimpleTestCase):
    def _client_with_aliases(self, alias_targets):
        client = mock.MagicMock(name='es_client')

        def get_alias(name, **kwargs):
            if name in alias_targets:
                return {alias_targets[name]: {'aliases': {name: {}}}}
            raise NotFoundError('no such alias', meta=None, body=None)

        client.indices.get_alias.side_effect = get_alias
        client.indices.get.side_effect = NotFoundError('no such index', meta=None, body=None)
        return client

    def test_single_atomic_multi_alias_swap(self):
        client = self._client_with_aliases({
            'author': 'author-20240101T000000Z',
            'tag': 'tag-20240101T000000Z',
        })
        swap_generation_aliases(client, {
            'author': 'author-20260101T000000Z',
            'tag': 'tag-20260101T000000Z',
        })

        # one atomic update_aliases call covering every alias:
        # remove from the previous generation, add on the new one
        client.indices.update_aliases.assert_called_once()
        actions = client.indices.update_aliases.call_args.kwargs['actions']
        self.assertEqual(actions, [
            {'remove': {'index': 'author-20240101T000000Z', 'alias': 'author'}},
            {'add': {'index': 'author-20260101T000000Z', 'alias': 'author'}},
            {'remove': {'index': 'tag-20240101T000000Z', 'alias': 'tag'}},
            {'add': {'index': 'tag-20260101T000000Z', 'alias': 'tag'}},
        ])
        # previous generations retained: nothing older to prune
        client.options.assert_not_called()

    def test_first_swap_is_add_only(self):
        client = self._client_with_aliases({})
        swap_generation_aliases(client, {'author': 'author-20260101T000000Z'})
        actions = client.indices.update_aliases.call_args.kwargs['actions']
        self.assertEqual(actions, [{'add': {'index': 'author-20260101T000000Z',
                                            'alias': 'author'}}])

    def test_swap_prunes_generations_older_than_previous(self):
        client = self._client_with_aliases({'author': 'author-20240101T000000Z'})
        client.indices.get.side_effect = None
        client.indices.get.return_value = {
            'author-20230101T000000Z': {},
            'author-20230601T000000Z': {},
            'author-20240101T000000Z': {},
        }
        swap_generation_aliases(client, {'author': 'author-20260101T000000Z'})

        deleted = [c.kwargs['index']
                   for c in client.options.return_value.indices.delete.call_args_list]
        # older generations pruned; new + previous generation kept
        self.assertEqual(deleted, ['author-20230101T000000Z', 'author-20230601T000000Z'])


class RebuildDocumentIndicesTest(SimpleTestCase):
    def _logged_client(self, alias_targets=None, count_value=1):
        client = mock.MagicMock(name='es_client')
        events = []

        def log_create(index, **kwargs):
            events.append(('create', index))

        def log_refresh(index, **kwargs):
            events.append(('refresh', index))

        def log_swap(actions=None):
            events.append(('swap', actions))

        client.indices.create.side_effect = log_create
        client.indices.refresh.side_effect = log_refresh
        client.indices.update_aliases.side_effect = log_swap
        alias_targets = alias_targets or {}

        def get_alias(name, **kwargs):
            if name in alias_targets:
                return {alias_targets[name]: {'aliases': {name: {}}}}
            raise NotFoundError('no such alias', meta=None, body=None)

        client.indices.get_alias.side_effect = get_alias
        client.indices.get.side_effect = NotFoundError('no such index', meta=None, body=None)
        client.count.return_value = ObjectApiResponse({'count': count_value}, 200)
        return client, events

    def _capture_bulk(self):
        calls = []

        def fake_bulk(client=None, actions=None, index=None, **kwargs):
            calls.append({'client': client, 'index': index, 'actions': list(actions)})
            return (len(calls[-1]['actions']), [])

        return calls, fake_bulk

    def _builds(self):
        builds = []
        for doc_class in (AuthorDoc, TagDoc, SponsorDoc):
            instance = mock.Mock()
            instance.id = 1
            instance.orcid = None
            instance.researcherid = None
            instance.email = 'one@example.com'
            instance.name = 'One'
            builds.append((doc_class, iter([doc_class.from_instance(instance)]), 1))
        return builds

    def test_all_generations_built_and_validated_before_single_atomic_swap(self):
        client, events = self._logged_client(count_value=1)
        calls, fake_bulk = self._capture_bulk()
        with mock.patch.object(search_indexes, 'bulk', side_effect=fake_bulk):
            result = rebuild_document_indices(client, self._builds())

        self.assertEqual(set(result), {'author', 'tag', 'sponsor'})

        # every create+refresh precedes the single, final atomic swap
        kinds = [kind for kind, _ in events]
        self.assertEqual(kinds.count('swap'), 1)
        self.assertEqual(kinds[-1], 'swap')
        for kind in kinds[:-1]:
            self.assertIn(kind, ('create', 'refresh'))

        # each class was bulk-loaded onto its own generation index,
        # without per-action stable aliases
        self.assertEqual(len(calls), 3)
        for call in calls:
            alias = call['index'].split('-')[0]
            self.assertIn(alias, {'author', 'tag', 'sponsor'})
            for action in call['actions']:
                self.assertNotIn('_index', action)

        # one atomic multi-alias swap: one add per alias, no removes
        # (no previous generation)
        swap_actions = events[-1][1]
        self.assertEqual(len(swap_actions), 3)
        self.assertEqual({a['add']['alias'] for a in swap_actions},
                         {'author', 'tag', 'sponsor'})
        for action in swap_actions:
            self.assertNotIn('remove', action)

        # nothing deleted on success
        client.options.assert_not_called()

    def test_build_failure_cleans_only_new_generations_and_leaves_aliases(self):
        client, events = self._logged_client(count_value=1)

        def failing_bulk(client=None, actions=None, index=None, **kwargs):
            if index.startswith('tag-'):
                raise BulkIndexError('1 document failed', [{}])
            return (len(list(actions)), [])

        with mock.patch.object(search_indexes, 'bulk', side_effect=failing_bulk):
            with self.assertRaises(BulkIndexError):
                rebuild_document_indices(client, self._builds())

        # no alias was ever consulted or swapped
        client.indices.get_alias.assert_not_called()
        client.indices.update_aliases.assert_not_called()

        # only the new generations are deleted: the failed one and the
        # one already built successfully before the failure
        created = [c.kwargs['index'] for c in client.indices.create.call_args_list]
        deleted = [c.kwargs['index']
                   for c in client.options.return_value.indices.delete.call_args_list]
        self.assertEqual(len(created), 2)
        self.assertEqual(sorted(deleted), sorted(created))
        self.assertNotIn('swap', [kind for kind, _ in events])

    def test_swap_failure_cleans_new_generations_and_keeps_previous(self):
        alias_targets = {
            'author': 'author-20240101T000000Z',
            'tag': 'tag-20240101T000000Z',
            'sponsor': 'sponsor-20240101T000000Z',
        }
        client, events = self._logged_client(alias_targets=alias_targets, count_value=1)
        client.indices.update_aliases.side_effect = BadRequestError(
            'alias already exists', meta=None, body=None)

        with mock.patch.object(search_indexes, 'bulk', return_value=(1, [])):
            with self.assertRaises(BadRequestError):
                rebuild_document_indices(client, self._builds())

        # the swap was attempted once, atomically, for all aliases
        self.assertEqual(client.indices.update_aliases.call_count, 1)
        swap_actions = client.indices.update_aliases.call_args.kwargs['actions']
        self.assertEqual(len(swap_actions), 6)
        self.assertEqual({a['remove']['alias'] for a in swap_actions if 'remove' in a},
                         set(alias_targets))

        # all new generations cleaned up; previous generations untouched
        created = [c.kwargs['index'] for c in client.indices.create.call_args_list]
        deleted = [c.kwargs['index']
                   for c in client.options.return_value.indices.delete.call_args_list]
        self.assertEqual(sorted(deleted), sorted(created))
        for old in alias_targets.values():
            self.assertNotIn(old, deleted)

    def test_successful_rebuild_retains_previous_generation(self):
        alias_targets = {
            'author': 'author-20240101T000000Z',
            'tag': 'tag-20240101T000000Z',
            'sponsor': 'sponsor-20240101T000000Z',
        }
        client, events = self._logged_client(alias_targets=alias_targets, count_value=1)
        with mock.patch.object(search_indexes, 'bulk', return_value=(1, [])):
            result = rebuild_document_indices(client, self._builds())

        self.assertEqual(set(result), set(alias_targets))
        # each alias: removed from the previous generation and added on
        # the new one, in one atomic call
        actions = client.indices.update_aliases.call_args.kwargs['actions']
        self.assertEqual(len(actions), 6)
        for alias, old_index in alias_targets.items():
            self.assertIn({'remove': {'index': old_index, 'alias': alias}}, actions)
            self.assertIn({'add': {'index': result[alias], 'alias': alias}}, actions)
        # previous generations retained for rollback; nothing deleted
        client.options.assert_not_called()


class BulkIndexPublicTest(SimpleTestCase):
    class FakeQuerySet(list):
        def filter(self, *args, **kwargs):
            return self

        def distinct(self):
            return self

        def select_related(self, *args, **kwargs):
            return self

        def prefetch_related(self, *args, **kwargs):
            return self

        def values_list(self, *args, **kwargs):
            return self

        def iterator(self):
            return iter(self)

        def count(self):
            return len(self)

    def test_rebuilds_all_classes_and_swaps_all_aliases_atomically(self):
        client = mock.MagicMock(name='es_client')
        events = []
        client.indices.create.side_effect = (
            lambda index, **kw: events.append(('create', index)))
        client.indices.update_aliases.side_effect = (
            lambda actions=None: events.append(('swap', actions)))
        client.indices.get_alias.side_effect = NotFoundError('no such alias', meta=None, body=None)
        client.indices.get.side_effect = NotFoundError('no such index', meta=None, body=None)
        client.count.return_value = ObjectApiResponse({'count': 0}, 200)

        publications = self.FakeQuerySet()
        related = self.FakeQuerySet()
        with mock.patch.object(search_indexes, 'get_es_client', return_value=client), \
                mock.patch.object(search_indexes, 'bulk'), \
                mock.patch.object(search_indexes.Publication.api, 'primary',
                                  return_value=publications), \
                mock.patch.object(search_indexes.Author.objects, 'filter', return_value=related), \
                mock.patch.object(search_indexes.Container.objects, 'filter',
                                  return_value=related) as container_filter, \
                mock.patch.object(search_indexes.Platform.objects, 'filter', return_value=related), \
                mock.patch.object(search_indexes.Sponsor.objects, 'filter', return_value=related), \
                mock.patch.object(search_indexes.Tag.objects, 'filter', return_value=related):
            bulk_index_public()
        # the container documents are actually queried
        container_filter.assert_called_once_with(publications__id__in=[])

        # ContainerDoc included: every alias gets its own generation index
        created = [c.kwargs['index'] for c in client.indices.create.call_args_list]
        self.assertEqual(len(created), 6)
        self.assertEqual({name.split('-')[0] for name in created},
                         {'author', 'container', 'platform', 'sponsor', 'tag', 'publication'})
        for index_name in created:
            self.assertRegex(index_name, r'^[a-z]+-\d{8}T\d{6}Z$')

        # one atomic multi-alias swap, not one swap per class
        self.assertEqual(client.indices.update_aliases.call_count, 1)
        swap_actions = client.indices.update_aliases.call_args.kwargs['actions']
        self.assertEqual(len(swap_actions), 6)
        self.assertEqual({a['add']['alias'] for a in swap_actions},
                         {'author', 'container', 'platform', 'sponsor', 'tag', 'publication'})
        for action in swap_actions:
            self.assertNotIn('remove', action)  # no previous generation
        # every add targets one of the freshly created generation indices
        self.assertEqual({a['add']['index'] for a in swap_actions}, set(created))

        # all generations are built before the single final swap
        self.assertEqual(events[-1][0], 'swap')
        for kind, _ in events[:-1]:
            self.assertEqual(kind, 'create')


class PublicationDocSearchTest(SimpleTestCase):
    def test_find_builds_expected_query_without_network(self):
        search = PublicationDocSearch().find('hello', {'tags': [1, 2]})
        body = search.search.to_dict()
        self.assertEqual(body['query']['bool']['must'],
                         [{'query_string': {'query': 'hello', 'default_field': 'all_data'}}])
        self.assertEqual(body['query']['bool']['should'],
                         [{'nested': {'path': 'tags', 'query': {'terms': {'tags.id': [1, 2]}}}}])
        self.assertEqual(body['query']['bool']['minimum_should_match'], 1)

    def test_find_without_query_or_filters_sorts_by_date(self):
        search = PublicationDocSearch().find('', {})
        self.assertEqual(search.search.to_dict()['sort'],
                         [{'incomplete_date_published': {'order': 'desc'}}])

    def test_get_search_index_lookup(self):
        with mock.patch.object(search_indexes, 'get_es_client'):
            self.assertIs(get_search_index(Author), AuthorDoc)
            self.assertIs(get_search_index(Container), ContainerDoc)
            self.assertIs(get_search_index(Platform), PlatformDoc)
            self.assertIs(get_search_index(Sponsor), SponsorDoc)
            self.assertIs(get_search_index(Tag), TagDoc)
            with self.assertRaises(ValidationError):
                get_search_index(Publication)
