"""Verified PostgreSQL backups in the application's backups root.

Each backup is a custom-format dump checked with ``pg_restore --list``, with a
SHA-256 file, a JSON receipt and the ``last-successful-backup`` marker that the
CoMSES infrastructure reads. Every operation holds ``.backup.lock``, the same
lock the release controller holds on the host.
"""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings
from django.db import connection

SCHEMA_VERSION = 1
RETENTION = timedelta(days=30)
LOCK_NAME = '.backup.lock'
MARKER_NAME = 'last-successful-backup'


class BackupError(RuntimeError):
    pass


class BackupBusy(BackupError):
    pass


def backups_root():
    return Path(settings.BACKUP_ROOT)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def archive_name(database, moment):
    """Unique per backup: two backups in the same second must never share a file."""
    return '{0}-{1:%Y%m%dT%H%M%S%f}Z.dump'.format(database, moment)


def iso(moment):
    return moment.isoformat().replace('+00:00', 'Z')


@contextmanager
def backup_lock(root, wait=False):
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_NAME
    created = not lock_path.exists()
    with lock_path.open('a+') as lock_file:
        if created:
            adopt(lock_path)
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            if not wait:
                raise BackupBusy('another backup operation is running') from error
            print('waiting for another backup operation to finish', file=sys.stderr, flush=True)
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


def database_settings():
    db = settings.DATABASES['default']
    return {
        'name': db['NAME'],
        'command': ['--host', str(db['HOST']), '--port', str(db['PORT']), '--username', db['USER']],
        'env': {**os.environ, 'PGPASSWORD': db['PASSWORD']},
    }


def run(command, env, **kwargs):
    kwargs.setdefault('stdin', subprocess.DEVNULL)
    try:
        return subprocess.run(command, env=env, check=True, **kwargs)
    except subprocess.CalledProcessError as error:
        raise BackupError('{0} failed with exit code {1}'.format(command[0], error.returncode)) from error


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def adopt(path):
    """Files belong to the backups root's owner (the operator on hosts), readable by its group; this runs as root."""
    root = path.parent.stat()
    os.chown(path, root.st_uid, root.st_gid)
    os.chmod(path, 0o640)


def atomic_write(path, text):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.' + path.name + '.', delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    adopt(Path(handle.name))
    os.replace(handle.name, path)


def publication_counts():
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.citation_publication') IS NOT NULL")
        if not cursor.fetchone()[0]:
            return {'citation_publication': 0, 'primary_publication': 0}
        cursor.execute('SELECT count(*), count(*) FILTER (WHERE is_primary) FROM citation_publication')
        total, primary = cursor.fetchone()
    return {'citation_publication': total, 'primary_publication': primary}


def postgres_versions(env):
    with connection.cursor() as cursor:
        cursor.execute('SHOW server_version')
        server = cursor.fetchone()[0]
    versions = {'server': server}
    for tool in ('pg_dump', 'pg_restore'):
        versions[tool] = run([tool, '--version'], env, capture_output=True, text=True).stdout.strip()
    return versions


def write_dump(temporary, db):
    with temporary.open('wb') as destination:
        run(['pg_dump', *db['command'], '--format', 'custom', '--no-owner', '--no-privileges', db['name']],
            db['env'], stdout=destination)
        destination.flush()
        os.fsync(destination.fileno())
    with temporary.open('rb') as source:
        run(['pg_restore', '--list'], db['env'], stdin=source, stdout=subprocess.DEVNULL)


def read_receipts(root):
    receipts = []
    for path in sorted(root.glob('*.dump.json'), reverse=True):
        try:
            receipt = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(receipt, dict) and receipt.get('schema_version') == SCHEMA_VERSION:
            receipts.append(receipt)
    return receipts


def prune(root, now, keep):
    """Removes dumps older than the retention period, never the one just written."""
    cutoff = now - RETENTION
    pruned = []
    for receipt in read_receipts(root):
        archive = receipt['archive']
        if archive == keep or datetime.fromisoformat(receipt['created_at'].replace('Z', '+00:00')) >= cutoff:
            continue
        for suffix in ('', '.sha256', '.json'):
            (root / (archive + suffix)).unlink(missing_ok=True)
        pruned.append(archive)
    return pruned


def create_backup(*, wait=False, scheduled=False, revision=None, image=None):
    root = backups_root()
    db = database_settings()
    with backup_lock(root, wait=wait):
        started = datetime.now(timezone.utc)
        now = started.replace(microsecond=0)
        name = archive_name(db['name'], started)
        target = root / name
        if target.exists():
            raise BackupError('refusing to replace an existing backup: {0}'.format(target))
        temporary = root / '.{0}.partial'.format(name)
        # Everything the receipt needs is gathered before the dump gets its final name, so a
        # failure never leaves a dump without a receipt (which prune would never see).
        try:
            write_dump(temporary, db)
            adopt(temporary)
            receipt = {
                'schema_version': SCHEMA_VERSION,
                'kind': 'backup',
                'created_at': iso(now),
                'archive': name,
                'bytes': temporary.stat().st_size,
                'sha256': sha256_file(temporary),
                'database': db['name'],
                'counts': publication_counts(),
                'postgres': postgres_versions(db['env']),
                'scheduled': scheduled,
                'revision': revision,
                'image': image,
            }
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        # Only this attempt's files are removed on failure (the name is unique, so they cannot be another backup's),
        # and the marker goes back to the backup it named before.
        marker = root / MARKER_NAME
        previous_marker = marker.read_text(encoding='utf-8') if marker.exists() else None
        try:
            atomic_write(root / (name + '.sha256'), '{0}  {1}\n'.format(receipt['sha256'], name))
            atomic_write(root / (name + '.json'), json.dumps(receipt, indent=2, sort_keys=True) + '\n')
            atomic_write(marker, 'timestamp={0}\narchive={1}\n'.format(receipt['created_at'], name))
            fsync_directory(root)
        except BaseException:
            for suffix in ('', '.sha256', '.json'):
                (root / (name + suffix)).unlink(missing_ok=True)
            if previous_marker is None:
                marker.unlink(missing_ok=True)
            else:
                atomic_write(marker, previous_marker)
            raise
        pruned = prune(root, now, keep=name)
    return {
        'phase': 'backup',
        'ok': True,
        'archive': name,
        'sha256': receipt['sha256'],
        'bytes': receipt['bytes'],
        'verified': True,
        'verification': 'pg_restore --list',
        'completed_at': receipt['created_at'],
        'counts': receipt['counts'],
        'scheduled': scheduled,
        'revision': revision,
        'image': image,
        'pruned': pruned,
    }
