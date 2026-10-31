from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import release_manifest  # noqa: E402

IMAGE = "ghcr.io/comses/catalog@sha256:" + "a" * 64
POSTGRES = "postgres:18@sha256:" + "2" * 64
SEARCH = "docker.elastic.co/elasticsearch/elasticsearch:8.19.21@sha256:" + "4" * 64


class ReleaseManifestTestCase(unittest.TestCase):
    def test_base_image_is_the_first_build_stage(self) -> None:
        dockerfile = "# syntax\nFROM python:3.12-slim@sha256:abc AS base\nFROM base AS final\n"

        self.assertEqual(release_manifest.base_image(dockerfile), "python:3.12-slim@sha256:abc")

    def test_support_images_exclude_the_application_and_merge_environments(self) -> None:
        images = release_manifest.support_images([[IMAGE, POSTGRES, SEARCH], [IMAGE, SEARCH, POSTGRES]], IMAGE)

        self.assertEqual(images, sorted([POSTGRES, SEARCH]))
        self.assertEqual(
            release_manifest.search_backend(images),
            "docker.elastic.co/elasticsearch/elasticsearch:8.19.21",
        )
        with self.assertRaises(ValueError):
            release_manifest.search_backend([POSTGRES])

    def test_build_facts_come_from_the_image_not_the_clock(self) -> None:
        inspected = "2026-10-27T06:24:38.999495867Z\thttps://example.invalid/runs/1"
        with mock.patch.object(release_manifest, "output", return_value=inspected) as output:
            facts = release_manifest.build_facts(IMAGE)

        self.assertEqual(facts, {"workflow_run": "https://example.invalid/runs/1", "built_at": "2026-10-27T06:24:38Z"})
        self.assertEqual(output.call_args.args[0][:4], ["docker", "image", "inspect", IMAGE])
        for unlabeled in ("2026-10-27T06:24:38Z\t", "2026-10-27T06:24:38Z\tunknown"):
            with (
                self.subTest(unlabeled=unlabeled),
                mock.patch.object(release_manifest, "output", return_value=unlabeled),
                self.assertRaisesRegex(ValueError, "build-run label"),
            ):
                release_manifest.build_facts(IMAGE)

    def test_written_manifest_passes_the_controller_validation_and_is_reproducible(self) -> None:
        revision = "b" * 40

        def output(command: list[str], **_kwargs: object) -> str:
            return {"HEAD": revision, "HEAD:citation": "c" * 40}[command[-1]]

        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(release_manifest, "output", side_effect=output),
            mock.patch.object(release_manifest, "rendered_images", return_value=[IMAGE, POSTGRES, SEARCH]),
            mock.patch.object(
                release_manifest,
                "dependency_versions",
                return_value={"python": "3.12.13", "packages": {"Django": "5.2.17"}, "uv_lock_sha256": "0" * 64},
            ),
            mock.patch.object(
                release_manifest,
                "build_facts",
                return_value={"workflow_run": "https://example.invalid/runs/1", "built_at": "2026-10-27T06:24:38Z"},
            ),
        ):
            destination = Path(directory) / "release-manifest.json"
            manifest = release_manifest.write(IMAGE, destination)
            first = destination.read_bytes()
            self.assertEqual(json.loads(first), manifest)
            self.assertEqual(release_manifest.check(destination, revision)["image"], IMAGE)
            with self.assertRaisesRegex(ValueError, "not " + "d" * 40):
                release_manifest.check(destination, "d" * 40)
            release_manifest.write(IMAGE, destination)
            self.assertEqual(destination.read_bytes(), first)

        self.assertEqual(manifest["support_images"], sorted([POSTGRES, SEARCH]))
        self.assertTrue(manifest["base_image"].startswith("python:3.12-slim@sha256:"))
        self.assertEqual(manifest["build"]["workflow_run"], "https://example.invalid/runs/1")


if __name__ == "__main__":
    unittest.main()
