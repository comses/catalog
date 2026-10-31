"""
Focused unit tests for the ``rebuild_es_index`` management command.

``bulk_index_all`` is mocked, so no live Elasticsearch cluster,
PostgreSQL database, or dev-only packages (Invoke) are involved. These
tests are written as SimpleTestCase so no test database is required.
"""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from elasticsearch.helpers import BulkIndexError

from catalog.core.search_indexes import SearchRebuildError

PATCH_TARGET = (
    'catalog.core.management.commands.rebuild_es_index.bulk_index_all')
REBUILD_LOGGER = 'catalog.core.management.commands.rebuild_es_index'
VALIDATE_LOGGER = 'catalog.core.management.commands.validate_search_indexes'


class RebuildEsIndexCommandTest(SimpleTestCase):
    def test_success_delegates_to_bulk_index_all(self):
        out = StringIO()
        with mock.patch(PATCH_TARGET) as bulk:
            call_command('rebuild_es_index', stdout=out)
        bulk.assert_called_once_with()
        self.assertIn('rebuilt successfully', out.getvalue())

    def test_validation_failure_raises_command_error(self):
        out = StringIO()
        failure = SearchRebuildError(
            'index publication-20260101T000000Z validation failed: '
            'expected 10 documents, found 9')
        with mock.patch(PATCH_TARGET, side_effect=failure):
            with self.assertLogs(REBUILD_LOGGER, 'ERROR'), self.assertRaises(CommandError) as ctx:
                call_command('rebuild_es_index', stdout=out)
        # the original failure is preserved on the exception chain
        self.assertIs(ctx.exception.__cause__, failure)
        self.assertIn('validation failed', str(ctx.exception))

    def test_build_failure_raises_command_error(self):
        out = StringIO()
        with mock.patch(PATCH_TARGET,
                        side_effect=BulkIndexError('1 document failed', [{}])):
            with self.assertLogs(REBUILD_LOGGER, 'ERROR'), self.assertRaises(CommandError):
                call_command('rebuild_es_index', stdout=out)

    def test_alias_swap_failure_raises_command_error(self):
        out = StringIO()
        swap_failure = RuntimeError('alias swap failed')
        with mock.patch(PATCH_TARGET, side_effect=swap_failure):
            with self.assertLogs(REBUILD_LOGGER, 'ERROR'), self.assertRaises(CommandError) as ctx:
                call_command('rebuild_es_index', stdout=out)
        self.assertIs(ctx.exception.__cause__, swap_failure)

    def test_success_message_uses_stdout_style(self):
        out = StringIO()
        with mock.patch(PATCH_TARGET):
            call_command('rebuild_es_index', stdout=out)
        # the success line is written to stdout, not stderr
        self.assertIn('Public and curator search indices', out.getvalue())


class ValidateSearchIndexesCommandTest(SimpleTestCase):
    patch_target = (
        'catalog.core.management.commands.validate_search_indexes.'
        'validate_search_indices')

    def test_success_reports_validated_counts(self):
        out = StringIO()
        with mock.patch(self.patch_target, return_value={
            'publication': 7,
            'publication_curator': 9,
        }) as validate:
            call_command('validate_search_indexes', stdout=out)

        validate.assert_called_once_with()
        self.assertIn('publication=7', out.getvalue())
        self.assertIn('publication_curator=9', out.getvalue())

    def test_failure_raises_command_error(self):
        failure = SearchRebuildError("search alias 'publication' is missing")
        with mock.patch(self.patch_target, side_effect=failure):
            with self.assertLogs(VALIDATE_LOGGER, 'ERROR'), self.assertRaises(CommandError) as ctx:
                call_command('validate_search_indexes')

        self.assertIs(ctx.exception.__cause__, failure)
