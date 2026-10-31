"""
Tests for the ``backup_database`` management command.

``pg_dump`` and ``pg_restore`` are replaced by a fake runner, so the tests need
the test database (for the counts and the server version) but no PostgreSQL
client tools.
"""
import fcntl
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from catalog.core import backups

RUN_TARGET = 'catalog.core.backups.subprocess.run'
COMMAND_LOGGER = 'catalog.core.management.commands.backup_database'


def fake_run(failing=()):
    """Stands in for subprocess.run with the PostgreSQL client tools, keeping their argument contract."""
    def run(command, env=None, check=False, stdin=None, stdout=None, capture_output=False, text=False):
        tool = command[0]
        assert env['PGPASSWORD'] is not None
        if command[1:] == ['--version']:
            assert capture_output and text
            return subprocess.CompletedProcess(command, 0, '{0} (PostgreSQL) 18.6\n'.format(tool), '')
        if tool in failing:
            raise subprocess.CalledProcessError(1, command)
        assert stdin is not None, 'every tool gets an explicit stdin'
        if tool == 'pg_dump':
            assert '--format' in command and command[-1] == env['PGDATABASE_FOR_TEST']
            stdout.write(b'PGDMP fake custom dump')
        elif tool == 'pg_restore':
            assert command[1:] == ['--list'] and stdout is subprocess.DEVNULL
            assert stdin.read() == b'PGDMP fake custom dump'
        return subprocess.CompletedProcess(command, 0, '', '')
    return run


