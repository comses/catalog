import json
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import psycopg2
from psycopg2 import sql
from django.db import DatabaseError, connection, connections, transaction
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from citation.models import Container, Publication

from catalog.core import backups


class BackupSnapshotTest(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = backups.database_settings()
        self.source = connection.settings_dict['NAME']
        self.connect = connection.get_connection_params()
        self.restored = 'backup_restored_' + uuid.uuid4().hex
        self.admin = psycopg2.connect(**{**self.connect, 'dbname': 'postgres'})
        self.admin.autocommit = True
        self.addCleanup(self.admin.close)
        for name in (self.restored,):
            with self.admin.cursor() as cursor:
                cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            self.addCleanup(self.drop_database, name)
        self.user = get_user_model().objects.create(username='backup-test')
        self.container = Container.objects.create(name='Backup test journal')
        Publication.objects.bulk_create([
            Publication(id=1, title='First', is_primary=True, added_by=self.user, container=self.container),
            Publication(id=2, title='Second', is_primary=False, added_by=self.user, container=self.container),
            Publication(id=3, title='Third', is_primary=True, added_by=self.user, container=self.container),
        ])

    def drop_database(self, name):
        with self.admin.cursor() as cursor:
            cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

    def execute(self, database, statement):
        connection = psycopg2.connect(**{**self.connect, 'dbname': database})
        try:
            with connection, connection.cursor() as cursor:
                cursor.execute(statement)
                return cursor.fetchall() if cursor.description else None
        finally:
            connection.close()

    def create_backup(self):
        with override_settings(BACKUP_ROOT=str(self.root)):
            return backups.create_backup()

    def test_receipt_and_restored_rows_use_the_same_snapshot(self):
        self.assert_consistent_restore(after_dump=False)

    def test_edits_after_dump_do_not_change_receipt_counts(self):
        self.assert_consistent_restore(after_dump=True)

    def assert_consistent_restore(self, after_dump):
        original = backups.write_dump
        def concurrent_writes(*args, **kwargs):
            if after_dump:
                original(*args, **kwargs)
            def insert():
                try:
                    Publication.objects.bulk_create([
                        Publication(id=4, title='Fourth', is_primary=False,
                                    added_by_id=self.user.pk, container_id=self.container.pk),
                        Publication(id=5, title='Fifth', is_primary=False,
                                    added_by_id=self.user.pk, container_id=self.container.pk),
                    ])
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(insert).result(timeout=30)
            self.execute(self.source, 'DELETE FROM citation_publication WHERE id = 2')
            self.execute(self.source, 'UPDATE citation_publication SET is_primary = false WHERE id = 1')
            if not after_dump:
                return original(*args, **kwargs)
        with mock.patch.object(backups, 'write_dump', side_effect=concurrent_writes):
            result = self.create_backup()
        archive = self.root / result['archive']
        subprocess.run(['pg_restore', *self.db['command'], '--exit-on-error', '--no-owner',
                        '--no-privileges', '--dbname', self.restored, str(archive)],
                       env=self.db['env'], check=True, capture_output=True)
        rows = self.execute(self.restored, 'SELECT id, is_primary FROM citation_publication ORDER BY id')
        assert rows is not None
        self.assertEqual(rows, [(1, True), (2, False), (3, True)])
        self.assertNotEqual(self.execute(self.source, 'SELECT id, is_primary FROM citation_publication ORDER BY id'), rows)
        counts = {'citation_publication': len(rows), 'primary_publication': sum(primary for _, primary in rows)}
        self.assertEqual(result['counts'], counts)
        self.assertEqual(json.loads(Path(str(archive) + '.json').read_text())['counts'], counts)
        self.assert_snapshot_released()

    def assert_snapshot_released(self):
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute('SHOW transaction_read_only')
            self.assertEqual(cursor.fetchone()[0], 'off')
            cursor.execute('SHOW transaction_isolation')
            self.assertEqual(cursor.fetchone()[0], 'read committed')
        with self.admin.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND state LIKE 'idle in transaction%%'", [self.source])
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_dump_failure_releases_snapshot_without_advancing_marker(self):
        first = self.create_backup()
        marker = (self.root / backups.MARKER_NAME).read_bytes()
        with mock.patch.object(backups, 'write_dump', side_effect=backups.BackupError('dump failed')):
            with self.assertRaises(backups.BackupError):
                self.create_backup()
        self.assertEqual((self.root / backups.MARKER_NAME).read_bytes(), marker)
        self.assertEqual([p.name for p in self.root.glob('*.dump')], [first['archive']])
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assert_snapshot_released()

    def test_snapshot_export_failure_does_not_publish_success(self):
        def reject_export(execute, statement, params, many, context):
            if 'pg_export_snapshot' in statement:
                raise DatabaseError('snapshot export failed')
            return execute(statement, params, many, context)
        with connection.execute_wrapper(reject_export):
            with self.assertRaisesRegex(backups.BackupError, 'snapshot failed'):
                self.create_backup()
        self.assertFalse((self.root / backups.MARKER_NAME).exists())
        self.assertEqual(list(self.root.glob('*.dump')), [])
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assert_snapshot_released()

    def test_backup_refuses_an_existing_transaction_without_changing_it(self):
        with transaction.atomic():
            Publication.objects.filter(pk=1).update(title='Uncommitted edit')
            with mock.patch.object(backups, 'write_dump') as dump:
                with self.assertRaisesRegex(backups.BackupError, 'outside an existing transaction'):
                    self.create_backup()
            dump.assert_not_called()
            self.assertEqual(Publication.objects.get(pk=1).title, 'Uncommitted edit')
            self.assertTrue(connection.in_atomic_block)
        self.assertEqual(Publication.objects.get(pk=1).title, 'Uncommitted edit')
        self.assertFalse((self.root / backups.MARKER_NAME).exists())
        self.assert_snapshot_released()

    def test_backup_refuses_manually_disabled_autocommit(self):
        transaction.set_autocommit(False)
        try:
            with self.assertRaisesRegex(backups.BackupError, 'outside an existing transaction'):
                self.create_backup()
            self.assertFalse(connection.get_autocommit())
        finally:
            transaction.rollback()
            transaction.set_autocommit(True)
