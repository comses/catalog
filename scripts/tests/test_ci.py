"""Exercise publication decisions without contacting GitHub or a Docker daemon."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'ci.sh'
REVISION = 'b' * 40
DIGEST = 'sha256:' + 'a' * 64
IMAGE = 'ghcr.io/comses/catalog'
FAKE_TOOL = r'''
import json
import os
import sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['TRACE'], 'a') as trace:
    trace.write(json.dumps([name, *args]) + '\n')
scenario = os.environ['SCENARIO']
revision = 'b' * 40
digest = 'sha256:' + 'a' * 64
if name == 'git':
    print('c' * 40 if args[-1] == 'HEAD:citation' else revision)
elif name == 'gh':
    if args[1].startswith('users/'):
        print(os.environ.get('OWNER_TYPE', 'Organization'))
    elif scenario == 'missing':
        print('gh: Not Found (HTTP 404)', file=sys.stderr)
        sys.exit(1)
    elif scenario == 'denied':
        print('gh: Forbidden (HTTP 403)', file=sys.stderr)
        sys.exit(1)
    else:
        print('sha-' + revision)
elif name == 'make':
    print('sha-' + revision + ': digest: ' + digest + ' size: 123')
elif name == 'docker' and args[:2] == ['image', 'inspect']:
    if 'RepoDigests' in args[-1]:
        if scenario != 'no-digest':
            print('ghcr.io/comses/catalog@' + digest)
    elif 'citation-revision' in args[-1]:
        print('c' * 40)
    else:
        print('wrong' if scenario == 'wrong-revision' else revision)
'''


class PublishTest(unittest.TestCase):
    def publish(self, scenario, owner_type='Organization'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('git', 'gh', 'docker', 'make', 'python3'):
                tool = root / name
                tool.write_text(f'#!{sys.executable}\n' + FAKE_TOOL)
                tool.chmod(0o755)
            trace = root / 'trace'
            result = subprocess.run(
                ['bash', str(SCRIPT), 'publish'], cwd=root, capture_output=True, text=True,
                env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
                     'CATALOG_IMAGE': f'{IMAGE}:sha-{REVISION}', 'TRACE': str(trace),
                     'SCENARIO': scenario, 'OWNER_TYPE': owner_type},
            )
            commands = [json.loads(line) for line in trace.read_text().splitlines()]
            return result, commands

    def test_missing_package_publishes_and_manifests_the_digest(self):
        result, commands = self.publish('missing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['make', 'image-push'], commands)
        self.assertIn(['docker', 'pull', f'{IMAGE}@{DIGEST}'], commands)
        self.assertIn(['python3', 'scripts/release_manifest.py', 'write', '--image',
                       f'{IMAGE}@{DIGEST}', '--output', 'release-manifest.json'], commands)

    def test_existing_image_is_reused_for_organizations_and_users(self):
        for owner_type, scope in [('Organization', 'orgs'), ('User', 'users')]:
            with self.subTest(owner_type=owner_type):
                result, commands = self.publish('existing', owner_type)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(any(f'{scope}/comses/packages/container/catalog/versions' in c
                                    for c in commands))
                self.assertNotIn(['make', 'image-push'], commands)
                self.assertIn(['docker', 'pull', f'{IMAGE}@{DIGEST}'], commands)

    def test_registry_errors_and_invalid_images_never_write_a_manifest(self):
        for scenario in ('denied', 'no-digest', 'wrong-revision'):
            with self.subTest(scenario=scenario):
                result, commands = self.publish(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] in ('make', 'python3') for c in commands))
