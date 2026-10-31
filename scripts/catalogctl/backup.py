"""The application-owned backups: running one, and reading the receipts and marker it writes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .common import CatalogError, log, parse_utc, read_json, require_json, sha256_file
from .database import DatabaseOperations
from .manifest import release_id


class BackupOperations(DatabaseOperations):
    """Delegates backups to the application and trusts only what it can verify on the host."""

    def backup(self) -> dict[str, Any]:
        """Runs the application's verified backup; its command holds .backup.lock, so this phase does not."""
        active = require_json(self.layout.active)
        compose_file = self.active_compose()
        output = (self.manage(compose_file, "backup_database", "--wait", capture=True).stdout or "").strip()
        try:
            result = json.loads(output[output.index("{"):])
        except (ValueError, json.JSONDecodeError) as error:
            raise CatalogError(f"backup_database printed no JSON result: {output[-500:]}") from error
        receipt = self.backup_receipt(result["archive"])
        artifact = self.layout.backups / receipt["archive"]
        if not artifact.is_file() or sha256_file(artifact) != receipt["sha256"]:
            raise CatalogError(f"backup artifact does not match its receipt: {artifact}")
        if not self.receipt_matches(receipt, active):
            raise CatalogError(
                f"backup receipt names {receipt.get('revision')} {receipt.get('image')}, not the active release"
            )
        result.update(path=str(artifact), release_id=active["release_id"])
        log(f"Backup created and verified: {artifact}")
        return result

    def backup_receipts(self) -> list[dict[str, Any]]:
        """Receipts the application wrote beside its dumps, newest first."""
        receipts = []
        for path in sorted(self.layout.backups.glob("*.dump.json"), reverse=True):
            try:
                receipt = read_json(path)
            except CatalogError as error:
                log(f"WARNING: ignoring {path}: {error}")
                continue
            if receipt:
                receipts.append(receipt)
        return receipts

    def backup_receipt(self, archive: str) -> dict[str, Any]:
        return require_json(self.layout.backups / f"{archive}.json")

    @staticmethod
    def receipt_matches(receipt: dict[str, Any], release: dict[str, Any]) -> bool:
        return (
            receipt.get("revision") == release.get("bundle_revision")
            and receipt.get("image") == release.get("image")
        )

    def backup_marker_archive(self) -> str | None:
        try:
            lines = self.layout.backup_marker.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        values = dict(line.split("=", 1) for line in lines if "=" in line)
        return values.get("archive")

    def backup_status(self, max_age: int | None = None) -> dict[str, Any]:
        receipts = self.backup_receipts()
        if not receipts:
            return {"phase": "backup-status", "ok": False, "error": "no backup receipt exists"}
        receipt = receipts[0]
        artifact = self.layout.backups / receipt["archive"]
        verified = artifact.is_file() and sha256_file(artifact) == receipt["sha256"]
        marker_matches = self.backup_marker_archive() == receipt["archive"]
        age = int((datetime.now(timezone.utc) - parse_utc(receipt["created_at"])).total_seconds())
        return {
            "phase": "backup-status",
            "ok": verified and marker_matches and (max_age is None or age <= max_age),
            "archive": artifact.name,
            "path": str(artifact),
            "sha256": receipt["sha256"],
            "verified": verified,
            "marker_matches": marker_matches,
            "completed_at": receipt["created_at"],
            "age_seconds": age,
            "max_age_seconds": max_age,
            "release_id": release_id(receipt.get("revision"), receipt.get("image")),
        }

    def latest_valid_backup(self, active: dict[str, Any], *, before: str | None = None) -> dict[str, Any]:
        cutoff = parse_utc(before) if before else None
        for receipt in self.backup_receipts():
            if not self.receipt_matches(receipt, active):
                continue
            created = parse_utc(receipt["created_at"])
            if cutoff and created >= cutoff:
                continue
            if datetime.now(timezone.utc) - created > timedelta(hours=24):
                continue
            artifact = self.layout.backups / receipt["archive"]
            if artifact.is_file() and sha256_file(artifact) == receipt["sha256"]:
                return receipt
        raise CatalogError(
            "migration requires a verified backup of the active release, under 24 hours old "
            "and taken before any earlier migration attempt"
        )
