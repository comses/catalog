"""Elasticsearch alias generations and the search rebuild."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from .backup import BackupOperations
from .common import CatalogError, log, utc_now
from .constants import DEPENDENCY_SERVICES, MANAGED_ALIASES


class SearchOperations(BackupOperations):
    """Search generations are rebuilt beside the live ones and switched atomically by alias."""

    def restore_active_aliases(self, compose_file: Path) -> None:
        active = self.active_state()
        if active and active.get("search_aliases"):
            # Rebuild retains the current targets; these must be the release recovery would restart.
            self.set_alias_targets(compose_file, active["search_aliases"])

    def rebuild_search(self, compose_file: Path) -> dict[str, str]:
        """Rebuilds search and visualization with the release's code while preserving active recovery targets."""
        self.restore_active_aliases(compose_file)
        self.manage(compose_file, "rebuild_es_index")
        self.manage(compose_file, "validate_search_indexes")
        self.manage(compose_file, "populate_visualization_cache", "--clear")
        after = self.alias_targets(compose_file)
        if not after:
            raise CatalogError("search rebuild produced no managed aliases")
        return after

    def alias_targets(self, compose_file: Path) -> dict[str, str]:
        result = self.compose(
            compose_file,
            "exec",
            "-T",
            "elasticsearch",
            "curl",
            "-fsS",
            "http://localhost:9200/_alias",
        )
        payload = json.loads(result.stdout or "{}")
        targets: dict[str, str] = {}
        for index_name, index_data in payload.items():
            for alias in index_data.get("aliases", {}):
                if alias in MANAGED_ALIASES or alias.startswith("autocomplete_"):
                    targets[alias] = index_name
        return targets

    def set_alias_targets(self, compose_file: Path, targets: dict[str, str]) -> None:
        current = self.alias_targets(compose_file)
        actions: list[dict[str, dict[str, str]]] = []
        for alias, index_name in current.items():
            if alias in targets or alias in MANAGED_ALIASES or alias.startswith("autocomplete_"):
                actions.append({"remove": {"index": index_name, "alias": alias}})
        for alias, index_name in targets.items():
            actions.append({"add": {"index": index_name, "alias": alias}})
        if not actions:
            return
        body = json.dumps({"actions": actions})
        self.compose(
            compose_file,
            "exec",
            "-T",
            "elasticsearch",
            "curl",
            "-fsS",
            "-XPOST",
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            body,
            "http://localhost:9200/_aliases",
        )

    def rebuild(self) -> dict[str, Any]:
        with self.locked():
            candidate = self.candidate_state()
            if candidate["migration_status"] != "succeeded":
                raise CatalogError("migrate must succeed before rebuild")
            if candidate["data_rebuild_status"] == "succeeded":
                return {
                    "phase": "rebuild",
                    "ok": True,
                    "already": True,
                    "aliases": candidate.get("search_aliases_after", {}),
                }
            if candidate["data_rebuild_status"] != "pending":
                raise CatalogError(f"candidate rebuild status is {candidate['data_rebuild_status']}")
            self.require_writers_drained(candidate, self.active_state())
            compose_file = Path(candidate["compose_file"])
            self.compose(compose_file, "up", "-d", "--wait", *DEPENDENCY_SERVICES, capture=False)
            self.restore_active_aliases(compose_file)
            before = self.alias_targets(compose_file)
            candidate = self.update_candidate(
                candidate,
                data_rebuild_status="in_progress",
                search_aliases_before=before,
                data_rebuild_started_at=utc_now(),
            )
            try:
                after = self.rebuild_search(compose_file)
            except Exception as error:
                with contextlib.suppress(Exception):
                    self.set_alias_targets(compose_file, before)
                self.update_candidate(
                    candidate,
                    data_rebuild_status="failed",
                    data_rebuild_failed_at=utc_now(),
                    data_rebuild_error=str(error),
                )
                raise
            self.update_candidate(
                candidate,
                data_rebuild_status="succeeded",
                data_rebuild_completed_at=utc_now(),
                search_aliases_after=after,
            )
            log("Search indexes and visualization cache rebuilt and validated")
            return {"phase": "rebuild", "ok": True, "aliases": after}
