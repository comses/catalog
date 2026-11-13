"""The candidate release: preparation, writer drain, migration, and retry after a failure."""

from __future__ import annotations

import getpass
import io
import json
import os
import shutil
import tarfile
import uuid
from pathlib import Path
from typing import Any

from .common import CatalogError, append_json_line, atomic_json, fsync_directory, log, read_json, sha256_file, sha256_tree, utc_now
from .constants import CONTROLLER_VERSION, DEPENDENCY_SERVICES, HOST_CANDIDATE_FIELDS, SCHEMA_VERSION, WRITER_SERVICES
from .manifest import load_manifest, release_id
from .search import SearchOperations


class CandidateOperations(SearchOperations):
    """A candidate is prepared while the current release serves and locked once it changes the host."""

    def require_empty_runtime(self) -> None:
        label = f"label=com.docker.compose.project={self.host().project_name}"
        containers = self.command_output(["docker", "ps", "-a", "--filter", label, "--format", "{{.Names}}"])
        volumes = self.command_output(["docker", "volume", "ls", "--filter", label, "--format", "{{.Name}}"])
        existing = sorted(containers.split() + volumes.split())
        if existing:
            raise CatalogError(
                "a first deployment needs an empty Docker runtime, but these Compose containers or "
                f"volumes already exist: {', '.join(existing)}; retire that stack explicitly first"
            )

    def foreign_http_publishers(self) -> list[str]:
        host = self.host()
        port = host.http_bind.rpartition(":")[2]
        listing = self.command_output(
            ["docker", "ps", "--filter", f"publish={port}", "--format", '{{.Names}}\t{{.Label "com.docker.compose.project"}}']
        )
        publishers = []
        for line in listing.splitlines():
            name, _, project = line.partition("\t")
            if project != host.project_name:
                publishers.append(f"{name} ({project or 'no Compose project'})")
        return sorted(publishers)

    def require_clean_revision(self, revision: str) -> str:
        head = self.command_output(["git", "rev-parse", "HEAD"], cwd=self.root)
        if head != revision:
            raise CatalogError(
                f"checkout HEAD {head} is not the manifest's Catalog commit; run git checkout --detach {revision}"
            )
        status = self.command_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=self.root
        )
        if status:
            raise CatalogError("candidate creation requires a clean checkout")
        citation_status = self.command_output(
            ["git", "-C", "citation", "status", "--porcelain", "--untracked-files=normal"],
            cwd=self.root,
        )
        if citation_status:
            raise CatalogError("citation submodule must be clean")

        expected_citation = self.command_output(
            ["git", "rev-parse", f"{revision}:citation"], cwd=self.root
        )
        citation_checkout = self.command_output(
            ["git", "-C", "citation", "rev-parse", "HEAD"], cwd=self.root
        )
        if citation_checkout != expected_citation:
            raise CatalogError("citation checkout does not match the Catalog gitlink")
        return expected_citation

    def pull_and_verify_image(
        self, image: str, revision: str, citation_revision: str
    ) -> dict[str, str]:
        self.runner.run(["docker", "pull", image], capture=False)
        labels_raw = self.command_output(
            ["docker", "image", "inspect", image, "--format", "{{json .Config.Labels}}"]
        )
        labels = json.loads(labels_raw or "{}")
        built_from = labels.get("org.opencontainers.image.revision")
        if built_from != revision:
            raise CatalogError(f"image {image} was built from {built_from}, not the manifest's Catalog commit {revision}")
        image_citation_revision = labels.get("org.comses.catalog.citation-revision")
        if image_citation_revision != citation_revision:
            raise CatalogError("image Citation revision label does not match the Catalog gitlink")
        return labels

    def archive_release(self, revision: str, release_dir: Path) -> str:
        archive = self.runner.run(
            ["git", "archive", "--format=tar", revision],
            cwd=self.root,
            text=False,
        ).stdout
        temporary = release_dir.with_name(f".{release_dir.name}.{uuid.uuid4().hex}")
        temporary.mkdir(parents=True)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
                bundle.extractall(temporary, filter="data")
            expected = sha256_tree(temporary)
            if release_dir.exists():
                actual = sha256_tree(release_dir, excluded={"docker-compose.yml"})
                if actual != expected:
                    raise CatalogError(f"existing release bundle was modified: {release_dir}")
                return expected
            os.replace(temporary, release_dir)
            fsync_directory(release_dir.parent)
            return expected
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def prepare(self, manifest_path: Path) -> dict[str, Any]:
        manifest, manifest_sha256 = load_manifest(manifest_path)
        image = manifest["image"]
        revision = manifest["catalog_revision"]
        candidate_id = release_id(revision, image)
        assert candidate_id is not None
        with self.locked():
            self.host_check()
            if self.layout.journal.exists():
                raise CatalogError("an unfinished transaction journal exists; run make recover")
            active = self.active_state()
            rollback = read_json(self.layout.rollback)
            if active and active.get("release_id") == candidate_id:
                log(f"Release {candidate_id} is already active")
                return {"phase": "prepare", "ok": True, "already_active": True, "release_id": candidate_id}
            if rollback and rollback.get("release_id") == candidate_id:
                raise CatalogError(f"release {candidate_id} is the rollback release; use make rollback instead")
            existing = read_json(self.layout.candidate)
            if existing and existing.get("manifest_sha256") == manifest_sha256:
                self.candidate_state()
                log(f"Candidate {candidate_id} is already prepared")
                return {
                    "phase": "prepare",
                    "ok": True,
                    "already": True,
                    "release_id": candidate_id,
                    "manifest_sha256": manifest_sha256,
                }
            # A finished stage is a host fact the replacement inherits; only an unsettled one locks the candidate.
            if existing and any(
                existing.get(stage) in {"in_progress", "failed"}
                for stage in ("restore_status", "migration_status", "data_rebuild_status")
            ):
                raise CatalogError("the existing candidate is locked by restore, migration, or rebuild state")
            inherited = {key: existing[key] for key in HOST_CANDIDATE_FIELDS if key in existing} if existing else {}
            if not active and not existing:
                self.require_empty_runtime()
            citation_revision = self.require_clean_revision(revision)
            if citation_revision != manifest["citation_revision"]:
                raise CatalogError("the Catalog gitlink does not match the manifest's Citation revision")
            self.pull_and_verify_image(image, revision, citation_revision)
            release_dir = self.layout.releases / candidate_id
            release_dir.parent.mkdir(parents=True, exist_ok=True)
            bundle_sha256 = self.archive_release(revision, release_dir)
            compose_file = release_dir / "docker-compose.yml"
            host = self.host()
            environment = os.environ.copy()
            environment.update(
                COMPOSE_PROJECT_NAME=host.project_name,
                CATALOG_IMAGE=image,
                CATALOG_BUNDLE_REVISION=revision,
                CATALOG_CONFIG_DIR=str(self.layout.secrets),
                CATALOG_SHARED_DIR=str(self.layout.shared),
                CATALOG_BACKUP_DIR=str(self.layout.backups),
                CATALOG_BUNDLE_DIR=str(release_dir),
                CATALOG_HTTP_BIND=host.http_bind,
                CATALOG_DOMAIN=host.domain,
                CATALOG_ENV=host.environment,
            )
            self.runner.run(
                ["bash", "scripts/compose.sh", host.environment, str(compose_file)],
                cwd=release_dir,
                env=environment,
                capture=False,
            )
            self.compose(compose_file, "config", "--quiet")
            images_result = self.compose(compose_file, "config", "--images")
            support_images = sorted(
                {line.strip() for line in (images_result.stdout or "").splitlines() if line.strip() != image}
            )
            if support_images != sorted(manifest["support_images"]):
                raise CatalogError("the rendered support images differ from the release manifest")
            if active:
                self.verify_release_artifact(active, "active")
                if active.get("support_images") != support_images:
                    raise CatalogError(
                        "support image digests changed: database and search-engine upgrades are separate, "
                        "reviewed transitions, not routine releases (see the runbook's service image transitions)"
                    )
            if sha256_tree(release_dir, excluded={"docker-compose.yml"}) != bundle_sha256:
                raise CatalogError("release bundle changed while the candidate was rendered")
            candidate = {
                "schema_version": SCHEMA_VERSION,
                "controller_version": CONTROLLER_VERSION,
                "operation_id": uuid.uuid4().hex,
                "host_id": host.host_id,
                "image": image,
                "bundle_revision": revision,
                "citation_revision": citation_revision,
                "manifest": manifest,
                "manifest_sha256": manifest_sha256,
                "release_id": candidate_id,
                "release_dir": str(release_dir),
                "compose_file": str(compose_file),
                "compose_sha256": sha256_file(compose_file),
                "bundle_sha256": bundle_sha256,
                "support_images": support_images,
                "created_at": utc_now(),
                "restore_status": "not_required" if active else "pending",
                "drain_status": "pending" if active else "not_required",
                "migration_status": "unmigrated",
                "data_rebuild_status": "pending",
                **inherited,
            }
            atomic_json(self.layout.candidate, candidate)
            log(f"Candidate {candidate_id} prepared from {image}")
            return {
                "phase": "prepare",
                "ok": True,
                "release_id": candidate_id,
                "manifest_sha256": manifest_sha256,
                "image": image,
                "support_images": support_images,
                "restore_required": candidate["restore_status"] == "pending",
            }

    def stop_writers(self, compose_file: Path) -> None:
        """Stops the writers and removes their containers, so a daemon restart or reboot cannot revive them."""
        for service in WRITER_SERVICES:
            self.compose(compose_file, "stop", "--timeout", "120", service, capture=False)
        self.compose(compose_file, "rm", "--force", *WRITER_SERVICES, capture=False)

    @staticmethod
    def require_writers_drained(candidate: dict[str, Any], active: dict[str, Any] | None) -> None:
        """A host with an active release changes its database or search only while that release's writers are stopped."""
        if active and candidate.get("drain_status") != "drained":
            raise CatalogError("stop the active release's writers first: make drain")

    def writers_resumed(self) -> None:
        """The active release's writers run again, so the candidate's drain and its rebuilt generations are stale."""
        candidate = read_json(self.layout.candidate)
        if not candidate:
            return
        values: dict[str, Any] = {}
        if candidate.get("drain_status") == "drained":
            values["drain_status"] = "pending"
        if candidate.get("data_rebuild_status") == "succeeded":
            values.update(data_rebuild_status="pending", search_aliases_after=None)
        if not candidate.get("migration_applied") and candidate.get("migration_status") != "in_progress":
            values.update(migration_backup=None, migration_started_at=None)
        if values:
            self.update_candidate(candidate, **values)
            if "migration_backup" in values:
                self.release_migration_backup(candidate)

    def require_schema_untouched_by_candidate(self) -> None:
        """Refuses to run a previous release while a candidate changed, or is changing, the database."""
        candidate = read_json(self.layout.candidate)
        if not candidate:
            return
        for stage in ("restore_status", "migration_status"):
            if candidate.get(stage) == "in_progress":
                raise CatalogError(f"candidate {candidate['release_id']} has {stage} in progress; wait for it or investigate")
        if candidate.get("migration_applied"):
            raise CatalogError(
                f"migrations were applied for candidate {candidate['release_id']}; the previous release "
                "may not match the schema, so finish the release or follow the recovery policy"
            )

    def migrations_pending(self, compose_file: Path) -> bool:
        # migrate --check exits non-zero while unapplied migrations exist.
        try:
            self.manage(compose_file, "migrate", "--check", capture=True)
        except CatalogError:
            return True
        return False

    def drain(self) -> dict[str, Any]:
        with self.locked():
            candidate = self.candidate_state()
            active = self.active_state()
            if not active:
                return {"phase": "drain", "ok": True, "already": True, "stopped": [], "reason": "no active release"}
            compose_file = self.verify_release_artifact(active, "active")
            # Re-run even when recorded as drained: nothing else proves the writers are still down.
            self.stop_writers(compose_file)
            if candidate.get("drain_status") == "drained":
                return {"phase": "drain", "ok": True, "already": True, "stopped": list(WRITER_SERVICES)}
            self.update_candidate(candidate, drain_status="drained", drained_at=utc_now())
            log(f"Writers of {active['release_id']} stopped; the site is unavailable until activate")
            return {
                "phase": "drain",
                "ok": True,
                "stopped": list(WRITER_SERVICES),
                "release_id": active["release_id"],
            }

    def migrate(self, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise CatalogError("set CONFIRM_SCHEMA_MIGRATION=1 to run migrate")
        with self.locked():
            candidate = self.candidate_state()
            if candidate["migration_status"] == "succeeded":
                return {"phase": "migrate", "ok": True, "already": True, "plan": candidate.get("migration_plan", [])}
            if candidate["migration_status"] != "unmigrated":
                raise CatalogError(
                    f"candidate migration status is {candidate['migration_status']}; "
                    "investigate, then run CONFIRM_CANDIDATE_RETRY=1 make candidate-retry"
                )
            active = self.active_state()
            backup = None
            if active:
                self.verify_release_artifact(active, "active")
                self.require_writers_drained(candidate, active)
            elif candidate.get("restore_status") != "succeeded":
                raise CatalogError("fresh-host migration requires a successful restore receipt")
            compose_file = Path(candidate["compose_file"])
            self.compose(compose_file, "up", "-d", "--wait", *DEPENDENCY_SERVICES, capture=False)
            if active:
                backup = self.select_migration_backup(candidate, active)
            candidate = self.update_candidate(
                candidate,
                migration_status="in_progress",
                migration_started_at=candidate.get("migration_started_at") or utc_now(),
                migration_applied=bool(candidate.get("migration_applied")),
                migration_backup=backup,
            )
            try:
                self.manage(compose_file, "makemigrations", "--check", "--dry-run")
                plan = (self.manage(compose_file, "migrate", "--plan", capture=True).stdout or "").splitlines()
                for line in plan:
                    log(f"plan: {line}")
                if self.migrations_pending(compose_file):
                    candidate = self.update_candidate(candidate, migration_plan=plan, migration_applied=True)
                    self.manage(compose_file, "migrate", "--noinput")
                    self.manage(compose_file, "migrate", "--check")
                else:
                    candidate = self.update_candidate(candidate, migration_plan=plan)
            except Exception as error:
                applied = bool(candidate.get("migration_applied"))
                self.update_candidate(
                    candidate,
                    migration_status="failed",
                    migration_failed_at=utc_now(),
                    migration_error=str(error),
                )
                if applied:
                    raise CatalogError(
                        f"migration failed after changes were applied; the database may be partly migrated: {error}"
                    ) from error
                raise CatalogError(
                    f"migration checks failed before any change was applied; make start restores the previous release: {error}"
                ) from error
            self.update_candidate(candidate, migration_status="succeeded", migration_completed_at=utc_now())
            log("Migrations applied; the application stays stopped until activate")
            return {
                "phase": "migrate",
                "ok": True,
                "plan": plan,
                "backup": backup["receipt"]["archive"] if backup else None,
            }

    def candidate_retry(self, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise CatalogError("set CONFIRM_CANDIDATE_RETRY=1 after investigating the failed operation")
        with self.locked():
            if self.layout.journal.exists():
                raise CatalogError("an unfinished transaction journal exists; run make recover")
            candidate = self.candidate_state()
            migration_status = candidate["migration_status"]
            rebuild_status = candidate["data_rebuild_status"]
            restore_status = candidate.get("restore_status")
            if restore_status in {"failed", "in_progress"}:
                next_values = {"restore_status": "pending"}
                stage = "restore"
            elif migration_status in {"failed", "in_progress"}:
                next_values = {
                    "migration_status": "unmigrated",
                    "data_rebuild_status": "pending",
                }
                stage = "migrate"
            elif rebuild_status in {"failed", "in_progress"}:
                aliases_before = candidate.get("search_aliases_before")
                if not isinstance(aliases_before, dict):
                    raise CatalogError("candidate has no pre-rebuild search alias snapshot")
                compose_file = Path(candidate["compose_file"])
                self.compose(compose_file, "up", "-d", "--wait", *DEPENDENCY_SERVICES, capture=False)
                self.set_alias_targets(compose_file, aliases_before)
                if self.alias_targets(compose_file) != aliases_before:
                    raise CatalogError("could not restore the pre-rebuild search aliases")
                next_values = {"data_rebuild_status": "pending"}
                stage = "rebuild"
            else:
                raise CatalogError("candidate has no failed or interrupted stage to retry")
            for key in list(candidate):
                if (
                    key.startswith("migration_failed_")
                    or key.startswith("data_rebuild_failed_")
                    or key.startswith("restore_failed_")
                    or key in {"migration_error", "data_rebuild_error", "restore_error"}
                ):
                    candidate.pop(key)
            candidate = self.update_candidate(
                candidate,
                **next_values,
                incident_reset_at=utc_now(),
                incident_reset_by=getpass.getuser(),
            )
            append_json_line(
                self.layout.history,
                {
                    "schema_version": SCHEMA_VERSION,
                    "operation": "candidate-retry",
                    "result": "authorized",
                    "host_id": self.host().host_id,
                    "release_id": candidate["release_id"],
                    "stage": stage,
                    "timestamp": utc_now(),
                },
            )
            log(f"Candidate unlocked for {stage}; rerun that phase")
            return {"phase": "candidate-retry", "ok": True, "stage": stage, "release_id": candidate["release_id"]}
