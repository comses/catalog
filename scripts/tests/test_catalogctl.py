from __future__ import annotations

import contextlib
import fcntl
import getpass
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import catalogctl  # noqa: E402

IMAGE = "ghcr.io/comses/catalog@sha256:" + "a" * 64
REVISION = "b" * 40
CITATION = "c" * 40
SUPPORT_IMAGES = ["nginx:1.28.3@sha256:" + "1" * 64, "postgres:18@sha256:" + "2" * 64]
RELEASE_ID = f"{REVISION[:12]}-{'a' * 12}"


class RunnerTestCase(unittest.TestCase):
    def test_run_uses_devnull_when_no_input_is_supplied(self) -> None:
        with mock.patch.object(subprocess, "run") as run:
            catalogctl.Runner().run(["example"])

        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_run_preserves_explicit_input(self) -> None:
        with mock.patch.object(subprocess, "run") as run:
            catalogctl.Runner().run(["example"], input_data="payload")

        self.assertIsNone(run.call_args.kwargs["stdin"])
        self.assertEqual(run.call_args.kwargs["input"], "payload")

    def test_uncaptured_output_goes_to_stderr_so_stdout_carries_only_the_result(self) -> None:
        with mock.patch.object(subprocess, "run") as run:
            catalogctl.Runner().run(["example"], capture=False)

        self.assertIs(run.call_args.kwargs["stdout"], sys.stderr)

    def test_to_file_uses_devnull(self) -> None:
        destination = mock.Mock()
        with mock.patch.object(subprocess, "run") as run:
            catalogctl.Runner().to_file(["example"], destination)

        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(run.call_args.kwargs["stdout"], destination)


class ControllerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.layout = catalogctl.Layout(root / "docker", root / "backups")
        self.controller = catalogctl.Controller(ROOT, self.layout)
        # Activation asks Docker who publishes the HTTP port; tests that need it override this.
        publishers = mock.patch.object(self.controller, "foreign_http_publishers", return_value=[])
        publishers.start()
        self.addCleanup(publishers.stop)

    def provision(self, host_id: str = "staging") -> None:
        self.controller.configure(host_id)

    def write_state(self, path: Path, **values: object) -> dict[str, Any]:
        state = {"schema_version": catalogctl.SCHEMA_VERSION, **values}
        catalogctl.atomic_json(path, state)
        return state

    def make_release(self, name: str) -> dict[str, Any]:
        release_dir = self.layout.releases / name
        release_dir.mkdir(parents=True, exist_ok=True)
        compose = release_dir / "docker-compose.yml"
        compose.write_text(f"name: comses-catalog\n# {name}\nservices: {{}}\n", encoding="utf-8")
        return {
            "release_dir": str(release_dir),
            "compose_file": str(compose),
            "compose_sha256": catalogctl.sha256_file(compose),
            "bundle_sha256": catalogctl.sha256_tree(release_dir, excluded={"docker-compose.yml"}),
        }

    def write_candidate(self, **overrides: object) -> dict[str, Any]:
        values: dict[str, object] = {
            "host_id": "staging",
            "operation_id": "operation-1",
            "release_id": RELEASE_ID,
            "image": IMAGE,
            "bundle_revision": REVISION,
            "citation_revision": CITATION,
            "manifest_sha256": "f" * 64,
            **self.make_release("candidate"),
            "support_images": SUPPORT_IMAGES,
            "created_at": catalogctl.utc_now(),
            "restore_status": "succeeded",
            "drain_status": "not_required",
            "migration_status": "unmigrated",
            "data_rebuild_status": "pending",
            "search_aliases_after": {"publication": "publication-new"},
        }
        values.update(overrides)
        return self.write_state(self.layout.candidate, **values)

    def write_active(self, name: str = "old", **overrides: object) -> dict[str, Any]:
        values: dict[str, object] = {
            "host_id": "staging",
            "release_id": f"{name}-release",
            "image": "ghcr.io/comses/catalog@sha256:" + "f" * 64,
            "bundle_revision": "e" * 40,
            **self.make_release(name),
            "support_images": SUPPORT_IMAGES,
            "search_aliases": {},
        }
        values.update(overrides)
        active = self.write_state(self.layout.active, **values)
        self.layout.canonical_compose.parent.mkdir(parents=True, exist_ok=True)
        self.layout.canonical_compose.write_bytes(Path(str(values["compose_file"])).read_bytes())
        return active

    def write_manifest(self, name: str = "manifest.json", **overrides: object) -> tuple[Path, dict[str, Any]]:
        manifest: dict[str, Any] = {
            "schema_version": catalogctl.MANIFEST_SCHEMA_VERSION,
            "kind": catalogctl.MANIFEST_KIND,
            "catalog_revision": REVISION,
            "citation_revision": CITATION,
            "image": IMAGE,
            "support_images": SUPPORT_IMAGES,
            "search_backend": "docker.elastic.co/elasticsearch/elasticsearch:8.19.21",
            "base_image": "python:3.12-slim@sha256:" + "3" * 64,
            "dependencies": {"python": "3.12.13"},
            "build": {"workflow_run": "https://example.invalid/runs/1"},
        }
        manifest.update(overrides)
        path = Path(self.temporary.name) / name
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path, manifest

    @contextlib.contextmanager
    def prepare_environment(
        self,
        *,
        rendered_support: list[str] | None = None,
        citation: str = CITATION,
    ) -> Generator[mock.MagicMock, None, None]:
        support = SUPPORT_IMAGES if rendered_support is None else rendered_support
        self.render_environment: dict[str, str] = {}

        def archive(_revision: str, release_dir: Path) -> str:
            release_dir.mkdir(parents=True, exist_ok=True)
            return catalogctl.sha256_tree(release_dir)

        def render(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[:2] == ["bash", "scripts/compose.sh"]:
                environment = kwargs["env"]
                assert isinstance(environment, dict)
                self.render_environment = dict(environment)
                Path(command[-1]).write_text("name: comses-catalog\nservices: {}\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        def compose(_path: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            output = "\n".join([IMAGE, *support]) + "\n" if arguments == ("config", "--images") else ""
            return subprocess.CompletedProcess(list(arguments), 0, output, "")

        with (
            mock.patch.object(self.controller, "host_check"),
            mock.patch.object(self.controller, "require_clean_revision", return_value=citation),
            mock.patch.object(self.controller, "pull_and_verify_image") as pull,
            mock.patch.object(self.controller, "archive_release", side_effect=archive),
            mock.patch.object(self.controller.runner, "run", side_effect=render),
            mock.patch.object(self.controller, "compose", side_effect=compose),
        ):
            yield pull

    # Validation

    def test_digest_validation_rejects_tags_and_malformed_digests(self) -> None:
        self.assertEqual(catalogctl.validate_image(IMAGE), IMAGE)
        for invalid in (
            "ghcr.io/comses/catalog:latest",
            "ghcr.io/comses/catalog:sha-deadbeef",
            "ghcr.io/comses/catalog@sha256:abc",
            "ghcr.io/comses/catalog@sha256:" + "A" * 64,
        ):
            with self.subTest(invalid=invalid), self.assertRaises(catalogctl.CatalogError):
                catalogctl.validate_image(invalid)

    def test_manifest_loads_with_the_digest_of_its_exact_bytes(self) -> None:
        path, manifest = self.write_manifest()
        loaded, digest = catalogctl.load_manifest(path)

        self.assertEqual(loaded, manifest)
        self.assertEqual(digest, catalogctl.sha256_file(path))

    def test_manifest_validation_rejects_incomplete_or_mutable_releases(self) -> None:
        cases = {
            "schema": {"schema_version": 1},
            "kind": {"kind": "something-else"},
            "tag": {"image": "ghcr.io/comses/catalog:latest"},
            "revision": {"catalog_revision": "main"},
            "support": {"support_images": ["postgres:18"]},
            "empty support": {"support_images": []},
        }
        for name, overrides in cases.items():
            with self.subTest(name=name), self.assertRaises(catalogctl.CatalogError):
                catalogctl.load_manifest(self.write_manifest(f"{name}.json", **overrides)[0])
        path, manifest = self.write_manifest("missing.json")
        del manifest["search_backend"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(catalogctl.CatalogError, "missing: search_backend"):
            catalogctl.load_manifest(path)

    # Storage, configuration and host checks

    def test_storage_prepare_creates_owner_only_directories_and_refuses_root(self) -> None:
        result = self.controller.storage_prepare()

        for directory in (self.layout.secrets, self.layout.state, self.layout.releases, self.layout.shared / "mail", self.layout.reports):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700, directory)
        self.assertTrue(self.layout.backups.is_dir())
        self.assertEqual(result["operator"], getpass.getuser())
        with (
            mock.patch.object(os, "geteuid", return_value=0),
            self.assertRaisesRegex(catalogctl.CatalogError, "not root"),
        ):
            self.controller.storage_prepare()

    def test_storage_preflight_requires_the_prepared_layout_and_a_safe_backups_root(self) -> None:
        with self.assertRaisesRegex(catalogctl.CatalogError, "make storage-prepare"):
            self.controller.storage_preflight()
        self.controller.storage_prepare()
        self.assertTrue(self.controller.storage_preflight()["ok"])

        self.layout.backups.chmod(0o777)
        with self.assertRaisesRegex(catalogctl.CatalogError, "world-writable"):
            self.controller.storage_preflight()
        self.layout.backups.chmod(0o500)
        with self.assertRaisesRegex(catalogctl.CatalogError, "not writable"):
            self.controller.storage_preflight()
        self.layout.backups.chmod(0o700)
        self.layout.secrets.chmod(0o750)
        with self.assertRaisesRegex(catalogctl.CatalogError, "owner-only"):
            self.controller.storage_preflight()
        self.layout.secrets.chmod(0o700)
        elsewhere = Path(self.temporary.name) / "elsewhere"
        elsewhere.mkdir()
        self.layout.reports.rmdir()
        self.layout.reports.symlink_to(elsewhere)
        with self.assertRaisesRegex(catalogctl.CatalogError, "must not be a symlink"):
            self.controller.storage_preflight()

    def test_storage_preflight_on_a_host_requires_the_infrastructure_bind(self) -> None:
        self.controller.storage_prepare()
        self.layout.backups_bind.mkdir()
        mounts = {("--mountpoint", "/srv"): "/srv", ("-T",): "/srv"}

        def findmnt(command: list[str], **_kwargs: object) -> str:
            self.assertEqual(command[0], "findmnt")
            return mounts[("--mountpoint", "/srv")] if "--mountpoint" in command else mounts[("-T",)]

        with (
            mock.patch.object(catalogctl.layout, "HOST_DIR", self.layout.root),
            mock.patch.object(catalogctl.host, "CANONICAL_CHECKOUT", self.controller.root),
            mock.patch.object(self.controller, "command_output", side_effect=findmnt),
        ):
            with self.assertRaisesRegex(catalogctl.CatalogError, "not the infrastructure's bind"):
                self.controller.storage_preflight()
            bound = catalogctl.Controller(ROOT, catalogctl.Layout(self.layout.root, self.layout.backups_bind))
            with mock.patch.object(bound, "command_output", side_effect=findmnt):
                result = bound.storage_preflight()
            self.assertEqual(result["bind"], str(self.layout.backups_bind))
            mounts[("--mountpoint", "/srv")] = ""
            with self.assertRaisesRegex(catalogctl.CatalogError, "not a mountpoint"):
                self.controller.storage_preflight()

    def test_storage_preflight_verifies_the_kernel_limit_the_infrastructure_sets(self) -> None:
        self.controller.storage_prepare()
        limit = Path(self.temporary.name) / "max_map_count"
        limit.write_text("65530\n", encoding="utf-8")
        with (
            mock.patch.object(catalogctl.host, "MAX_MAP_COUNT_PATH", limit),
            self.assertRaisesRegex(catalogctl.CatalogError, "vm.max_map_count must be at least 262144"),
        ):
            self.controller.storage_preflight()

    def test_configure_creates_fixed_identity_and_does_not_rotate_secrets(self) -> None:
        self.provision()
        password = (self.layout.secrets / "postgres_password").read_bytes()
        config = (self.layout.secrets / "config.ini").read_bytes()

        self.provision()

        self.assertEqual((self.layout.secrets / "postgres_password").read_bytes(), password)
        self.assertEqual((self.layout.secrets / "config.ini").read_bytes(), config)
        self.assertEqual(stat.S_IMODE((self.layout.secrets / "config.ini").stat().st_mode), 0o600)
        self.assertEqual(self.controller.host().host_id, "staging")
        self.assertEqual(self.controller.host().project_name, "comses-catalog")
        with self.assertRaisesRegex(catalogctl.CatalogError, "identity is immutable"):
            self.controller.configure("prod")

        identity = self.layout.host_env.read_text(encoding="utf-8")
        self.layout.host_env.write_text(identity.replace("=comses-catalog", "=catalog"), encoding="utf-8")
        with self.assertRaisesRegex(catalogctl.CatalogError, "COMPOSE_PROJECT_NAME must be comses-catalog"):
            self.controller.host()

    def test_configure_imports_the_settings_of_an_existing_installation(self) -> None:
        old = Path(self.temporary.name) / "old-config.ini"
        old.write_text(
            "[db]\nNAME=comses_catalog\nPASSWORD=old-database-password\n\n"
            "[solr]\nCORE_NAME=catalog_core\n\n"
            "[django]\nAUDIT_ACCOUNT_USERNAME=auditor\nRAVEN_PRIVATE_DSN=https://key@sentry.example/1\n"
            "RAVEN_PUBLIC_DSN=https://public@sentry.example/1\nSECRET_KEY=old-secret-key\n\n"
            "[email]\nEMAIL_HOST=smtp.example.org\nEMAIL_PORT=2525\nEMAIL_HOST_USER=mailer\n"
            "EMAIL_HOST_PASSWORD=p%%ss\nEMAIL_SUBJECT_PREFIX=\"[catalog]\"\n",
            encoding="utf-8",
        )

        result = self.controller.configure("prod", import_config=old)

        config = (self.layout.secrets / "config.ini").read_text(encoding="utf-8")
        self.assertIn("EMAIL_HOST_PASSWORD = p%%ss", config)
        self.assertIn("RAVEN_PRIVATE_DSN = https://key@sentry.example/1", config)
        self.assertIn("SECRET_KEY = old-secret-key", config)
        self.assertNotIn("old-database-password", config)
        self.assertNotIn("[solr]", config)
        self.assertNotIn("p%%ss", json.dumps(result))
        self.assertIn("email.EMAIL_HOST_PASSWORD", result["imported"])
        self.assertNotIn("db.PASSWORD", result["imported"])
        with (
            mock.patch.object(self.controller, "command_output", return_value=""),
            mock.patch.object(catalogctl.host, "MAX_MAP_COUNT_PATH", Path(self.temporary.name) / "absent"),
        ):
            self.controller.host_check()

    def test_configure_imports_settings_only_into_new_secrets(self) -> None:
        self.provision()
        old = Path(self.temporary.name) / "old-config.ini"
        old.write_text("[email]\nEMAIL_HOST=smtp.example.org\n", encoding="utf-8")

        with self.assertRaisesRegex(catalogctl.CatalogError, "secrets already exist"):
            self.controller.configure("staging", import_config=old)

    def test_configure_never_changes_the_infrastructure_owned_backups_root(self) -> None:
        self.layout.backups.mkdir(parents=True)
        self.layout.backups.chmod(0o2775)

        self.provision()

        self.assertEqual(stat.S_IMODE(self.layout.backups.stat().st_mode), 0o2775)

    def test_default_layout_keeps_host_state_on_the_persistent_volume(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            layout = catalogctl.Layout.from_environment()

        self.assertTrue(layout.system)
        self.assertFalse(self.layout.system)
        self.assertEqual(layout.secrets, Path("/srv/apps/comses-catalog/docker/secrets"))
        self.assertEqual(layout.host_env, Path("/srv/apps/comses-catalog/docker/deploy/host.env"))
        self.assertEqual(layout.canonical_compose, Path("/srv/apps/comses-catalog/docker/deploy/runtime/docker-compose.yml"))
        self.assertEqual(layout.backups, Path("/srv/backups/comses_model_catalog"))
        self.assertEqual(layout.backups_bind, Path("/srv/apps/comses-catalog/docker/deploy/shared/backups"))
        self.assertEqual(layout.lock, Path("/srv/backups/comses_model_catalog/.backup.lock"))
        self.assertEqual(layout.backup_marker, Path("/srv/backups/comses_model_catalog/last-successful-backup"))

    def test_configure_sets_an_explicit_http_bind_and_keeps_it_on_later_runs(self) -> None:
        self.provision()
        self.assertEqual(self.controller.host().http_bind, "127.0.0.1:80")

        self.controller.configure("staging", "192.168.254.123:80")
        self.assertEqual(self.controller.host().http_bind, "192.168.254.123:80")

        self.provision()
        self.assertEqual(self.controller.host().http_bind, "192.168.254.123:80")
        with self.assertRaisesRegex(catalogctl.CatalogError, "HTTP_BIND must be an explicit"):
            self.controller.configure("staging", "80")
        self.assertEqual(self.controller.host().http_bind, "192.168.254.123:80")

    def test_host_check_requires_the_canonical_checkout_for_system_paths(self) -> None:
        self.provision()
        with (
            mock.patch.object(catalogctl.layout, "HOST_DIR", self.layout.root),
            self.assertRaisesRegex(catalogctl.CatalogError, "canonical checkout"),
        ):
            self.controller.host_check()

    def test_host_requires_an_explicit_http_bind_address(self) -> None:
        self.provision()
        cases = (
            ("127.0.0.1:80", True),
            ("0.0.0.0:80", True),
            ("[::1]:8080", True),
            ("80", False),
            ("localhost:80", False),
            ("::1:80", False),
            ("127.0.0.1:0", False),
        )
        for bind, accepted in cases:
            with self.subTest(bind=bind):
                lines = [
                    f"CATALOG_HTTP_BIND={bind}" if line.startswith("CATALOG_HTTP_BIND=") else line
                    for line in self.layout.host_env.read_text(encoding="utf-8").splitlines()
                ]
                self.layout.host_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
                if accepted:
                    self.assertEqual(self.controller.host().http_bind, bind)
                else:
                    with self.assertRaisesRegex(catalogctl.CatalogError, "explicit <address>:<port>"):
                        self.controller.host()

    def test_host_rejects_writable_identity_file(self) -> None:
        self.provision()
        self.layout.host_env.chmod(0o666)
        with self.assertRaisesRegex(catalogctl.CatalogError, "unsafe permissions"):
            self.controller.host()

    def test_host_check_requires_tarfile_extraction_filters(self) -> None:
        self.provision()

        with (
            mock.patch.object(catalogctl.host, "tarfile", SimpleNamespace()),
            self.assertRaisesRegex(catalogctl.CatalogError, "3.10.12"),
        ):
            self.controller.host_check()

    def test_host_rejects_mismatched_database_password_files(self) -> None:
        self.provision()
        (self.layout.secrets / "postgres_password").write_text("different\n", encoding="utf-8")

        with self.assertRaisesRegex(catalogctl.CatalogError, "database passwords differ"):
            self.controller.host_check()

    def test_production_host_requires_complete_smtp_configuration(self) -> None:
        self.provision("prod")

        with self.assertRaisesRegex(
            catalogctl.CatalogError,
            "email.EMAIL_HOST_USER, email.EMAIL_HOST_PASSWORD",
        ):
            self.controller.host_check()

    # Locking

    def test_inherited_lock_keeps_other_processes_out_between_phases(self) -> None:
        self.controller.storage_prepare()
        with self.layout.lock.open('a+') as inherited:
            fcntl.flock(inherited, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code = (
                'from pathlib import Path; from catalogctl import Controller, Layout; '
                f'c = Controller(Path({str(ROOT)!r}), Layout(Path({str(self.layout.root)!r}), '
                f'Path({str(self.layout.backups)!r}))); '
                'context = c.locked(); context.__enter__(); context.__exit__(None, None, None)'
            )
            subprocess.run(
                [sys.executable, '-c', code], check=True, timeout=3,
                env={**os.environ, 'PYTHONPATH': str(ROOT / 'scripts'),
                     'CATALOG_LOCK_FD': str(inherited.fileno())},
                pass_fds=(inherited.fileno(),), capture_output=True,
            )
            with self.layout.lock.open('r') as competing:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_inherited_lock_must_name_the_host_backup_lock(self) -> None:
        self.controller.storage_prepare()
        with (self.layout.backups / 'wrong.lock').open('a+') as unrelated:
            with mock.patch.dict(os.environ, CATALOG_LOCK_FD=str(unrelated.fileno())):
                with self.assertRaisesRegex(catalogctl.CatalogError, 'inherited lock'):
                    with self.controller.locked():
                        self.fail('accepted a different lock file')

    def test_nested_phases_take_the_host_lock_once(self) -> None:
        self.controller.storage_prepare()
        operations: list[int] = []
        with mock.patch.object(fcntl, "flock", side_effect=lambda _file, operation: operations.append(operation)):
            with self.controller.locked():
                with self.controller.locked():
                    pass

        self.assertEqual(operations, [fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN])
        self.assertEqual(catalogctl.core._LOCK_DEPTH, {})

    def test_a_busy_lock_is_reported_before_waiting(self) -> None:
        self.controller.storage_prepare()
        operations: list[int] = []

        def flock(_file: object, operation: int) -> None:
            operations.append(operation)
            if operation == fcntl.LOCK_EX | fcntl.LOCK_NB:
                raise BlockingIOError

        with (
            mock.patch.object(fcntl, "flock", side_effect=flock),
            mock.patch.object(catalogctl.core, "log") as log,
        ):
            with self.controller.locked():
                pass

        self.assertEqual(operations, [fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_EX, fcntl.LOCK_UN])
        self.assertIn("Waiting for", log.call_args.args[0])

    def test_a_lock_file_the_application_created_is_usable_without_write_access(self) -> None:
        self.layout.backups.mkdir(parents=True)
        self.layout.lock.touch()
        self.layout.lock.chmod(0o444)
        operations: list[int] = []
        with mock.patch.object(fcntl, "flock", side_effect=lambda _file, operation: operations.append(operation)):
            with self.controller.locked():
                pass

        self.assertEqual(operations, [fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN])
        with self.assertRaisesRegex(catalogctl.CatalogError, "backups root .* is missing"):
            with catalogctl.Controller(ROOT, catalogctl.Layout(self.layout.root, self.layout.root / "absent")).locked():
                pass

    def test_the_lock_is_released_when_a_phase_fails(self) -> None:
        self.controller.storage_prepare()
        with self.assertRaises(RuntimeError), self.controller.locked():
            raise RuntimeError("phase failed")

        self.assertEqual(catalogctl.core._LOCK_DEPTH, {})
        with self.controller.locked():
            pass

    # prepare

    def test_prepare_records_the_manifest_and_renders_the_host_project(self) -> None:
        self.provision()
        manifest_path, manifest = self.write_manifest()
        with self.prepare_environment() as pull:
            result = self.controller.prepare(manifest_path)

        pull.assert_called_once_with(IMAGE, REVISION, CITATION)
        self.assertEqual(self.render_environment["COMPOSE_PROJECT_NAME"], "comses-catalog")
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["manifest"], manifest)
        self.assertEqual(candidate["manifest_sha256"], catalogctl.sha256_file(manifest_path))
        self.assertEqual(candidate["release_id"], RELEASE_ID)
        self.assertEqual(candidate["restore_status"], "pending")
        self.assertEqual(candidate["drain_status"], "not_required")
        self.assertEqual(result["release_id"], RELEASE_ID)
        self.assertTrue(result["restore_required"])

    def test_prepare_refuses_support_images_that_differ_from_the_manifest(self) -> None:
        self.provision()
        manifest_path, _manifest = self.write_manifest()
        with (
            self.prepare_environment(rendered_support=[SUPPORT_IMAGES[0]]),
            self.assertRaisesRegex(catalogctl.CatalogError, "differ from the release manifest"),
        ):
            self.controller.prepare(manifest_path)
        self.assertFalse(self.layout.candidate.exists())

    def test_prepare_refuses_a_gitlink_that_differs_from_the_manifest(self) -> None:
        self.provision()
        manifest_path, _manifest = self.write_manifest()
        with (
            self.prepare_environment(citation="d" * 40) as pull,
            self.assertRaisesRegex(catalogctl.CatalogError, "manifest's Citation revision"),
        ):
            self.controller.prepare(manifest_path)
        pull.assert_not_called()

    def test_prepare_is_idempotent_for_the_same_manifest(self) -> None:
        self.provision()
        manifest_path, _manifest = self.write_manifest()
        with self.prepare_environment():
            self.controller.prepare(manifest_path)
        with self.prepare_environment() as pull:
            result = self.controller.prepare(manifest_path)

        self.assertTrue(result["already"])
        pull.assert_not_called()

    def test_prepare_of_the_active_release_does_nothing(self) -> None:
        self.provision()
        self.write_active(release_id=RELEASE_ID)
        manifest_path, _manifest = self.write_manifest()
        with self.prepare_environment() as pull:
            result = self.controller.prepare(manifest_path)

        self.assertTrue(result["already_active"])
        pull.assert_not_called()
        self.assertFalse(self.layout.candidate.exists())

    def test_prepare_refuses_the_rollback_release(self) -> None:
        self.provision()
        self.write_active()
        self.write_state(self.layout.rollback, release_id=RELEASE_ID)
        manifest_path, _manifest = self.write_manifest()
        with (
            self.prepare_environment() as pull,
            self.assertRaisesRegex(catalogctl.CatalogError, "use make rollback"),
        ):
            self.controller.prepare(manifest_path)
        pull.assert_not_called()

    def test_first_prepare_refuses_an_existing_compose_runtime(self) -> None:
        self.provision()
        manifest_path, _manifest = self.write_manifest()
        queries: list[list[str]] = []

        def output(command: list[str], **_kwargs: object) -> str:
            queries.append(command)
            if command[:2] == ["docker", "ps"]:
                return "comses-catalog-nginx-1\ncomses-catalog-db-1\n"
            if command[:3] == ["docker", "volume", "ls"]:
                return "comses-catalog_esdata8\n"
            return ""

        with (
            mock.patch.object(self.controller, "host_check"),
            mock.patch.object(self.controller, "command_output", side_effect=output),
            mock.patch.object(self.controller, "pull_and_verify_image") as pull,
            self.assertRaisesRegex(
                catalogctl.CatalogError,
                "already exist: comses-catalog-db-1, comses-catalog-nginx-1, comses-catalog_esdata8;",
            ),
        ):
            self.controller.prepare(manifest_path)

        pull.assert_not_called()
        self.assertFalse(self.layout.candidate.exists())
        self.assertEqual(len(queries), 2)
        for query in queries:
            self.assertIn("label=com.docker.compose.project=comses-catalog", query)

    def test_prepare_on_an_active_host_skips_the_empty_runtime_check(self) -> None:
        self.provision()
        self.write_active()
        manifest_path, _manifest = self.write_manifest()
        with (
            self.prepare_environment(),
            mock.patch.object(self.controller, "require_empty_runtime") as require_empty,
        ):
            result = self.controller.prepare(manifest_path)

        require_empty.assert_not_called()
        self.assertFalse(result["restore_required"])
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["drain_status"], "pending")

    def test_prepare_refuses_support_image_changes_on_an_active_host(self) -> None:
        self.provision()
        self.write_active(support_images=["postgres:17@sha256:" + "9" * 64])
        manifest_path, _manifest = self.write_manifest()
        with (
            self.prepare_environment(),
            self.assertRaisesRegex(catalogctl.CatalogError, "separate, reviewed transitions"),
        ):
            self.controller.prepare(manifest_path)

    def test_a_locked_candidate_cannot_be_replaced(self) -> None:
        self.provision()
        manifest_path, _manifest = self.write_manifest()
        for state in (
            {"migration_status": "failed"},
            {"migration_status": "in_progress"},
            {"restore_status": "in_progress"},
            {"migration_status": "succeeded", "data_rebuild_status": "failed"},
        ):
            with self.subTest(state=state):
                self.write_candidate(**state)
                with (
                    self.prepare_environment(),
                    self.assertRaisesRegex(catalogctl.CatalogError, "locked by restore, migration, or rebuild"),
                ):
                    self.controller.prepare(manifest_path)

    def test_a_replacement_candidate_keeps_what_happened_to_the_database_and_writers(self) -> None:
        self.provision()
        self.write_active()
        self.write_candidate(
            manifest_sha256="0" * 64,
            restore_status="not_required",
            drain_status="drained",
            drained_at="2026-10-26T10:00:00Z",
            migration_applied=True,
            migration_started_at="2026-10-26T10:01:00Z",
        )
        manifest_path, _manifest = self.write_manifest()
        with self.prepare_environment():
            self.controller.prepare(manifest_path)

        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["manifest_sha256"], catalogctl.sha256_file(manifest_path))
        self.assertEqual(candidate["drain_status"], "drained")
        self.assertIs(candidate["migration_applied"], True)
        self.assertEqual(candidate["migration_started_at"], "2026-10-26T10:01:00Z")
        with (
            mock.patch.object(self.controller, "compose") as compose,
            self.assertRaisesRegex(catalogctl.CatalogError, "migrations were applied"),
        ):
            self.controller.start()
        compose.assert_not_called()

    def test_a_migrated_candidate_can_be_replaced_once_its_failed_rebuild_was_retried(self) -> None:
        # A rebuild or activation that fails after the migrations ran is fixed forward:
        # candidate-retry clears the failure, then prepare brings the fixed release.
        self.provision()
        self.write_candidate(
            manifest_sha256="0" * 64,
            restore_status="succeeded",
            migration_status="succeeded",
            migration_applied=True,
            migration_started_at="2026-10-27T20:03:34Z",
            data_rebuild_status="pending",
        )
        manifest_path, _manifest = self.write_manifest()
        with self.prepare_environment():
            self.controller.prepare(manifest_path)

        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["manifest_sha256"], catalogctl.sha256_file(manifest_path))
        self.assertEqual(candidate["restore_status"], "succeeded")
        self.assertEqual(candidate["migration_status"], "unmigrated")
        self.assertIs(candidate["migration_applied"], True)
        self.assertEqual(candidate["migration_started_at"], "2026-10-27T20:03:34Z")
        self.assertEqual(candidate["data_rebuild_status"], "pending")

    def test_a_fresh_host_candidate_can_be_replaced_after_its_restore(self) -> None:
        self.provision()
        self.write_candidate(
            manifest_sha256="0" * 64,
            restore_status="succeeded",
            restore_receipt="/receipts/restore.json",
            restore_sha256="d" * 64,
            migration_applied=True,
        )
        manifest_path, _manifest = self.write_manifest()
        with (
            self.prepare_environment(),
            mock.patch.object(self.controller, "require_empty_runtime") as require_empty,
        ):
            result = self.controller.prepare(manifest_path)

        require_empty.assert_not_called()
        self.assertFalse(result["restore_required"])
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["restore_status"], "succeeded")
        self.assertEqual(candidate["restore_receipt"], "/receipts/restore.json")
        self.assertIs(candidate["migration_applied"], True)

    def test_candidate_requires_the_citation_checkout_from_the_catalog_gitlink(self) -> None:
        with (
            mock.patch.object(
                self.controller,
                "command_output",
                side_effect=[REVISION, "", "", CITATION, "d" * 40],
            ),
            self.assertRaisesRegex(catalogctl.CatalogError, "does not match the Catalog gitlink"),
        ):
            self.controller.require_clean_revision(REVISION)

    def test_a_checkout_at_another_commit_names_the_fix(self) -> None:
        with (
            mock.patch.object(self.controller, "command_output", return_value="d" * 40),
            self.assertRaisesRegex(catalogctl.CatalogError, f"git checkout --detach {REVISION}"),
        ):
            self.controller.require_clean_revision(REVISION)

    def test_an_image_built_from_other_sources_is_rejected(self) -> None:
        for labels, message in (
            ({"org.opencontainers.image.revision": "d" * 40}, f"built from {'d' * 40}"),
            (
                {"org.opencontainers.image.revision": REVISION, "org.comses.catalog.citation-revision": "d" * 40},
                "does not match the Catalog gitlink",
            ),
        ):
            with (
                self.subTest(message=message),
                mock.patch.object(self.controller.runner, "run"),
                mock.patch.object(self.controller, "command_output", return_value=json.dumps(labels)),
                self.assertRaisesRegex(catalogctl.CatalogError, message),
            ):
                self.controller.pull_and_verify_image(IMAGE, REVISION, CITATION)

    # backup and backup-status

    backup_count = 0

    def write_backup(self, release: dict[str, Any], *, created_at: datetime | None = None) -> dict[str, Any]:
        """Stands in for the application's backup_database command: dump, checksum, receipt and marker."""
        self.backup_count += 1
        created = (created_at or datetime.now(timezone.utc)).replace(microsecond=0) + timedelta(seconds=self.backup_count)
        archive = f"comses_catalog-{created:%Y%m%dT%H%M%SZ}.dump"
        self.layout.backups.mkdir(parents=True, exist_ok=True)
        artifact = self.layout.backups / archive
        artifact.write_bytes(b"valid custom dump")
        receipt = {
            "schema_version": catalogctl.SCHEMA_VERSION,
            "kind": "backup",
            "created_at": catalogctl.utc_now() if created_at is None else created.isoformat().replace("+00:00", "Z"),
            "archive": archive,
            "bytes": artifact.stat().st_size,
            "sha256": catalogctl.sha256_file(artifact),
            "database": "comses_catalog",
            "counts": {"citation_publication": 10, "primary_publication": 3},
            "postgres": {"server": "18.6", "pg_dump": "18.6", "pg_restore": "18.6"},
            "scheduled": False,
            "revision": release["bundle_revision"],
            "image": release["image"],
        }
        (self.layout.backups / f"{archive}.sha256").write_text(f"{receipt['sha256']}  {archive}\n", encoding="utf-8")
        catalogctl.atomic_json(self.layout.backups / f"{archive}.json", receipt)
        self.layout.backup_marker.write_text(f"timestamp={receipt['created_at']}\narchive={archive}\n", encoding="utf-8")
        return receipt

    def run_backup(self, release: dict[str, Any] | None = None) -> dict[str, Any]:
        active = release or catalogctl.require_json(self.layout.active)

        def backup_database(_compose: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            receipt = self.write_backup(active)
            output = json.dumps({"phase": "backup", "ok": True, "archive": receipt["archive"], "sha256": receipt["sha256"]})
            return subprocess.CompletedProcess(list(arguments), 0, f"Container db Running\n{output}\n", "")

        with mock.patch.object(self.controller, "manage", side_effect=backup_database) as manage:
            result = self.controller.backup()
        self.assertEqual(manage.call_args.args[1:], ("backup_database", "--wait"))
        self.assertTrue(manage.call_args.kwargs["capture"])
        return result

    def test_backup_delegates_to_the_application_and_verifies_its_receipt(self) -> None:
        self.provision()
        active = self.write_active()

        result = self.run_backup()

        artifact = Path(result["path"])
        self.assertEqual(artifact.parent, self.layout.backups)
        receipt = catalogctl.require_json(self.layout.backups / f"{artifact.name}.json")
        self.assertEqual(receipt["sha256"], catalogctl.sha256_file(artifact))
        self.assertEqual(
            {key: result[key] for key in ("ok", "archive", "sha256", "release_id")},
            {"ok": True, "archive": artifact.name, "sha256": receipt["sha256"], "release_id": active["release_id"]},
        )
        self.assertEqual(self.controller.backup_marker_archive(), artifact.name)

    def test_backup_refuses_a_receipt_for_another_release_or_a_changed_artifact(self) -> None:
        self.provision()
        active = self.write_active()
        other = {**active, "image": "ghcr.io/comses/catalog@sha256:" + "9" * 64}
        with self.assertRaisesRegex(catalogctl.CatalogError, "not the active release"):
            self.run_backup(other)

        def tampered(_compose: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            receipt = self.write_backup(active)
            (self.layout.backups / receipt["archive"]).write_bytes(b"changed after the receipt")
            return subprocess.CompletedProcess(list(arguments), 0, json.dumps({"archive": receipt["archive"]}), "")

        with (
            mock.patch.object(self.controller, "manage", side_effect=tampered),
            self.assertRaisesRegex(catalogctl.CatalogError, "does not match its receipt"),
        ):
            self.controller.backup()

    def test_backup_requires_a_json_result_from_the_application(self) -> None:
        self.provision()
        self.write_active()
        with (
            mock.patch.object(self.controller, "manage", return_value=subprocess.CompletedProcess([], 0, "no result", "")),
            self.assertRaisesRegex(catalogctl.CatalogError, "printed no JSON result"),
        ):
            self.controller.backup()

    def test_backup_status_verifies_and_ages_the_latest_backup(self) -> None:
        self.provision()
        self.assertFalse(self.controller.backup_status()["ok"])
        self.write_active()
        backup = self.run_backup()

        current = self.controller.backup_status(max_age=3600)
        self.assertTrue(current["ok"])
        self.assertEqual(current["archive"], backup["archive"])
        self.assertTrue(current["verified"])
        self.assertTrue(current["marker_matches"])
        self.assertEqual(current["release_id"], catalogctl.release_id("e" * 40, "ghcr.io/comses/catalog@sha256:" + "f" * 64))

        receipt_path = self.layout.backups / f"{backup['archive']}.json"
        receipt = catalogctl.require_json(receipt_path)
        receipt["created_at"] = "2026-01-01T00:00:00Z"
        catalogctl.atomic_json(receipt_path, receipt)
        self.assertFalse(self.controller.backup_status(max_age=86400)["ok"])

        self.layout.backup_marker.write_text("timestamp=x\narchive=other.dump\n", encoding="utf-8")
        self.assertFalse(self.controller.backup_status()["ok"])
        self.layout.backup_marker.write_text(f"timestamp=x\narchive={backup['archive']}\n", encoding="utf-8")

        Path(backup["path"]).write_bytes(b"corrupted")
        stale = self.controller.backup_status()
        self.assertFalse(stale["ok"])
        self.assertFalse(stale["verified"])

    # restore

    def test_plain_restore_rejects_database_level_commands_before_starting_services(self) -> None:
        dump = Path(self.temporary.name) / "unsafe.sql"
        dump.write_text("CREATE DATABASE other;\n", encoding="utf-8")
        with (
            mock.patch.object(self.controller, "compose") as compose,
            self.assertRaisesRegex(catalogctl.CatalogError, "database-level commands"),
        ):
            self.controller.restore(dump, "comses_catalog")
        compose.assert_not_called()

    def test_restore_rejects_a_mismatched_adjacent_checksum(self) -> None:
        dump = Path(self.temporary.name) / "catalog.sql"
        dump.write_text("SELECT 1;\n", encoding="utf-8")
        dump.with_suffix(".sql.sha256").write_text(f"{'0' * 64}  {dump.name}\n", encoding="utf-8")
        with (
            mock.patch.object(self.controller, "compose") as compose,
            self.assertRaisesRegex(catalogctl.CatalogError, "checksum does not match"),
        ):
            self.controller.restore(dump, "comses_catalog")
        compose.assert_not_called()

    def test_restore_refuses_a_database_that_already_has_publications(self) -> None:
        self.provision()
        self.write_candidate(restore_status="pending")
        dump = Path(self.temporary.name) / "catalog.sql"
        dump.write_text("SELECT 1;\n", encoding="utf-8")

        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "db_identity", return_value=("catalog", "comses_catalog")),
            mock.patch.object(
                self.controller,
                "database_counts",
                return_value={"citation_publication": 5, "primary_publication": 2},
            ),
            mock.patch.object(self.controller, "psql") as psql,
            self.assertRaisesRegex(catalogctl.CatalogError, "already contains 5 publications"),
        ):
            self.controller.restore(dump, "comses_catalog")

        psql.assert_not_called()
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["restore_status"], "pending")

    # drain and migrate

    def test_drain_stops_the_scheduler_then_django_of_the_active_release(self) -> None:
        self.provision()
        active = self.write_active()
        self.write_candidate(restore_status="not_required", drain_status="pending")
        calls: list[tuple[str, ...]] = []

        def compose(path: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(str(path), active["compose_file"])
            calls.append(arguments)
            return subprocess.CompletedProcess(list(arguments), 0, "", "")

        with mock.patch.object(self.controller, "compose", side_effect=compose):
            result = self.controller.drain()
            again = self.controller.drain()

        drained = [
            ("stop", "--timeout", "120", "scheduler"),
            ("stop", "--timeout", "120", "django"),
            ("rm", "--force", "scheduler", "django"),
        ]
        # The containers are removed so a daemon restart cannot revive them, and a repeated
        # drain stops them again because nothing else proves they are still down.
        self.assertEqual(calls, drained + drained)
        self.assertEqual(result["stopped"], ["scheduler", "django"])
        self.assertTrue(again["already"])
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["drain_status"], "drained")

    def test_drain_on_a_fresh_host_has_nothing_to_stop(self) -> None:
        self.provision()
        self.write_candidate()
        with mock.patch.object(self.controller, "compose") as compose:
            result = self.controller.drain()

        compose.assert_not_called()
        self.assertEqual(result["stopped"], [])

    def test_migrate_requires_confirmation_and_runs_ordered_checks(self) -> None:
        self.provision()
        self.write_candidate()
        with self.assertRaisesRegex(catalogctl.CatalogError, "CONFIRM_SCHEMA_MIGRATION"):
            self.controller.migrate(False)

        calls: list[tuple[str, ...]] = []
        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "manage", side_effect=self.migration_commands(calls)),
        ):
            result = self.controller.migrate(True)
            again = self.controller.migrate(True)

        self.assertEqual(
            calls,
            [
                ("makemigrations", "--check", "--dry-run"),
                ("migrate", "--plan"),
                ("migrate", "--check"),
                ("migrate", "--noinput"),
                ("migrate", "--check"),
            ],
        )
        self.assertEqual(result["plan"], ["planned migration"])
        self.assertTrue(again["already"])
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["migration_status"], "succeeded")
        self.assertEqual(candidate["migration_plan"], ["planned migration"])
        self.assertIs(candidate["migration_applied"], True)

    def test_migrate_without_pending_migrations_leaves_the_schema_untouched(self) -> None:
        self.provision()
        self.write_candidate()
        calls: list[tuple[str, ...]] = []
        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "manage", side_effect=self.migration_commands(calls, pending=False)),
        ):
            self.controller.migrate(True)

        self.assertNotIn(("migrate", "--noinput"), calls)
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["migration_status"], "succeeded")
        self.assertIs(candidate["migration_applied"], False)

    @staticmethod
    def migration_commands(
        calls: list[tuple[str, ...]],
        *,
        pending: bool = True,
        failing: tuple[str, ...] = (),
    ) -> Any:
        # The first `migrate --check` reports whether migrations are pending, as Django does.
        probed: list[bool] = []

        def manage(_compose: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(arguments)
            if arguments == failing:
                raise catalogctl.CatalogError("boom")
            if arguments == ("migrate", "--check") and not probed:
                probed.append(True)
                if pending:
                    raise catalogctl.CatalogError("unapplied migrations")
            output = "planned migration\n" if arguments == ("migrate", "--plan") else ""
            return subprocess.CompletedProcess(list(arguments), 0, output, "")

        return manage

    def test_migrate_on_an_active_host_names_the_backup_it_relied_on(self) -> None:
        self.provision()
        active = self.write_active()
        receipt = self.write_backup(active)
        self.write_candidate(restore_status="not_required", drain_status="drained")
        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "manage", side_effect=self.migration_commands([])),
        ):
            result = self.controller.migrate(True)

        self.assertEqual(result["backup"], receipt["archive"])
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["migration_status"], "succeeded")

    def test_migrate_on_an_active_host_requires_drained_writers(self) -> None:
        self.provision()
        self.write_active()
        self.write_candidate(restore_status="not_required", drain_status="pending")
        with (
            mock.patch.object(self.controller, "compose") as compose,
            self.assertRaisesRegex(catalogctl.CatalogError, "make drain"),
        ):
            self.controller.migrate(True)
        compose.assert_not_called()

    def test_migrate_reports_whether_a_failure_changed_the_database(self) -> None:
        for failing, message, applied in (
            (("makemigrations", "--check", "--dry-run"), "make start restores the previous release", False),
            (("migrate", "--noinput"), "may be partly migrated", True),
        ):
            with self.subTest(failing=failing):
                self.provision()
                self.write_candidate()
                with (
                    mock.patch.object(self.controller, "compose"),
                    mock.patch.object(self.controller, "manage", side_effect=self.migration_commands([], failing=failing)),
                    self.assertRaisesRegex(catalogctl.CatalogError, message),
                ):
                    self.controller.migrate(True)
                candidate = catalogctl.require_json(self.layout.candidate)
                self.assertEqual(candidate["migration_status"], "failed")
                self.assertIs(candidate["migration_applied"], applied)

    def test_a_retried_migration_keeps_an_earlier_partial_migration_on_record(self) -> None:
        self.provision()
        self.write_candidate(migration_applied=True)

        def manage(_compose: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise catalogctl.CatalogError("check failed")

        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "manage", side_effect=manage),
            self.assertRaisesRegex(catalogctl.CatalogError, "may be partly migrated"),
        ):
            self.controller.migrate(True)
        self.assertIs(catalogctl.require_json(self.layout.candidate)["migration_applied"], True)

    def test_migration_backup_must_predate_any_earlier_migration_attempt(self) -> None:
        self.provision()
        active = self.write_active()
        receipt = self.write_backup(active)
        # A newer, valid backup of another release must not count for this one.
        self.write_backup({**active, "image": "ghcr.io/comses/catalog@sha256:" + "9" * 64})

        self.assertEqual(self.controller.latest_valid_backup(active)["archive"], receipt["archive"])
        with self.assertRaisesRegex(catalogctl.CatalogError, "before any earlier migration attempt"):
            self.controller.latest_valid_backup(active, before=receipt["created_at"])

    # rebuild

    def test_rebuild_validates_search_and_records_new_aliases(self) -> None:
        self.provision()
        self.write_candidate(migration_status="succeeded")
        old_aliases = {"publication": "publication-old"}
        new_aliases = {"publication": "publication-new"}
        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "manage") as manage,
            mock.patch.object(self.controller, "alias_targets", side_effect=[old_aliases, new_aliases]),
        ):
            result = self.controller.rebuild()
            again = self.controller.rebuild()

        self.assertEqual(
            [call.args[1:] for call in manage.call_args_list],
            [
                ("rebuild_es_index",),
                ("validate_search_indexes",),
                ("populate_visualization_cache", "--clear"),
            ],
        )
        self.assertEqual(result["aliases"], new_aliases)
        self.assertTrue(again["already"])
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["data_rebuild_status"], "succeeded")
        self.assertEqual(candidate["search_aliases_before"], old_aliases)
        self.assertEqual(candidate["search_aliases_after"], new_aliases)

    def test_alias_snapshot_includes_model_documentation(self) -> None:
        response = {
            "model_documentation-20260920t120000z": {
                "aliases": {"model_documentation": {}}
            },
            "unmanaged-index": {"aliases": {"unmanaged": {}}},
        }
        with mock.patch.object(
            self.controller,
            "compose",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ):
            aliases = self.controller.alias_targets(Path("docker-compose.yml"))

        self.assertEqual(
            aliases,
            {"model_documentation": "model_documentation-20260920t120000z"},
        )

    def test_candidate_retry_requires_confirmation_and_only_resets_failed_stage(self) -> None:
        self.provision()
        self.write_candidate(
            migration_status="succeeded",
            data_rebuild_status="failed",
            data_rebuild_failed_at=catalogctl.utc_now(),
            data_rebuild_error="index failed",
            search_aliases_before={"publication": "publication-old"},
        )
        with self.assertRaisesRegex(catalogctl.CatalogError, "CONFIRM_CANDIDATE_RETRY"):
            self.controller.candidate_retry(False)

        events: list[object] = []
        with (
            mock.patch.object(self.controller, "compose", side_effect=lambda _path, *arguments, **_kwargs: events.append(arguments)),
            mock.patch.object(self.controller, "set_alias_targets", side_effect=lambda *_args: events.append("aliases")) as restore_aliases,
            mock.patch.object(
                self.controller,
                "alias_targets",
                return_value={"publication": "publication-old"},
            ),
        ):
            result = self.controller.candidate_retry(True)

        # A failed rebuild may have left Elasticsearch stopped; the retry brings it back before restoring aliases.
        self.assertEqual(events, [("up", "-d", "--wait", "db", "redis", "elasticsearch"), "aliases"])
        self.assertEqual(result["stage"], "rebuild")
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["migration_status"], "succeeded")
        self.assertEqual(candidate["data_rebuild_status"], "pending")
        self.assertNotIn("data_rebuild_error", candidate)
        restore_aliases.assert_called_once()
        history = json.loads(self.layout.history.read_text().strip())
        self.assertEqual(history["operation"], "candidate-retry")
        self.assertEqual(history["stage"], "rebuild")

    def test_candidate_retry_can_unlock_an_interrupted_restore(self) -> None:
        self.provision()
        self.write_candidate(
            restore_status="in_progress",
            restore_started_at=catalogctl.utc_now(),
        )

        self.controller.candidate_retry(True)

        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["restore_status"], "pending")
        history = json.loads(self.layout.history.read_text().strip())
        self.assertEqual(history["stage"], "restore")

    # activate, rollback, recovery

    def test_successful_activation_publishes_state_after_health_check(self) -> None:
        self.provision()
        candidate = self.write_candidate(
            migration_status="succeeded",
            data_rebuild_status="succeeded",
            search_aliases_after={"publication": "publication-new"},
        )
        events: list[str] = []

        def verify(_compose: Path) -> None:
            events.append("healthy")

        def publish(source: Path) -> None:
            self.assertEqual(events, ["healthy"])
            events.append("published")
            catalogctl.atomic_write(self.layout.canonical_compose, source.read_bytes())

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(
                self.controller,
                "alias_targets",
                return_value={"publication": "publication-new"},
            ),
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "verify_runtime", side_effect=verify),
            mock.patch.object(self.controller, "publish_runtime", side_effect=publish),
        ):
            result = self.controller.activate()
            again = self.controller.activate()

        active = catalogctl.require_json(self.layout.active)
        self.assertEqual(events, ["healthy", "published"])
        self.assertEqual(active["image"], candidate["image"])
        self.assertEqual(active["manifest_sha256"], candidate["manifest_sha256"])
        self.assertEqual(active["search_aliases"], {"publication": "publication-new"})
        self.assertEqual(result["release_id"], RELEASE_ID)
        self.assertTrue(again["already"])
        self.assertFalse(self.layout.candidate.exists())
        self.assertFalse(self.layout.journal.exists())
        history = json.loads(self.layout.history.read_text().strip())
        self.assertEqual(history["result"], "succeeded")

    def test_runtime_publication_copies_the_release_compose_file(self) -> None:
        release = self.make_release("published")
        compose = Path(release["compose_file"])

        self.controller.publish_runtime(compose)

        self.assertEqual(self.layout.canonical_compose.read_bytes(), compose.read_bytes())
        self.assertEqual(stat.S_IMODE(self.layout.canonical_compose.stat().st_mode), 0o600)

    def test_activation_switches_search_to_the_validated_generation_after_a_recovery(self) -> None:
        self.provision()
        self.write_active(search_aliases={"publication": "publication-old"})
        self.write_candidate(drain_status="drained",
            restore_status="not_required",
            migration_status="succeeded",
            data_rebuild_status="succeeded",
            search_aliases_after={"publication": "publication-new"},
        )
        events: list[object] = []

        def manage(_compose: Path, *arguments: str, **_kwargs: object) -> None:
            events.append(arguments)

        def set_aliases(_compose: Path, targets: dict[str, str]) -> None:
            self.assertTrue(self.layout.journal.exists())
            events.append(targets)

        def compose(_compose: Path, *arguments: str, **_kwargs: object) -> None:
            events.append(arguments[0])

        with (
            mock.patch.object(self.controller, "manage", side_effect=manage),
            mock.patch.object(self.controller, "set_alias_targets", side_effect=set_aliases),
            mock.patch.object(self.controller, "compose", side_effect=compose),
            mock.patch.object(self.controller, "verify_runtime"),
            mock.patch.object(self.controller, "publish_runtime"),
        ):
            self.controller.activate()

        self.assertEqual(
            events,
            [("migrate", "--check"), {"publication": "publication-new"}, ("validate_search_indexes",), "up"],
        )
        self.assertEqual(catalogctl.require_json(self.layout.active)["search_aliases"], {"publication": "publication-new"})

    def test_activation_waits_for_another_stack_to_release_the_http_port(self) -> None:
        self.provision()
        self.write_candidate(migration_status="succeeded", data_rebuild_status="succeeded")

        with (
            mock.patch.object(self.controller, "foreign_http_publishers", return_value=["catalog-nginx-1 (catalog)"]),
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(self.controller, "compose") as compose,
            self.assertRaisesRegex(catalogctl.CatalogError, "port 80 is published by catalog-nginx-1 \\(catalog\\)"),
        ):
            self.controller.activate()

        compose.assert_not_called()
        self.assertFalse(self.layout.journal.exists())
        self.assertTrue(self.layout.candidate.exists())

    def test_only_containers_of_other_projects_block_the_http_port(self) -> None:
        self.provision()
        listing = "catalog-nginx-1\tcatalog\ncomses-catalog-nginx-1\tcomses-catalog\nhand-started\t\n"
        with mock.patch.object(self.controller, "command_output", return_value=listing) as output:
            publishers = catalogctl.Controller.foreign_http_publishers(self.controller)

        self.assertEqual(publishers, ["catalog-nginx-1 (catalog)", "hand-started (no Compose project)"])
        self.assertIn("publish=80", output.call_args.args[0])

    def test_activation_without_a_validated_search_snapshot_changes_nothing(self) -> None:
        self.provision()
        self.write_candidate(migration_status="succeeded", data_rebuild_status="succeeded", search_aliases_after={})

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(self.controller, "compose") as compose,
            self.assertRaisesRegex(catalogctl.CatalogError, "no validated search alias snapshot"),
        ):
            self.controller.activate()

        compose.assert_not_called()
        self.assertTrue(self.layout.candidate.exists())
        self.assertFalse(self.layout.journal.exists())

    def test_failed_activation_recovers_previous_runtime_and_retains_candidate(self) -> None:
        self.provision()
        self.write_candidate(
            restore_status="not_required",
            drain_status="drained",
            migration_status="succeeded",
            migration_applied=False,
            data_rebuild_status="succeeded",
        )
        previous = self.write_active()
        self.write_state(self.layout.rollback, release_id="older-release")

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(
                self.controller,
                "alias_targets",
                return_value={"publication": "publication-new"},
            ),
            mock.patch.object(self.controller, "compose", side_effect=catalogctl.CatalogError("startup failed")),
            mock.patch.object(self.controller, "restore_runtime", return_value=True) as restore,
            self.assertRaisesRegex(catalogctl.CatalogError, "prior runtime recovered=True"),
        ):
            self.controller.activate()

        restore.assert_called_once()
        self.assertEqual(catalogctl.require_json(self.layout.active), previous)
        # The previous release's writers run again.
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["drain_status"], "pending")
        self.assertFalse(self.layout.journal.exists())
        history = json.loads(self.layout.history.read_text().strip())
        self.assertEqual(history["result"], "failed-recovered")

    def test_runtime_check_requests_through_nginx_and_never_tests_its_config(self) -> None:
        # nginx -t opens the listening sockets, so on a slow host it races the starting
        # master for port 80; the healthcheck and the request prove the runtime instead.
        self.provision()
        compose_file = self.layout.releases / "release" / "docker-compose.yml"
        with mock.patch.object(self.controller, "compose") as compose:
            self.controller.verify_runtime(compose_file)
        calls = [call.args[1:] for call in compose.call_args_list]
        self.assertEqual(
            calls,
            [("exec", "-T", "django", "curl", "-fsS", "-H", "Host: staging-catalog.comses.net", "http://nginx/")],
        )

    def test_failed_activation_after_migrations_keeps_the_site_down(self) -> None:
        self.provision()
        candidate = self.write_candidate(
            restore_status="not_required",
            drain_status="drained",
            migration_status="succeeded",
            migration_applied=True,
            data_rebuild_status="succeeded",
        )
        previous = self.write_active()
        calls: list[tuple[str, ...]] = []

        def compose(path: Path, *arguments: str, **_kwargs: object) -> None:
            calls.append(arguments)
            self.assertEqual(str(path), candidate["compose_file"])
            if arguments[0] == "up":
                raise catalogctl.CatalogError("startup failed")

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(self.controller, "alias_targets", return_value={}),
            mock.patch.object(self.controller, "compose", side_effect=compose),
            mock.patch.object(self.controller, "restore_runtime") as restore,
            self.assertRaisesRegex(catalogctl.CatalogError, "the site stays down"),
        ):
            self.controller.activate()

        restore.assert_not_called()
        self.assertEqual(
            [call for call in calls if call[0] == "stop"],
            [("stop", "--timeout", "120", "scheduler"), ("stop", "--timeout", "120", "django")],
        )
        self.assertEqual(catalogctl.require_json(self.layout.active), previous)
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["drain_status"], "drained")
        self.assertFalse(self.layout.journal.exists())
        history = json.loads(self.layout.history.read_text().strip())
        self.assertEqual(history["result"], "failed-kept-down")
        with self.assertRaisesRegex(catalogctl.CatalogError, "migrations were applied"):
            self.controller.start()

    def test_failed_activation_keeps_the_candidate_logs_for_diagnosis(self) -> None:
        self.provision()
        candidate = self.write_candidate(migration_status="succeeded", data_rebuild_status="succeeded")

        def compose(path: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(str(path), candidate["compose_file"])
            if arguments[0] == "logs":
                return subprocess.CompletedProcess(list(arguments), 0, "django-1  | boom\n", "")
            if arguments[0] == "up":
                raise catalogctl.CatalogError("startup failed")
            return subprocess.CompletedProcess(list(arguments), 0, "", "")

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(self.controller, "compose", side_effect=compose),
            self.assertRaisesRegex(catalogctl.CatalogError, "activation failed"),
        ):
            self.controller.activate()

        snapshot = next(self.layout.reports.glob(f"activation-{RELEASE_ID}-*.log"))
        self.assertEqual(snapshot.read_text(encoding="utf-8"), "django-1  | boom\n")

    def test_recover_of_an_interrupted_activation_follows_the_same_policy(self) -> None:
        for applied, outcome in ((True, "kept-down"), (False, "restored-previous")):
            with self.subTest(migration_applied=applied):
                self.provision()
                active = self.write_active()
                candidate = self.write_candidate(
                    restore_status="not_required",
                    drain_status="drained",
                    migration_status="succeeded",
                    migration_applied=applied,
                    data_rebuild_status="succeeded",
                )
                self.write_state(
                    self.layout.journal,
                    operation="deploy",
                    operation_id="operation-1",
                    checkpoint="candidate-started",
                    candidate=candidate,
                    previous_active=active,
                    previous_rollback=None,
                )
                with (
                    mock.patch.object(self.controller, "compose") as compose,
                    mock.patch.object(self.controller, "restore_runtime", return_value=True) as restore,
                ):
                    result = self.controller.recover()

                self.assertEqual(result["outcome"], outcome)
                self.assertEqual(restore.called, not applied)
                stopped = any(call.args[1] == "stop" for call in compose.call_args_list)
                self.assertEqual(stopped, applied)
                self.assertFalse(self.layout.journal.exists())
                self.assertEqual(catalogctl.require_json(self.layout.active), active)
                self.assertEqual(
                    catalogctl.require_json(self.layout.candidate)["drain_status"],
                    "drained" if applied else "pending",
                )

    def test_activation_failure_while_publishing_state_is_finished_by_recover_not_reverted(self) -> None:
        # Once the new runtime is verified (runtime-ready), nothing reverts it: a crash while the
        # state files are being written leaves a journal that recover finalizes.
        self.provision()
        candidate = self.write_candidate(drain_status="drained", migration_status="succeeded", data_rebuild_status="succeeded")
        previous = self.write_active()
        self.write_state(self.layout.rollback, release_id="older-release")
        update_journal = self.controller.update_journal

        def fail_commit(journal: dict[str, object], checkpoint: str, **values: object) -> dict[str, object]:
            if checkpoint == "committed":
                raise OSError("state disk full")
            return update_journal(journal, checkpoint, **values)

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(
                self.controller,
                "alias_targets",
                return_value={"publication": "publication-new"},
            ),
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "verify_runtime"),
            mock.patch.object(self.controller, "publish_runtime"),
            mock.patch.object(self.controller, "settle_failed_activation") as settle,
            mock.patch.object(self.controller, "update_journal", side_effect=fail_commit),
            self.assertRaisesRegex(catalogctl.CatalogError, "runtime-ready but finalization failed; run make recover"),
        ):
            self.controller.activate()

        settle.assert_not_called()
        journal = catalogctl.require_json(self.layout.journal)
        self.assertEqual(journal["checkpoint"], "runtime-ready")
        self.assertEqual(journal["new_active"]["release_id"], candidate["release_id"])
        self.assertEqual(journal["new_rollback"], previous)
        self.assertEqual(catalogctl.require_json(self.layout.active)["release_id"], candidate["release_id"])

        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "set_alias_targets"),
            mock.patch.object(self.controller, "verify_runtime"),
        ):
            result = self.controller.recover()

        self.assertEqual(result["outcome"], "finalized")
        self.assertEqual(catalogctl.require_json(self.layout.active)["release_id"], candidate["release_id"])
        self.assertEqual(catalogctl.require_json(self.layout.rollback), previous)
        self.assertFalse(self.layout.candidate.exists())
        self.assertFalse(self.layout.journal.exists())
        history = [json.loads(line) for line in self.layout.history.read_text().splitlines()]
        self.assertEqual([(h["operation"], h["result"]) for h in history], [("deploy", "succeeded")])

    def test_state_files_are_untouched_until_the_journal_carries_the_new_release(self) -> None:
        # A hard crash before the runtime-ready checkpoint must leave active.json as it was,
        # otherwise recover would find published state with no record of what published it.
        self.provision()
        self.write_candidate(drain_status="drained", migration_status="succeeded", data_rebuild_status="succeeded")
        previous = self.write_active()

        def crash(journal: dict[str, object], checkpoint: str, **values: object) -> dict[str, object]:
            raise KeyboardInterrupt

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(self.controller, "alias_targets", return_value={"publication": "publication-new"}),
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "verify_runtime"),
            mock.patch.object(self.controller, "publish_runtime"),
            mock.patch.object(self.controller, "update_journal", side_effect=crash),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.controller.activate()

        self.assertEqual(catalogctl.require_json(self.layout.active), previous)
        self.assertEqual(catalogctl.require_json(self.layout.journal)["checkpoint"], "candidate-started")

    def test_recover_finalizes_a_committed_activation_once(self) -> None:
        self.provision()
        candidate = self.write_candidate(
            migration_status="succeeded",
            data_rebuild_status="succeeded",
            search_aliases_after={"publication": "publication-new"},
        )

        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(
                self.controller,
                "alias_targets",
                return_value={"publication": "publication-new"},
            ),
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "verify_runtime"),
            mock.patch.object(self.controller, "publish_runtime"),
            mock.patch.object(self.controller, "append_history_once", side_effect=OSError("history disk full")),
            self.assertRaisesRegex(catalogctl.CatalogError, "committed but finalization failed"),
        ):
            self.controller.activate()

        active = catalogctl.require_json(self.layout.active)
        self.assertEqual(active["image"], candidate["image"])
        self.assertEqual(catalogctl.require_json(self.layout.journal)["checkpoint"], "committed")
        self.assertTrue(self.layout.candidate.exists())

        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "set_alias_targets"),
            mock.patch.object(self.controller, "verify_runtime"),
        ):
            result = self.controller.recover()

        self.assertEqual(result["outcome"], "finalized")
        self.assertEqual(self.layout.canonical_compose.read_bytes(), Path(candidate["compose_file"]).read_bytes())
        self.assertFalse(self.layout.candidate.exists())
        self.assertFalse(self.layout.journal.exists())
        history = [json.loads(line) for line in self.layout.history.read_text().splitlines()]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["operation"], "deploy")
        self.assertEqual(history[0]["result"], "succeeded")

    def test_recover_finalizes_an_activation_interrupted_after_its_runtime_was_verified(self) -> None:
        # The journal carries the new release from runtime-ready on, so a crash while the state
        # files are being published (even after active.json was written) is finished, not reverted.
        self.provision()
        candidate = self.write_candidate(migration_status="succeeded", data_rebuild_status="succeeded")
        new_active = {
            key: candidate[key]
            for key in (
                "host_id", "release_id", "image", "bundle_revision", "citation_revision", "manifest_sha256",
                "compose_file", "compose_sha256", "release_dir", "bundle_sha256", "support_images",
            )
        }
        new_active.update(schema_version=catalogctl.SCHEMA_VERSION, search_aliases={"publication": "publication-new"})
        self.write_state(
            self.layout.journal,
            operation="deploy",
            operation_id=candidate["operation_id"],
            started_at=catalogctl.utc_now(),
            checkpoint="runtime-ready",
            candidate=candidate,
            previous_active=None,
            previous_rollback=None,
            new_active=new_active,
            new_rollback=None,
        )
        catalogctl.atomic_json(self.layout.active, new_active)

        with (
            mock.patch.object(self.controller, "compose") as compose,
            mock.patch.object(self.controller, "set_alias_targets"),
            mock.patch.object(self.controller, "verify_runtime"),
            mock.patch.object(self.controller, "settle_failed_activation") as settle,
        ):
            result = self.controller.recover()

        settle.assert_not_called()
        self.assertEqual(result["outcome"], "finalized")
        self.assertEqual(catalogctl.require_json(self.layout.active)["release_id"], candidate["release_id"])
        self.assertFalse(self.layout.journal.exists())
        self.assertFalse(self.layout.candidate.exists())
        history = [json.loads(line) for line in self.layout.history.read_text().splitlines()]
        self.assertEqual([(h["operation"], h["result"]) for h in history], [("deploy", "succeeded")])
        up_calls = [call for call in compose.call_args_list if "up" in call.args]
        self.assertEqual(len(up_calls), 1)

    def test_host_check_names_a_setting_django_cannot_read(self) -> None:
        self.provision()
        config = self.layout.secrets / "config.ini"
        config.write_text(config.read_text(encoding="utf-8").replace("SECRET_KEY=", "SECRET_KEY=100%", 1), encoding="utf-8")
        with (
            mock.patch.object(self.controller, "command_output", return_value=""),
            mock.patch.object(catalogctl.host, "MAX_MAP_COUNT_PATH", Path(self.temporary.name) / "absent"),
            self.assertRaisesRegex(catalogctl.CatalogError, "django.SECRET_KEY cannot be read as Django reads it"),
        ):
            self.controller.host_check()

    # rollback

    def rollback_fixture(self, **candidate: object) -> tuple[dict[str, Any], dict[str, Any]]:
        self.provision()
        rollback = self.write_active(
            "a", release_id="release-a", search_aliases={"publication": "publication-20261027t120000000000z"}
        )
        active = self.write_active("b")
        catalogctl.atomic_json(self.layout.rollback, rollback)
        if candidate:
            self.write_candidate(**candidate)
        return active, rollback

    def test_rollback_refuses_while_a_candidate_changed_or_is_changing_the_database(self) -> None:
        for state, message in (
            ({"migration_status": "failed", "migration_applied": True}, "migrations were applied"),
            ({"migration_status": "in_progress"}, "migration_status in progress"),
            ({"restore_status": "in_progress"}, "restore_status in progress"),
        ):
            with self.subTest(state=state):
                self.rollback_fixture(drain_status="drained", **state)
                with (
                    mock.patch.object(self.controller, "compose") as compose,
                    self.assertRaisesRegex(catalogctl.CatalogError, message),
                ):
                    self.controller.rollback_release()
                compose.assert_not_called()
                self.assertFalse(self.layout.journal.exists())

    def test_rollback_stops_the_writers_rebuilds_search_with_the_previous_release_and_invalidates_the_candidate(self) -> None:
        # The previous generations are snapshots of an older database, so the previous release rebuilds
        # them with its own code while no writer runs; a candidate's drain and generations are stale after.
        active, rollback = self.rollback_fixture(drain_status="drained", migration_status="succeeded",
                                                 data_rebuild_status="succeeded")
        calls: list[tuple[str, tuple[str, ...]]] = []

        def compose(path: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((Path(path).parent.name, arguments))
            return subprocess.CompletedProcess(list(arguments), 0, "", "")

        with (
            mock.patch.object(self.controller, "compose", side_effect=compose),
            mock.patch.object(self.controller, "set_alias_targets"),
            mock.patch.object(self.controller, "verify_runtime"),
            mock.patch.object(self.controller, "alias_targets", return_value={"publication": "publication-a2"}),
            mock.patch.object(self.controller, "manage") as manage,
        ):
            result = self.controller.rollback_release()

        self.assertEqual(result["release_id"], "release-a")
        self.assertEqual(result["aliases"], {"publication": "publication-a2"})
        self.assertEqual(calls[0], ("b", ("stop", "--timeout", "120", "scheduler")))
        self.assertEqual(calls[2], ("b", ("rm", "--force", "scheduler", "django")))
        self.assertEqual(calls[3], ("a", ("up", "-d", "--wait", "db", "redis", "elasticsearch")))
        self.assertEqual(
            [call.args[1:] for call in manage.call_args_list],
            [("rebuild_es_index",), ("validate_search_indexes",), ("populate_visualization_cache", "--clear")],
        )
        self.assertTrue(all(Path(call.args[0]).parent.name == "a" for call in manage.call_args_list))
        self.assertEqual(catalogctl.require_json(self.layout.active)["search_aliases"], {"publication": "publication-a2"})
        self.assertEqual(catalogctl.require_json(self.layout.rollback)["release_id"], active["release_id"])
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual((candidate["drain_status"], candidate["data_rebuild_status"]), ("pending", "pending"))
        self.assertIsNone(candidate["search_aliases_after"])

    def test_every_writer_resume_invalidates_the_candidate_drain_and_rebuild(self) -> None:
        self.provision()
        self.write_active()
        self.write_candidate(drain_status="drained", migration_status="succeeded", data_rebuild_status="succeeded")
        with mock.patch.object(self.controller, "compose"):
            self.controller.start()
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual((candidate["drain_status"], candidate["data_rebuild_status"]), ("pending", "pending"))
        self.assertIsNone(candidate["search_aliases_after"])

        self.write_candidate(drain_status="drained", migration_status="succeeded", data_rebuild_status="succeeded")
        with (
            mock.patch.object(self.controller, "manage"),
            mock.patch.object(self.controller, "alias_targets", return_value={"publication": "publication-new"}),
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "verify_runtime", side_effect=[catalogctl.CatalogError("no answer"), None]),
            mock.patch.object(self.controller, "publish_runtime"),
            self.assertRaisesRegex(catalogctl.CatalogError, "prior runtime recovered=True"),
        ):
            self.controller.activate()
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual((candidate["drain_status"], candidate["data_rebuild_status"]), ("pending", "pending"))
        with self.assertRaisesRegex(catalogctl.CatalogError, "make drain"):
            self.controller.rebuild()

    # rebuild and the writer policy

    def test_rebuild_and_activate_require_a_current_drain_on_an_active_host(self) -> None:
        # start resets the drain, so a rebuild or activation after it would race the writers.
        self.provision()
        self.write_active()
        self.write_candidate(drain_status="pending", migration_status="succeeded")
        with mock.patch.object(self.controller, "compose") as compose:
            with self.assertRaisesRegex(catalogctl.CatalogError, "make drain"):
                self.controller.rebuild()
            self.write_candidate(drain_status="pending", migration_status="succeeded", data_rebuild_status="succeeded")
            with self.assertRaisesRegex(catalogctl.CatalogError, "make drain"):
                self.controller.activate()
        compose.assert_not_called()

    # bundle hashing

    def test_failed_start_invalidates_candidate_before_writers_can_run(self) -> None:
        self.rollback_fixture(drain_status="drained", migration_status="succeeded", data_rebuild_status="succeeded")
        def partial_start(*args, **kwargs):
            candidate = catalogctl.require_json(self.layout.candidate)
            self.assertEqual(candidate["drain_status"], "pending")
            self.assertEqual(candidate["data_rebuild_status"], "pending")
            raise catalogctl.CatalogError("partial startup")
        with mock.patch.object(self.controller, "compose", side_effect=partial_start):
            with self.assertRaisesRegex(catalogctl.CatalogError, "partial startup"):
                self.controller.start()

    def test_rollback_finalization_invalidates_before_start_and_journal_removal(self) -> None:
        active, rollback = self.rollback_fixture(drain_status="drained", migration_status="succeeded",
                                                 data_rebuild_status="succeeded")
        self.write_state(self.layout.journal, operation="rollback", operation_id="rollback-1",
                         checkpoint="runtime-ready", new_active=rollback, new_rollback=active)
        def start(*args, **kwargs):
            self.assertEqual(catalogctl.require_json(self.layout.candidate)["drain_status"], "pending")
        with mock.patch.object(self.controller, "start_release", side_effect=start):
            self.controller.recover()
        self.assertFalse(self.layout.journal.exists())

    def test_replacement_inherits_restore_swap_names(self) -> None:
        self.provision()
        self.write_candidate(restore_status="pending", restore_temporary_database="restoring",
                             restore_retained_database="retained")
        manifest, _ = self.write_manifest()
        with self.prepare_environment():
            self.controller.prepare(manifest)
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertEqual(candidate["restore_temporary_database"], "restoring")
        self.assertEqual(candidate["restore_retained_database"], "retained")

    def test_repeated_rebuilds_keep_active_generations_available_for_recovery(self) -> None:
        active, _ = self.rollback_fixture(drain_status="drained", migration_status="succeeded")
        active["search_aliases"] = {"publication": "b"}
        catalogctl.atomic_json(self.layout.active, active)
        aliases = {"publication": "c"}
        indices = {"b", "c"}
        def switch(_compose, targets):
            self.assertFalse(set(targets.values()) - indices)
            aliases.clear()
            aliases.update(targets)
        def manage(_compose, command, *args, **kwargs):
            if command == "rebuild_es_index":
                previous = set(aliases.values())
                indices.add("d")
                indices.intersection_update(previous | {"d"})
                aliases.update(publication="d")
            if command == "populate_visualization_cache":
                raise catalogctl.CatalogError("cache failed")
        with (mock.patch.object(self.controller, "compose"),
              mock.patch.object(self.controller, "manage", side_effect=manage),
              mock.patch.object(self.controller, "set_alias_targets", side_effect=switch),
              mock.patch.object(self.controller, "alias_targets", side_effect=lambda *_: dict(aliases)),
              mock.patch.object(self.controller, "verify_runtime")):
            with self.assertRaisesRegex(catalogctl.CatalogError, "cache failed"):
                self.controller.rebuild()
            self.assertIn("b", indices)
            with self.assertRaisesRegex(catalogctl.CatalogError, "active runtime recovered=True"):
                self.controller.rollback_release()
        self.assertIn("b", indices)
        self.assertFalse(self.layout.journal.exists())

    def test_bundle_hash_cannot_absorb_a_deleted_successor_into_a_changed_file(self) -> None:
        root = Path(self.temporary.name)
        honest = root / "honest"
        honest.mkdir()
        (honest / "a").write_bytes(b"x")
        (honest / "b").write_bytes(b"y")
        mode = f"{(honest / 'b').stat().st_mode & 0o111:o}"
        tampered = root / "tampered"
        tampered.mkdir()
        (tampered / "a").write_bytes(b"x" + f"F b\0{mode}\0".encode() + b"y")
        self.assertNotEqual(catalogctl.sha256_tree(honest), catalogctl.sha256_tree(tampered))

    # restore

    def test_restore_finishes_a_swap_whose_record_was_interrupted(self) -> None:
        # The receipt and the swap's database names are on disk before the renames, so a restore
        # that swapped the databases but never recorded success is recognised and finished.
        self.provision()
        receipt_path = self.layout.receipts / "restores" / f"restore-{RELEASE_ID}.json"
        counts = {"citation_publication": 5, "primary_publication": 2}
        catalogctl.atomic_json(receipt_path, {
            "schema_version": catalogctl.SCHEMA_VERSION, "kind": "restore", "database": "comses_catalog",
            "retained_database": "comses_catalog_before_x", "counts": counts, "sha256": "e" * 64,
        })
        self.write_candidate(
            restore_status="pending",
            restore_receipt=str(receipt_path),
            restore_retained_database="comses_catalog_before_x",
            restore_sha256="e" * 64,
        )
        dump = Path(self.temporary.name) / "catalog.sql"
        dump.write_text("SELECT 1;\n", encoding="utf-8")
        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "db_identity", return_value=("catalog", "comses_catalog")),
            mock.patch.object(self.controller, "database_counts", return_value=counts),
            mock.patch.object(self.controller, "psql", return_value="1") as psql,
        ):
            result = self.controller.restore(dump, "comses_catalog")

        self.assertTrue(result["already"])
        self.assertEqual(result["retained_database"], "comses_catalog_before_x")
        self.assertIn("pg_database", psql.call_args.args[-1])
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["restore_status"], "succeeded")

    def restore_reconcile_fixture(self, **candidate: object) -> tuple[Path, dict[str, int]]:
        self.provision()
        counts = {"citation_publication": 5, "primary_publication": 2}
        receipt_path = self.layout.receipts / "restores" / f"restore-{RELEASE_ID}.json"
        catalogctl.atomic_json(receipt_path, {
            "schema_version": catalogctl.SCHEMA_VERSION, "kind": "restore", "database": "comses_catalog",
            "retained_database": "comses_catalog_before_x", "counts": counts, "sha256": "e" * 64,
        })
        self.write_candidate(restore_status="pending", restore_receipt=str(receipt_path), restore_sha256="e" * 64,
                             restore_temporary_database="comses_catalog_restore_x",
                             restore_retained_database="comses_catalog_before_x", **candidate)
        dump = Path(self.temporary.name) / "catalog.sql"
        dump.write_text("SELECT 1;\n", encoding="utf-8")
        return dump, counts

    def test_restore_finishes_a_swap_interrupted_between_its_two_renames(self) -> None:
        dump, counts = self.restore_reconcile_fixture()
        existing = {"comses_catalog_before_x", "comses_catalog_restore_x"}
        sql: list[str] = []

        def psql(compose_file: Path, user: str, database: str, statement: str) -> str:
            sql.append(statement)
            if "pg_database" in statement:
                name = statement.split("'")[1]
                return "1" if name in existing else "0"
            if "RENAME TO" in statement:
                existing.discard("comses_catalog_restore_x")
                existing.add("comses_catalog")
            return ""

        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "db_identity", return_value=("catalog", "comses_catalog")),
            mock.patch.object(self.controller, "database_counts", return_value=counts),
            mock.patch.object(self.controller, "psql", side_effect=psql),
        ):
            result = self.controller.restore(dump, "comses_catalog")

        self.assertTrue(result["already"])
        self.assertIn('ALTER DATABASE "comses_catalog_restore_x" RENAME TO "comses_catalog";', sql)
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["restore_status"], "succeeded")

    def test_restore_drops_a_populated_copy_whose_swap_never_started_and_starts_over(self) -> None:
        dump, _counts = self.restore_reconcile_fixture()
        existing = {"comses_catalog", "comses_catalog_restore_x"}
        sql: list[str] = []

        def psql(compose_file: Path, user: str, database: str, statement: str) -> str:
            sql.append(statement)
            if "pg_database" in statement:
                return "1" if statement.split("'")[1] in existing else "0"
            if "DROP DATABASE" in statement:
                existing.discard("comses_catalog_restore_x")
            return ""

        with (
            mock.patch.object(self.controller, "compose"),
            mock.patch.object(self.controller, "db_identity", return_value=("catalog", "comses_catalog")),
            mock.patch.object(self.controller, "database_counts", return_value={"citation_publication": 0, "primary_publication": 0}),
            mock.patch.object(self.controller, "psql", side_effect=psql),
            mock.patch.object(self.controller.runner, "run"),
            mock.patch.object(self.controller, "postgres_versions", return_value={}),
            mock.patch("subprocess.Popen") as popen,
        ):
            popen.return_value.wait.return_value = 1  # the fresh attempt fails at the plain restore; that is not under test
            with self.assertRaisesRegex(catalogctl.CatalogError, "plain SQL restore failed"):
                self.controller.restore(dump, "comses_catalog")

        self.assertIn('DROP DATABASE IF EXISTS "comses_catalog_restore_x";', sql)
        candidate = catalogctl.require_json(self.layout.candidate)
        self.assertNotEqual(candidate["restore_temporary_database"], "comses_catalog_restore_x")
        self.assertTrue(candidate["restore_temporary_database"].startswith("comses_catalog_restore_"))

    def test_recover_without_a_journal_has_nothing_to_do(self) -> None:
        self.provision()
        with mock.patch.object(self.controller, "compose") as compose:
            result = self.controller.recover()

        compose.assert_not_called()
        self.assertEqual(result, {"phase": "recover", "ok": True, "already": True, "outcome": "nothing-to-recover"})

    def test_start_returns_the_previous_release_only_while_the_schema_is_untouched(self) -> None:
        self.provision()
        self.write_active()
        self.write_candidate(restore_status="not_required", drain_status="drained", migration_applied=False)
        with mock.patch.object(self.controller, "compose") as compose:
            self.controller.start()
        compose.assert_called_once()
        self.assertEqual(catalogctl.require_json(self.layout.candidate)["drain_status"], "pending")

        self.write_candidate(restore_status="not_required", drain_status="drained", migration_applied=True)
        with (
            mock.patch.object(self.controller, "compose") as compose,
            self.assertRaisesRegex(catalogctl.CatalogError, "migrations were applied"),
        ):
            self.controller.start()
        compose.assert_not_called()

    # validate, status, CLI

    def run_validate(
        self,
        containers: dict[str, dict[str, Any]],
        failing: tuple[tuple[str, ...], ...] = (),
    ) -> dict[str, Any]:
        def manage(_compose: Path, *arguments: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if arguments in failing:
                raise catalogctl.CatalogError("check failed")
            return subprocess.CompletedProcess(list(arguments), 0, "", "")

        with (
            mock.patch.object(self.controller, "running_containers", return_value=containers),
            mock.patch.object(self.controller, "manage", side_effect=manage),
            mock.patch.object(self.controller, "verify_runtime"),
        ):
            return self.controller.validate()

    def healthy_containers(self, active: dict[str, Any]) -> dict[str, dict[str, Any]]:
        containers = {
            service: {"image": SUPPORT_IMAGES[0], "revision": None, "state": "running", "health": "healthy"}
            for service in catalogctl.REQUIRED_SERVICES
        }
        for service in catalogctl.APPLICATION_SERVICES:
            containers[service] = {
                "image": active["image"],
                "revision": active["bundle_revision"],
                "state": "running",
                "health": "healthy",
            }
        return containers

    def test_validate_checks_services_running_artifacts_migrations_and_http(self) -> None:
        self.provision()
        active = self.write_active()

        result = self.run_validate(self.healthy_containers(active))

        self.assertTrue(result["ok"], result["checks"])
        self.assertTrue(result["checks"]["artifact:django"]["ok"])
        self.assertTrue(result["checks"]["http"]["ok"])

    def test_validate_fails_on_a_wrong_running_image_or_a_failed_check(self) -> None:
        self.provision()
        active = self.write_active()
        containers = self.healthy_containers(active)
        containers["django"]["image"] = IMAGE
        containers["redis"]["health"] = "unhealthy"

        result = self.run_validate(containers, failing=(("migrate", "--check"),))

        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["artifact:django"]["ok"])
        self.assertFalse(result["checks"]["service:redis"]["ok"])
        self.assertFalse(result["checks"]["migrations"]["ok"])
        self.assertTrue(result["checks"]["search"]["ok"])

    def test_validate_rejects_a_container_built_from_another_commit(self) -> None:
        self.provision()
        active = self.write_active()
        containers = self.healthy_containers(active)
        containers["scheduler"]["revision"] = "d" * 40

        result = self.run_validate(containers)

        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["artifact:scheduler"]["ok"])

    def test_release_report_names_the_pre_release_backup(self) -> None:
        self.provision()
        previous = self.write_active("previous", image="ghcr.io/comses/catalog@sha256:" + "9" * 64)
        backup = self.run_backup()
        self.write_active("current")

        with (
            mock.patch.object(self.controller, "db_identity", return_value=("catalog", "comses_catalog")),
            mock.patch.object(self.controller, "command_output", return_value=""),
            mock.patch.object(self.controller, "manage", return_value=subprocess.CompletedProcess([], 0, "", "")),
            mock.patch.object(self.controller, "postgres_versions", return_value={}),
            mock.patch.object(self.controller, "database_counts", return_value={}),
            mock.patch.object(self.controller, "alias_targets", return_value={}),
        ):
            report = self.controller.release_report()

        self.assertEqual(report["latest_backup"]["archive"], backup["archive"])
        self.assertTrue(report["latest_backup"]["verified"])
        self.assertEqual(
            report["latest_backup"]["release_id"],
            catalogctl.release_id(previous["bundle_revision"], previous["image"]),
        )

    def test_main_prints_one_json_result_and_matching_exit_status(self) -> None:
        self.provision()
        self.write_candidate(drain_status="drained")
        environment = {
            "CATALOG_HOST_DIR": str(self.layout.root),
            "CATALOG_BACKUP_DIR": str(self.layout.backups),
        }
        with (
            mock.patch.dict(os.environ, environment),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            status_code = catalogctl.main(["status"])
        status = json.loads(stdout.getvalue())
        self.assertEqual(status_code, 0)
        self.assertEqual(status["phase"], "status")
        self.assertIsNone(status["active"])
        self.assertEqual(status["candidate"]["drain_status"], "drained")
        self.assertEqual(status["lock_protocol"], "inherited-fd-v1")
        self.assertEqual(
            status["candidate"]["manifest_sha256"],
            catalogctl.require_json(self.layout.candidate).get("manifest_sha256"),
        )

        with (
            mock.patch.dict(os.environ, environment),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            not_ready_code = catalogctl.main(["backup-status"])
        self.assertEqual(not_ready_code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

        missing = Path(self.temporary.name) / "missing.json"
        with (
            mock.patch.dict(os.environ, environment),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            failure_code = catalogctl.main(["prepare", "--manifest", str(missing)])
        failure = json.loads(stdout.getvalue())
        self.assertEqual(failure_code, 1)
        self.assertEqual(failure["phase"], "prepare")
        self.assertFalse(failure["ok"])
        self.assertIn("cannot read release manifest", failure["error"])


if __name__ == "__main__":
    unittest.main()