class BackupDatabaseCommandTest(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        if os.geteuid() == 0:
            # On hosts the backups root belongs to the operator, not to the root the container runs as.
            os.chown(self.root, 1000, 1000)
        settings = override_settings(BACKUP_ROOT=str(self.root))
        settings.enable()
        self.addCleanup(settings.disable)

    def run_command(self, *args, failing=()):
        out = StringIO()
        database = backups.database_settings()['name']
        with (
            mock.patch.dict(os.environ, {'PGDATABASE_FOR_TEST': database}),
            mock.patch(RUN_TARGET, side_effect=fake_run(failing)),
        ):
            call_command('backup_database', *args, stdout=out)
        return json.loads(out.getvalue())

    def test_creates_a_verified_dump_with_checksum_receipt_and_marker(self):
        with mock.patch.dict(os.environ, {'CATALOG_BUNDLE_REVISION': 'a' * 40, 'CATALOG_IMAGE': 'img@sha256:' + 'b' * 64}):
            result = self.run_command()

        archive = self.root / result['archive']
        self.assertTrue(archive.name.startswith('{0}-'.format(archive.name.split('-')[0])))
        self.assertEqual(archive.read_bytes(), b'PGDMP fake custom dump')
        self.assertEqual(oct(archive.stat().st_mode & 0o777), '0o640')
        # Every file belongs to the backups root's owner, so the host-side operator can read them.
        root = self.root.stat()
        for name in (archive.name, archive.name + '.sha256', archive.name + '.json', backups.MARKER_NAME, backups.LOCK_NAME):
            created = (self.root / name).stat()
            self.assertEqual((created.st_uid, created.st_gid), (root.st_uid, root.st_gid), name)
        self.assertEqual(result['sha256'], backups.sha256_file(archive))
        self.assertTrue(result['ok'])
        self.assertTrue(result['verified'])
        self.assertEqual(result['revision'], 'a' * 40)
        checksum = (self.root / (archive.name + '.sha256')).read_text()
        self.assertEqual(checksum, '{0}  {1}\n'.format(result['sha256'], archive.name))
        receipt = json.loads((self.root / (archive.name + '.json')).read_text())
        self.assertEqual(receipt['archive'], archive.name)
        self.assertEqual(receipt['counts'], {'citation_publication': 0, 'primary_publication': 0})
        self.assertEqual(receipt['postgres']['pg_dump'], 'pg_dump (PostgreSQL) 18.6')
        self.assertIn('server', receipt['postgres'])
        self.assertEqual(receipt['image'], 'img@sha256:' + 'b' * 64)
        self.assertFalse(receipt['scheduled'])
        marker = (self.root / backups.MARKER_NAME).read_text()
        self.assertEqual(marker, 'timestamp={0}\narchive={1}\n'.format(receipt['created_at'], archive.name))
        self.assertEqual(sorted(path.name for path in self.root.iterdir() if path.name.startswith('.')), ['.backup.lock'])

    def test_scheduled_flag_is_recorded(self):
        result = self.run_command('--scheduled')
        receipt = json.loads((self.root / (result['archive'] + '.json')).read_text())
        self.assertTrue(result['scheduled'])
        self.assertTrue(receipt['scheduled'])

    def write_old_backup(self, name, age):
        created = datetime.now(timezone.utc) - age
        (self.root / name).write_bytes(b'old')
        (self.root / (name + '.sha256')).write_text('0' * 64 + '  ' + name + '\n')
        (self.root / (name + '.json')).write_text(json.dumps({
            'schema_version': backups.SCHEMA_VERSION,
            'archive': name,
            'created_at': backups.iso(created.replace(microsecond=0)),
        }))

    def test_prunes_dumps_older_than_the_retention_period_only(self):
        self.write_old_backup('comses_catalog-20200101T000000Z.dump', timedelta(days=31))
        self.write_old_backup('comses_catalog-20260101T000000Z.dump', timedelta(days=29))

        result = self.run_command()

        self.assertEqual(result['pruned'], ['comses_catalog-20200101T000000Z.dump'])
        remaining = sorted(path.name for path in self.root.glob('*.dump'))
        self.assertEqual(remaining, sorted(['comses_catalog-20260101T000000Z.dump', result['archive']]))
        self.assertFalse((self.root / 'comses_catalog-20200101T000000Z.dump.json').exists())

    def test_a_failed_verification_leaves_no_dump_marker_or_partial_file(self):
        with self.assertLogs(COMMAND_LOGGER, 'ERROR'), self.assertRaisesRegex(CommandError, 'pg_restore failed'):
            self.run_command(failing=('pg_restore',))

        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['.backup.lock'])

    def test_a_failure_while_gathering_the_receipt_leaves_no_dump(self):
        with (
            mock.patch('catalog.core.backups.postgres_versions', side_effect=backups.BackupError('pg_dump --version failed')),
            self.assertLogs(COMMAND_LOGGER, 'ERROR'),
            self.assertRaisesRegex(CommandError, 'pg_dump --version failed'),
        ):
            self.run_command()

        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['.backup.lock'])

    def test_a_failure_while_writing_the_receipt_removes_the_renamed_dump(self):
        def failing_marker(path, text):
            if path.name == backups.MARKER_NAME:
                raise OSError('disk full')
            return original(path, text)

        original = backups.atomic_write
        with (
            mock.patch('catalog.core.backups.atomic_write', side_effect=failing_marker),
            self.assertRaises(OSError),
        ):
            with mock.patch.dict(os.environ, {'PGDATABASE_FOR_TEST': backups.database_settings()['name']}), \
                    mock.patch(RUN_TARGET, side_effect=fake_run()):
                backups.create_backup()

        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['.backup.lock'])

    def test_two_backups_in_the_same_second_never_share_a_file(self):
        first = self.run_command()
        second = self.run_command()
        self.assertNotEqual(first['archive'], second['archive'])
        self.assertTrue((self.root / first['archive']).exists())
        self.assertTrue((self.root / (first['archive'] + '.json')).exists())

    def test_an_existing_archive_is_never_replaced(self):
        first = self.run_command()
        with (
            mock.patch('catalog.core.backups.archive_name', return_value=first['archive']),
            self.assertLogs(COMMAND_LOGGER, 'ERROR'),
            self.assertRaisesRegex(CommandError, 'refusing to replace an existing backup'),
        ):
            self.run_command()
        self.assertTrue((self.root / first['archive']).exists())
        self.assertTrue((self.root / (first['archive'] + '.json')).exists())
        self.assertIn('archive={0}'.format(first['archive']), (self.root / backups.MARKER_NAME).read_text())

    def test_a_discarded_attempt_leaves_the_marker_on_the_previous_backup(self):
        first = self.run_command()
        with (
            mock.patch('catalog.core.backups.fsync_directory', side_effect=OSError('disk full')),
            self.assertLogs(COMMAND_LOGGER, 'ERROR'),
            self.assertRaises(CommandError),
        ):
            self.run_command()
        self.assertIn('archive={0}'.format(first['archive']), (self.root / backups.MARKER_NAME).read_text())
        self.assertEqual(sorted(p.name for p in self.root.glob('*.dump')), [first['archive']])

    def test_a_running_backup_operation_blocks_a_new_one_unless_waiting(self):
        self.root.mkdir(exist_ok=True)
        with (self.root / backups.LOCK_NAME).open('a+') as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            with self.assertLogs(COMMAND_LOGGER, 'ERROR'), self.assertRaisesRegex(CommandError, 'another backup operation is running'):
                self.run_command()
            self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['.backup.lock'])
