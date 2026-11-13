"""Exercise release publication with local GitHub and registry stand-ins."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64
MANIFEST = json.dumps({"image": f"ghcr.io/comses/catalog@{DIGEST}"})
TOOL = '''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps([tool, *args]) + "\\n")
if tool == "gh" and args[0] == "api":
    metadata = os.environ["RELEASE_METADATA"]
    if metadata.startswith("HTTP "):
        print("gh: " + metadata, file=sys.stderr)
        sys.exit(1)
    print(metadata)
elif tool == "gh" and args[:2] == ["release", "download"]:
    destination = Path(args[args.index("--dir") + 1]) / "release-manifest.json"
    destination.write_text(os.environ["EXISTING_MANIFEST"])
elif tool == "docker" and args[:3] == ["buildx", "imagetools", "inspect"]:
    promoted = Path(os.environ["CALL_LOG"] + ".promoted")
    digest = os.environ["PROMOTED_DIGEST"] if promoted.exists() else os.environ["ALIAS_DIGEST"]
    if digest == "missing":
        print("ERROR: " + args[3] + ": not found", file=sys.stderr)
        sys.exit(1)
    if digest == "denied":
        print("ERROR: unauthorized", file=sys.stderr)
        sys.exit(1)
    print(digest)
elif tool == "docker" and args[:3] == ["buildx", "imagetools", "create"]:
    Path(os.environ["CALL_LOG"] + ".promoted").touch()
    sys.exit(int(os.environ["PROMOTION_STATUS"]))
elif tool == "gh" and args[:2] in (["release", "create"], ["release", "upload"], ["release", "edit"]):
    pass
else:
    raise RuntimeError("unexpected call: " + repr([tool, *args]))
'''


class PublishReleaseTestCase(unittest.TestCase):
    def run_publish(self, **overrides: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "release-manifest.json").write_text(MANIFEST)
            binaries = work / "bin"
            binaries.mkdir()
            for name in ("gh", "docker"):
                command = binaries / name
                command.write_text(TOOL)
                command.chmod(0o755)
            log = work / "calls.jsonl"
            log.touch()
            env = {
                **os.environ,
                "PATH": f"{binaries}:{os.environ['PATH']}",
                "CALL_LOG": str(log),
                "GITHUB_REPOSITORY": "CoMSES/Catalog",
                "TAG": "v2026.11",
                "RELEASE_METADATA": "HTTP 404",
                "EXISTING_MANIFEST": MANIFEST,
                "ALIAS_DIGEST": "missing",
                "PROMOTED_DIGEST": DIGEST,
                "PROMOTION_STATUS": "0",
                **overrides,
            }
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/publish-release.sh")],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls

    def assert_no_publication(self, calls: list[list[str]]) -> None:
        for call in calls:
            self.assertNotEqual(call[:4], ["docker", "buildx", "imagetools", "create"])
            self.assertNotIn(call[:3], [["gh", "release", verb] for verb in ("create", "upload", "edit")])

    def test_new_release_promotes_before_creating_release_with_asset(self) -> None:
        result, calls = self.run_publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [call[:4] for call in calls[1:-1]],
            [
                ["docker", "buildx", "imagetools", "inspect"],
                ["docker", "buildx", "imagetools", "create"],
                ["docker", "buildx", "imagetools", "inspect"],
            ],
        )
        self.assertIn("ghcr.io/comses/catalog:v2026.11", calls[2])
        self.assertIn("--prefer-index=false", calls[2])
        self.assertEqual(calls[2][-1], f"ghcr.io/comses/catalog@{DIGEST}")
        self.assertEqual(calls[-1][:3], ["gh", "release", "create"])
        self.assertIn("--verify-tag", calls[-1])
        self.assertIn("release-manifest.json#Release manifest", calls[-1])

    def test_identical_published_release_is_a_noop(self) -> None:
        result, calls = self.run_publish(RELEASE_METADATA="false\tfalse\t1\ttrue", ALIAS_DIGEST=DIGEST)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_no_publication(calls)
        self.assertEqual(sum(call[:2] == ["gh", "api"] for call in calls), 1)

    def test_draft_with_matching_asset_is_published(self) -> None:
        result, calls = self.run_publish(RELEASE_METADATA="true\tfalse\t1\tfalse", ALIAS_DIGEST=DIGEST)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1][:3], ["gh", "release", "edit"])
        self.assertIn("--draft=false", calls[-1])

    def test_interrupted_draft_uploads_missing_asset_before_publication(self) -> None:
        result, calls = self.run_publish(RELEASE_METADATA="true\tfalse\t0\tfalse", ALIAS_DIGEST=DIGEST)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [call[:3] for call in calls[-2:]],
            [["gh", "release", "upload"], ["gh", "release", "edit"]],
        )

    def test_conflicting_manifest_stops_before_alias_changes(self) -> None:
        result, calls = self.run_publish(RELEASE_METADATA="false\tfalse\t1\tfalse", EXISTING_MANIFEST="different")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different manifest", result.stderr)
        self.assert_no_publication(calls)

    def test_invalid_existing_releases_are_rejected_before_publication(self) -> None:
        for metadata in ("false\ttrue\t1\tfalse", "true\tfalse\t2\tfalse", "false\tfalse\t0\ttrue"):
            with self.subTest(metadata=metadata):
                result, calls = self.run_publish(RELEASE_METADATA=metadata)
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_publication(calls)

    def test_github_errors_are_not_treated_as_missing_releases(self) -> None:
        for status in ("HTTP 403", "HTTP 500"):
            with self.subTest(status=status):
                result, calls = self.run_publish(RELEASE_METADATA=status)
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_publication(calls)

    def test_conflicting_alias_and_registry_errors_prevent_publication(self) -> None:
        for digest in ("sha256:" + "b" * 64, "denied"):
            with self.subTest(digest=digest):
                result, calls = self.run_publish(ALIAS_DIGEST=digest)
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_publication(calls)

    def test_promotion_failure_and_digest_mismatch_prevent_github_publication(self) -> None:
        for overrides in ({"PROMOTION_STATUS": "1"}, {"PROMOTED_DIGEST": "sha256:" + "b" * 64}):
            with self.subTest(overrides=overrides):
                result, calls = self.run_publish(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:2] == ["gh", "release"] for call in calls))

    def test_manifest_from_another_repository_prevents_publication(self) -> None:
        result, calls = self.run_publish(GITHUB_REPOSITORY="someone/else")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_publication(calls)
