import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'dev-restore.sh'


class DevelopmentRestoreTest(unittest.TestCase):
    def run_restore(self, valid):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            for name in ('config.sh', 'deploy.sh'):
                (root / 'scripts' / name).write_text('exit 0\n')
            dump = root / 'input.dump'
            dump.write_bytes(b'invalid archive')
            docker = root / 'docker'
            docker.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$TRACE"
if [[ "$*" == *"pg_restore --list"* ]]; then
    exit "$PREFLIGHT_EXIT"
fi
''')
            docker.chmod(0o755)
            trace = root / 'trace'
            result = subprocess.run(['bash', str(SCRIPT)], cwd=root, capture_output=True, text=True,
                                    env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'],
                                         'DUMP': str(dump), 'CONFIRM': 'comses_catalog',
                                         'TRACE': str(trace), 'PREFLIGHT_EXIT': '0' if valid else '2'})
            return result, trace.read_text().splitlines()

    def test_invalid_archive_does_not_stop_or_replace_database(self):
        result, commands = self.run_restore(False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any('pg_restore --list' in c for c in commands))
        for command in commands:
            self.assertNotIn('stop django', command)
            self.assertNotIn('dropdb', command)
            self.assertNotIn('createdb', command)

    def test_valid_archive_is_checked_before_destructive_operations(self):
        result, commands = self.run_restore(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        preflight = next(i for i, c in enumerate(commands) if 'pg_restore --list' in c)
        stop = next(i for i, c in enumerate(commands) if 'stop django' in c)
        drop = next(i for i, c in enumerate(commands) if 'dropdb' in c)
        self.assertLess(preflight, stop)
        self.assertLess(stop, drop)
