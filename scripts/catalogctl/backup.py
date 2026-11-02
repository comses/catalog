"""The application-owned backups: running one, and reading the receipts and marker it writes."""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .common import CatalogError, atomic_json, atomic_write, fsync_directory, log, parse_utc, read_json, require_json, sha256_file
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
            reference_time = cutoff or datetime.now(timezone.utc)
            if not timedelta(0) <= reference_time - created <= timedelta(hours=24):
                continue
            artifact = self.layout.backups / receipt["archive"]
            if artifact.is_file() and sha256_file(artifact) == receipt["sha256"]:
                return receipt
        raise CatalogError(
            "migration requires a verified backup of the active release, under 24 hours old "
            "at selection and taken before any earlier migration attempt"
        )

    def retained_backup_directory(self, reference: dict[str, Any]):
        token = reference.get("directory", "")
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            raise CatalogError("invalid retained backup directory")
        parent = self.layout.backups / ".migration-backups"
        directory = parent / token
        if parent.is_symlink() or directory.is_symlink():
            raise CatalogError("retained backup directories must not be symlinks")
        return directory

    def verify_migration_backup(self, reference: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
        directory = self.retained_backup_directory(reference)
        receipt = reference["receipt"]
        if not self.receipt_matches(receipt, active):
            raise CatalogError("retained migration backup belongs to another release")
        for name in ("archive.dump", "receipt.json", "archive.dump.sha256"):
            path = directory / name
            if not path.exists() or not stat.S_ISREG(path.lstat().st_mode):
                raise CatalogError(f"retained migration backup is missing or unsafe: {path}")
        if (require_json(directory / "receipt.json") != receipt
                or sha256_file(directory / "archive.dump") != receipt["sha256"]
                or (directory / "archive.dump.sha256").read_text() != receipt["sha256"] + "  archive.dump\n"):
            raise CatalogError("retained migration backup failed integrity verification")
        return receipt

    def retain_migration_backup(self, receipt: dict[str, Any]) -> dict[str, Any]:
        reference = {"directory": uuid.uuid4().hex, "receipt": receipt}
        directory = self.retained_backup_directory(reference)
        directory.parent.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory.parent, 0o700)
        directory.mkdir(mode=0o700)
        archive = receipt["archive"]
        if not isinstance(archive, str) or not re.fullmatch(r"[^/\\]+\.dump", archive):
            raise CatalogError("invalid backup archive name")
        source = self.layout.backups / archive
        if not stat.S_ISREG(source.lstat().st_mode):
            raise CatalogError("migration backup must be a regular file")
        os.link(source, directory / "archive.dump", follow_symlinks=False)
        atomic_json(directory / "receipt.json", receipt)
        atomic_write(directory / "archive.dump.sha256", (receipt["sha256"] + "  archive.dump\n").encode())
        with (directory / "archive.dump").open("rb") as archive_file:
            os.fsync(archive_file.fileno())
        fsync_directory(directory)
        fsync_directory(directory.parent)
        fsync_directory(self.layout.backups)
        return reference

    def release_migration_backup(self, candidate: dict[str, Any]) -> None:
        reference = candidate.get("migration_backup")
        if not reference:
            return
        directory = self.retained_backup_directory(reference)
        if not directory.exists():
            return
        for name in ("archive.dump", "receipt.json", "archive.dump.sha256"):
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()
        fsync_directory(directory.parent)

    def select_migration_backup(self, candidate: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
        reference = candidate.get("migration_backup")
        if reference and candidate.get("migration_started_at"):
            self.verify_migration_backup(reference, active)
            return reference
        receipt = self.latest_valid_backup(active, before=candidate.get("migration_started_at"))
        reference = self.retain_migration_backup(receipt)
        self.verify_migration_backup(reference, active)
        # Retention may take time; an unstarted attempt still needs a fresh backup.
        if not candidate.get("migration_started_at"):
            age = datetime.now(timezone.utc) - parse_utc(receipt["created_at"])
            if not timedelta(0) <= age <= timedelta(hours=24):
                raise CatalogError("selected backup expired before migration started; take a fresh backup")
        return reference
