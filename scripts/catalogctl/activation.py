"""Journaled release transitions: activation, rollback, recovery, and the runtime they publish."""

from __future__ import annotations

import getpass
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidate import CandidateOperations
from .common import CatalogError, append_json_line, atomic_json, atomic_write, log, read_json, require_json, utc_now
from .constants import DEPENDENCY_SERVICES, FINALIZABLE_CHECKPOINTS, SCHEMA_VERSION


class ActivationOperations(CandidateOperations):
    """Every transition is journaled so an interrupted one can be recovered or finished."""

    def write_journal(self, value: dict[str, Any]) -> None:
        value = dict(value)
        value["schema_version"] = SCHEMA_VERSION
        atomic_json(self.layout.journal, value)

    def update_journal(self, journal: dict[str, Any], checkpoint: str, **values: Any) -> dict[str, Any]:
        journal = dict(journal)
        journal.update(values)
        journal["checkpoint"] = checkpoint
        journal["updated_at"] = utc_now()
        self.write_journal(journal)
        return journal

    def append_history_once(self, record: dict[str, Any]) -> None:
        operation_id = record["operation_id"]
        result = record["result"]
        if self.layout.history.exists():
            try:
                with self.layout.history.open(encoding="utf-8") as source:
                    for line in source:
                        existing = json.loads(line)
                        if (
                            existing.get("operation_id") == operation_id
                            and existing.get("result") == result
                        ):
                            return
            except (OSError, json.JSONDecodeError) as error:
                raise CatalogError(f"invalid release history {self.layout.history}: {error}") from error
        append_json_line(self.layout.history, record)

    def restore_release_state(
        self,
        active: dict[str, Any] | None,
        rollback: dict[str, Any] | None,
    ) -> None:
        if active:
            atomic_json(self.layout.active, active)
        else:
            self.layout.active.unlink(missing_ok=True)
        if rollback:
            atomic_json(self.layout.rollback, rollback)
        else:
            self.layout.rollback.unlink(missing_ok=True)

    def start_release(self, compose_file: Path, aliases: dict[str, str], *, validate_search: bool = False) -> None:
        """Switches search to the release's generations, starts it, checks it, and publishes its runtime."""
        self.set_alias_targets(compose_file, aliases)
        if validate_search:
            self.manage(compose_file, "validate_search_indexes")
        self.compose(compose_file, "up", "-d", "--no-build", "--wait", "--remove-orphans", capture=False)
        self.verify_runtime(compose_file)
        self.publish_runtime(compose_file)

    def complete_transition(self, journal: dict[str, Any]) -> None:
        """Records a committed transition's outcome and clears its journal."""
        active = journal.get("new_active")
        if not active:
            raise CatalogError("committed journal has no new active release")
        self.append_history_once(
            {
                "schema_version": SCHEMA_VERSION,
                "operation": journal["operation"],
                "operation_id": journal["operation_id"],
                "result": "succeeded",
                "host_id": self.host().host_id,
                "release_id": active["release_id"],
                "image": active["image"],
                "timestamp": utc_now(),
            }
        )
        if journal["operation"] == "deploy":
            self.release_migration_backup(journal.get("candidate", {}))
            self.layout.candidate.unlink(missing_ok=True)
        self.layout.journal.unlink(missing_ok=True)

    def commit_transition(self, journal: dict[str, Any]) -> None:
        """Publishes the release state the journal carries since runtime-ready, then closes the journal."""
        self.restore_release_state(journal["new_active"], journal.get("new_rollback"))
        journal = self.update_journal(journal, "committed")
        self.complete_transition(journal)

    def fail_transition(
        self,
        journal: dict[str, Any],
        error: Exception,
        previous_active: dict[str, Any] | None,
        previous_rollback: dict[str, Any] | None,
        outcome: str | None,
    ) -> tuple[bool, Exception]:
        """Records how a failed transition was settled; returns whether the prior state was recovered."""
        recovered = outcome is not None
        if recovered:
            try:
                self.restore_release_state(previous_active, previous_rollback)
            except Exception as state_error:
                recovered = False
                error = CatalogError(f"{error}; prior state recovery failed: {state_error}")
        self.update_journal(journal, "recovered" if recovered else "unrecovered", error=str(error))
        results = {"kept-down": "failed-kept-down", "restored-previous": "failed-recovered"}
        self.append_history_once(
            {
                "schema_version": SCHEMA_VERSION,
                "operation": journal["operation"],
                "operation_id": journal["operation_id"],
                "result": results.get(outcome or "", "failed-unrecovered") if recovered else "failed-unrecovered",
                "host_id": self.host().host_id,
                "timestamp": utc_now(),
                "error": str(error),
            }
        )
        if recovered:
            self.layout.journal.unlink(missing_ok=True)
        return recovered, error

    def require_uncommitted(self, journal: dict[str, Any], error: Exception) -> None:
        persisted = read_json(self.layout.journal) or journal
        checkpoint = persisted.get("checkpoint")
        if checkpoint in FINALIZABLE_CHECKPOINTS:
            raise CatalogError(
                f"{journal['operation']} {checkpoint} but finalization failed; run make recover: {error}"
            ) from error

    def finalize_transition(self, journal: dict[str, Any]) -> None:
        """Finishes a transition whose runtime was verified before the interruption (recovery path)."""
        active = journal.get("new_active")
        if not active:
            raise CatalogError("journal has no new active release to finalize")
        compose_file = self.verify_release_artifact(active, "finalized")
        if journal["operation"] == "rollback":
            self.writers_resumed()
        self.start_release(compose_file, active.get("search_aliases", {}))
        self.restore_release_state(active, journal.get("new_rollback"))
        self.complete_transition(journal)

    def verify_runtime(self, compose_file: Path) -> None:
        # Never `nginx -t` here: it binds the listening sockets and can race the starting master for port 80.
        domain = self.host().domain
        self.compose(
            compose_file,
            "exec",
            "-T",
            "django",
            "curl",
            "-fsS",
            "-H",
            f"Host: {domain}",
            "http://nginx/",
        )

    def publish_runtime(self, compose_file: Path) -> None:
        # Operations on the active release (backup, validate, start, stop, logs) use this copy.
        atomic_write(self.layout.canonical_compose, compose_file.read_bytes(), 0o600)

    def snapshot_logs(self, compose_file: Path, release: str) -> Path | None:
        """Recovery recreates the containers and discards their logs, so keep a copy first."""
        try:
            output = self.compose(compose_file, "logs", "--no-color", "--timestamps").stdout or ""
            path = self.layout.reports / f"activation-{release}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.log"
            atomic_write(path, output.encode(), 0o600)
        except Exception as error:
            log(f"WARNING: could not snapshot the candidate's logs: {error}")
            return None
        log(f"Candidate logs kept at {path}")
        return path

    def restore_runtime(self, active: dict[str, Any] | None, candidate_compose: Path) -> bool:
        try:
            if active:
                self.writers_resumed()
                self.start_release(self.verify_release_artifact(active, "active"), active.get("search_aliases", {}))
            else:
                self.compose(candidate_compose, "rm", "-s", "-f", capture=False, check=False)
            return True
        except Exception as error:
            log(f"ERROR: runtime recovery failed: {error}")
            return False

    def settle_failed_activation(
        self, active: dict[str, Any] | None, candidate: dict[str, Any], candidate_compose: Path
    ) -> str | None:
        """Returns how the runtime was settled, or None if that failed."""
        self.snapshot_logs(candidate_compose, candidate["release_id"])
        if active and candidate.get("migration_applied"):
            # The previous release may not match the migrated schema, so it stays stopped, as `start` requires.
            try:
                self.stop_writers(candidate_compose)
            except Exception as error:
                log(f"ERROR: stopping the candidate's writers failed: {error}")
                return None
            return "kept-down"
        if not self.restore_runtime(active, candidate_compose):
            return None
        if active:
            self.writers_resumed()
        return "restored-previous"

    def activate(self) -> dict[str, Any]:
        with self.locked():
            if self.layout.journal.exists():
                raise CatalogError("an unfinished transaction journal exists; run make recover")
            if not self.layout.candidate.exists():
                active = self.active_state()
                if active:
                    return {"phase": "activate", "ok": True, "already": True, "release_id": active["release_id"]}
            candidate = self.candidate_state()
            if candidate["migration_status"] != "succeeded":
                raise CatalogError("migrate must succeed before activate")
            if candidate["data_rebuild_status"] != "succeeded":
                raise CatalogError("rebuild must succeed before activate")
            self.require_writers_drained(candidate, self.active_state())
            compose_file = Path(candidate["compose_file"])
            self.manage(compose_file, "migrate", "--check")
            expected_aliases = candidate.get("search_aliases_after")
            if not isinstance(expected_aliases, dict) or not expected_aliases:
                raise CatalogError("candidate has no validated search alias snapshot")
            publishers = self.foreign_http_publishers()
            if publishers:
                raise CatalogError(
                    f"port {self.host().http_bind.rpartition(':')[2]} is published by {', '.join(publishers)}; "
                    "stop that stack before activation (runbook: production cutover)"
                )
            active = self.active_state()
            if active:
                self.verify_release_artifact(active, "active")
            rollback = read_json(self.layout.rollback)
            journal = {
                "operation": "deploy",
                "operation_id": candidate["operation_id"],
                "started_at": utc_now(),
                "checkpoint": "candidate-started",
                "candidate": candidate,
                "previous_active": active,
                "previous_rollback": rollback,
            }
            self.write_journal(journal)
            try:
                # A recovered earlier attempt restored the previous release's aliases, so the start switches them again.
                self.start_release(compose_file, expected_aliases, validate_search=True)
                new_active = {
                    "schema_version": SCHEMA_VERSION,
                    "host_id": self.host().host_id,
                    "release_id": candidate["release_id"],
                    "image": candidate["image"],
                    "bundle_revision": candidate["bundle_revision"],
                    "citation_revision": candidate["citation_revision"],
                    "manifest": candidate.get("manifest"),
                    "manifest_sha256": candidate.get("manifest_sha256"),
                    "compose_file": candidate["compose_file"],
                    "compose_sha256": candidate["compose_sha256"],
                    "release_dir": candidate["release_dir"],
                    "bundle_sha256": candidate["bundle_sha256"],
                    "support_images": candidate["support_images"],
                    "search_aliases": expected_aliases,
                    "deployed_at": utc_now(),
                    "operator": getpass.getuser(),
                }
                journal = self.update_journal(journal, "runtime-ready", new_active=new_active, new_rollback=active)
                self.commit_transition(journal)
            except Exception as error:
                self.require_uncommitted(journal, error)
                outcome = self.settle_failed_activation(active, candidate, compose_file)
                recovered, error = self.fail_transition(journal, error, active, rollback, outcome)
                if recovered and outcome == "kept-down":
                    raise CatalogError(
                        "activation failed after migrations were applied, so the previous release was not "
                        "restarted and the site stays down; fix the cause and rerun make activate, "
                        f"or follow the recovery policy: {error}"
                    ) from error
                raise CatalogError(f"activation failed; prior runtime recovered={recovered}: {error}") from error
            log(f"Activated {candidate['release_id']} on {self.host().host_id}")
            return {
                "phase": "activate",
                "ok": True,
                "release_id": candidate["release_id"],
                "image": candidate["image"],
                "manifest_sha256": candidate.get("manifest_sha256"),
                "previous_release": active["release_id"] if active else None,
            }

    def rollback_release(self) -> dict[str, Any]:
        """Returns to the previous release with search rebuilt by its own code from the current database.

        The previous generations are snapshots of an earlier database, so they are rebuilt while no writer runs;
        the site is unavailable for the duration of that rebuild."""
        with self.locked():
            if self.layout.journal.exists():
                raise CatalogError("an unfinished transaction journal exists; run make recover")
            active = require_json(self.layout.active)
            rollback = require_json(self.layout.rollback)
            self.require_schema_untouched_by_candidate()
            active_compose = self.verify_release_artifact(active, "active")
            compose_file = self.verify_release_artifact(rollback, "rollback")
            journal = {
                "operation": "rollback",
                "operation_id": uuid.uuid4().hex,
                "started_at": utc_now(),
                "checkpoint": "candidate-started",
                "previous_active": active,
                "previous_rollback": rollback,
            }
            self.write_journal(journal)
            try:
                self.stop_writers(active_compose)
                self.compose(compose_file, "up", "-d", "--wait", *DEPENDENCY_SERVICES, capture=False)
                aliases = self.rebuild_search(compose_file)
                self.writers_resumed()
                self.start_release(compose_file, aliases)
                rolled_back = dict(rollback)
                rolled_back.update(search_aliases=aliases, deployed_at=utc_now(), operator=getpass.getuser())
                journal = self.update_journal(journal, "runtime-ready", new_active=rolled_back, new_rollback=active)
                self.commit_transition(journal)
            except Exception as error:
                self.require_uncommitted(journal, error)
                outcome = "restored-previous" if self.restore_runtime(active, compose_file) else None
                if outcome:
                    self.writers_resumed()
                recovered, error = self.fail_transition(journal, error, active, rollback, outcome)
                raise CatalogError(f"rollback failed; active runtime recovered={recovered}: {error}") from error
            self.writers_resumed()
            log(f"Rolled back to {rollback['release_id']} with its search rebuilt")
            return {
                "phase": "rollback",
                "ok": True,
                "release_id": rollback["release_id"],
                "image": rollback["image"],
                "previous_release": active["release_id"],
                "aliases": aliases,
            }

    def recover(self) -> dict[str, Any]:
        with self.locked():
            journal = read_json(self.layout.journal)
            if journal is None:
                return {"phase": "recover", "ok": True, "already": True, "outcome": "nothing-to-recover"}
            if journal.get("checkpoint") in FINALIZABLE_CHECKPOINTS:
                self.finalize_transition(journal)
                log("Finalized the verified release and repaired its history")
                return {"phase": "recover", "ok": True, "outcome": "finalized", "operation": journal["operation"]}
            active = journal.get("previous_active")
            candidate_data = journal.get("candidate") or journal.get("previous_rollback")
            if not candidate_data:
                raise CatalogError("journal has no runtime artifact for recovery")
            candidate_compose = self.verify_release_artifact(candidate_data, "recovery")
            if journal["operation"] == "deploy":
                outcome = self.settle_failed_activation(active, candidate_data, candidate_compose)
            else:
                outcome = "restored-previous" if self.restore_runtime(active, candidate_compose) else None
                if outcome and active:
                    self.writers_resumed()
            if outcome is None:
                self.update_journal(journal, "unrecovered")
                raise CatalogError("automatic recovery failed; journal retained")
            previous_rollback = journal.get("previous_rollback")
            self.restore_release_state(active, previous_rollback)
            self.append_history_once(
                {
                    "schema_version": SCHEMA_VERSION,
                    "operation": "recover",
                    "operation_id": journal["operation_id"],
                    "result": "succeeded",
                    "outcome": outcome,
                    "host_id": self.host().host_id,
                    "timestamp": utc_now(),
                    "recovered_operation": journal["operation"],
                },
            )
            self.layout.journal.unlink(missing_ok=True)
            if outcome == "kept-down":
                log("Migrations were applied, so the previous release stays stopped; rerun make activate")
            else:
                log("Recovered the previous active runtime and state")
            return {"phase": "recover", "ok": True, "outcome": outcome, "operation": journal["operation"]}

    def start(self) -> dict[str, Any]:
        with self.locked():
            active = require_json(self.layout.active)
            self.require_schema_untouched_by_candidate()
            self.writers_resumed()
            self.compose(self.active_compose(), "up", "-d", "--no-build", "--wait", capture=False)
            return {"phase": "start", "ok": True, "release_id": active["release_id"]}

    def stop(self) -> dict[str, Any]:
        with self.locked():
            active = require_json(self.layout.active)
            self.compose(self.active_compose(), "stop", capture=False)
            return {"phase": "stop", "ok": True, "release_id": active["release_id"]}

    def logs(self) -> None:
        self.compose(self.active_compose(), "logs", "-f", capture=False)
