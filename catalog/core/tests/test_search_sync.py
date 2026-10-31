from unittest import mock

from elasticsearch import NotFoundError
from elasticsearch.helpers import BulkIndexError

from citation.models import (
    AuditCommand,
    AuditLog,
    Author,
    Container,
    Publication,
    PublicationAuthors,
)
from citation.serializers import PublicationSerializer

from catalog.core.search_indexes import (
    _curator_contributor_data,
    refresh_search_documents,
)

from .common import BaseTest


class SearchSyncTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.container = Container.objects.create(name='Journal')
        self.author = Author.objects.create(
            given_name='Ada',
            family_name='Lovelace',
            email='private@example.com',
        )
        self.publication = Publication.objects.create(
            title='Searchable model',
            added_by=self.user,
            container=self.container,
            contact_email='contact@example.com',
            status=Publication.Status.REVIEWED,
        )
        PublicationAuthors.objects.create(
            publication=self.publication,
            author=self.author,
            role=PublicationAuthors.RoleChoices.AUTHOR,
        )

    def sync(self, bulk_result=(4, [])):
        """Runs a refresh for the fixture publication with bulk mocked; returns the bulk mock."""
        client = mock.MagicMock()
        client.indices.get_alias.return_value = {'generation-1': {}}
        with (
            mock.patch('catalog.core.search_indexes.get_es_client', return_value=client),
            mock.patch('catalog.core.search_indexes.bulk', return_value=bulk_result) as bulk,
        ):
            refresh_search_documents(publication_ids=(self.publication.pk,))
        return bulk

    @staticmethod
    def actions(bulk):
        bulk.assert_called_once()
        self_args = bulk.call_args
        assert self_args.kwargs['refresh'] == 'wait_for'
        return list(self_args.args[1])

    def test_reviewed_publication_updates_public_and_curator_aliases_without_pii(self):
        # Batched updates wait for refresh without a separate wait for each document.
        actions = self.actions(self.sync())

        self.assertEqual([(a['_op_type'], a['_index']) for a in actions[:2]],
                         [('index', 'publication_curator'), ('index', 'publication')])
        # the publication's related records reach autocomplete with it
        self.assertEqual({(a['_index'], a['_id']) for a in actions[2:]},
                         {('container', self.container.pk), ('author', self.author.pk)})
        public_document = actions[1]['_source']
        self.assertNotIn('contact_email', public_document)
        self.assertNotIn('has_contact_email', public_document)
        self.assertNotIn('email', public_document['authors'][0])

    def test_a_missing_alias_is_never_written_through(self):
        # indexing through a missing alias would auto-create a concrete index of that
        # name, after which rebuild_es_index can never add the alias again.
        client = mock.MagicMock()
        client.indices.get_alias.side_effect = NotFoundError('no such alias', meta=None, body=None)
        with (
            mock.patch('catalog.core.search_indexes.get_es_client', return_value=client),
            mock.patch('catalog.core.search_indexes.bulk') as bulk,
            self.assertLogs('catalog.core.search_indexes', 'WARNING') as logs,
        ):
            refresh_search_documents(publication_ids=(self.publication.pk,))

        bulk.assert_not_called()
        self.assertTrue(any('run rebuild_es_index' in line for line in logs.output))

    def test_unreviewed_publication_is_removed_from_public_alias(self):
        self.publication.status = Publication.Status.UNREVIEWED
        self.publication.save(update_fields=('status',))
        actions = self.actions(self.sync())

        self.assertEqual((actions[0]['_op_type'], actions[0]['_index']), ('index', 'publication_curator'))
        self.assertIn({'_op_type': 'delete', '_index': 'publication', '_id': self.publication.pk}, actions)
        self.assertNotIn(('index', 'publication'), [(a['_op_type'], a['_index']) for a in actions])

    def test_a_delete_of_an_absent_document_is_not_an_error_but_an_index_failure_is(self):
        self.sync(bulk_result=(3, [{'delete': {'_id': 1, 'status': 404, 'result': 'not_found'}}]))
        with self.assertRaises(BulkIndexError):
            self.sync(bulk_result=(3, [{'index': {'_id': 1, 'status': 400, 'error': 'mapper_parsing_exception'}}]))

    def test_serializer_save_survives_elasticsearch_outage(self):
        serializer = PublicationSerializer(self.publication)
        data = serializer.data
        data['title'] = 'Saved while search is unavailable'
        serializer = PublicationSerializer(self.publication, data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with mock.patch(
            'catalog.core.search_sync.refresh_search_documents',
            side_effect=RuntimeError('Elasticsearch unavailable'),
        ), self.assertLogs('citation.signals', level='ERROR'):
            with self.captureOnCommitCallbacks(execute=True):
                saved = serializer.save(user=self.user)

        saved.refresh_from_db()
        self.assertEqual(saved.title, 'Saved while search is unavailable')

    def test_curator_contributions_are_aggregated_for_all_publications(self):
        other_user = self.create_user(
            username='other-curator',
            email='other@example.com',
        )
        first_command = AuditCommand.objects.create(
            creator=self.user,
            action=AuditCommand.Action.MANUAL,
        )
        second_command = AuditCommand.objects.create(
            creator=other_user,
            action=AuditCommand.Action.MANUAL,
        )
        AuditLog.objects.bulk_create(
            [
                AuditLog(
                    action='UPDATE',
                    row_id=self.publication.pk,
                    table='publication',
                    audit_command=first_command,
                ),
                AuditLog(
                    action='UPDATE',
                    row_id=self.publication.pk,
                    table='publication',
                    audit_command=first_command,
                ),
                AuditLog(
                    action='UPDATE',
                    row_id=self.author.pk,
                    table='author',
                    pub_id=self.publication,
                    audit_command=second_command,
                ),
            ]
        )

        contributions = _curator_contributor_data()

        self.assertCountEqual(
            contributions[self.publication.pk],
            ['testcase (66%)', 'other-curator (33%)'],
        )
