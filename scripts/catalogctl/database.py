"""PostgreSQL access through the database container, and the fresh-host restore."""

from __future__ import annotations

import contextlib
import lzma
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import CatalogError, atomic_json, log, read_json, sha256_file, utc_now
from .constants import SAFE_IDENTIFIER_RE, SCHEMA_VERSION
from .host import HostOperations


def validate_identifier(value: str) -> str:
    if not SAFE_IDENTIFIER_RE.fullmatch(value):
        raise CatalogError(f"unsafe PostgreSQL identifier: {value}")
    return value


class DatabaseOperations(HostOperations):
    """Talks to PostgreSQL through the database container's own client tools."""

    def db_identity(self, compose_file: Path) -> tuple[str, str]:
        output = self.command_output(
            self.compose_command(
                compose_file,
                "exec",
                "-T",
                "db",
                "sh",
                "-c",
                'printf "%s\\n%s\\n" "$POSTGRES_USER" "$POSTGRES_DB"',
            )
        )
        lines = output.splitlines()
        if len(lines) != 2:
            raise CatalogError("could not read database identity from the container")
        return validate_identifier(lines[0]), validate_identifier(lines[1])

    def psql(self, compose_file: Path, user: str, database: str, sql: str) -> str:
        return self.command_output(
            self.compose_command(
                compose_file,
                "exec",
                "-T",
                "db",
                "psql",
                "--username",
                user,
                "--dbname",
                database,
                "--tuples-only",
                "--no-align",
                "--set",
                "ON_ERROR_STOP=1",
                "--command",
                sql,
            )
        )

    def database_counts(self, compose_file: Path, user: str, database: str) -> dict[str, int]:
        exists = self.psql(
            compose_file,
            user,
            database,
            "SELECT to_regclass('public.citation_publication') IS NOT NULL;",
        )
        if exists != "t":
            return {"citation_publication": 0, "primary_publication": 0}
        output = self.psql(
            compose_file,
            user,
            database,
            "SELECT count(*), count(*) FILTER (WHERE is_primary) FROM citation_publication;",
        )
        total, primary = output.split("|", 1)
        return {"citation_publication": int(total), "primary_publication": int(primary)}

    def postgres_versions(self, compose_file: Path, user: str, database: str) -> dict[str, str]:
        return {
            "server": self.psql(compose_file, user, database, "SHOW server_version;"),
            "pg_dump": self.command_output(
                self.compose_command(compose_file, "exec", "-T", "db", "pg_dump", "--version")
            ),
            "pg_restore": self.command_output(
                self.compose_command(compose_file, "exec", "-T", "db", "pg_restore", "--version")
            ),
        }

    @staticmethod
    def dump_kind(path: Path) -> str:
        if path.name.endswith(".sql.xz"):
            return "sql-xz"
        if path.suffix == ".sql":
            return "sql"
        if path.suffix == ".dump":
            return "custom"
        raise CatalogError("DUMP must end in .dump, .sql, or .sql.xz")

    @staticmethod
    def verify_dump_checksum(path: Path) -> None:
        checksum_path = Path(f"{path}.sha256")
        if not checksum_path.exists():
            return
        fields = checksum_path.read_text(encoding="utf-8").strip().split()
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            raise CatalogError(f"invalid checksum file: {checksum_path}")
        recorded_name = fields[1].lstrip("*")
        if recorded_name != path.name:
            raise CatalogError(f"checksum file names another artifact: {recorded_name}")
        if sha256_file(path) != fields[0]:
            raise CatalogError(f"dump checksum does not match: {path}")

    @staticmethod
    def validate_plain_dump(path: Path, kind: str) -> None:
        opener = lzma.open if kind == "sql-xz" else open
        pattern = re.compile(r"^(?:CREATE|DROP|ALTER)\s+DATABASE\b|^\\connect\b", re.I)
        try:
            with opener(path, "rt", encoding="utf-8", errors="replace") as source:
                for line in source:
                    if pattern.search(line.strip()):
                        raise CatalogError("plain SQL dump contains database-level commands")
        except lzma.LZMAError as error:
            raise CatalogError(f"invalid xz dump: {error}") from error

    def terminate_connections(self, compose_file: Path, user: str, database: str) -> None:
        self.psql(
            compose_file,
            user,
            "postgres",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{database}' AND pid <> pg_backend_pid();",
        )

    def restore(self, dump: Path, confirm: str) -> dict[str, Any]:
        dump = dump.expanduser().resolve()
        if not dump.is_file() or dump.stat().st_size == 0:
            raise CatalogError(f"dump is missing or empty: {dump}")
        self.verify_dump_checksum(dump)
        kind = self.dump_kind(dump)
        if kind != "custom":
            self.validate_plain_dump(dump, kind)
        with self.locked():
            if self.layout.active.exists():
                raise CatalogError("this restore command is limited to a fresh host with no active release")
            candidate = self.candidate_state()
            if candidate.get("restore_status") != "pending":
                raise CatalogError(f"candidate restore status is {candidate.get('restore_status')}")
            compose_file = Path(candidate["compose_file"])
            self.compose(compose_file, "up", "-d", "--wait", "db", capture=False)
            user, database = self.db_identity(compose_file)
            if confirm != database:
                raise CatalogError(f"set CONFIRM={database} to authorize the database swap")
            finished = self.reconcile_interrupted_restore(candidate, compose_file, user, database)
            if finished:
                return finished
            candidate = self.candidate_state()
            counts = self.database_counts(compose_file, user, database)
            if counts["citation_publication"]:
                raise CatalogError(
                    f"{database} already contains {counts['citation_publication']} publications; restore requires "
                    "the empty database of a fresh host, so investigate and move that database aside first"
                )
            candidate = self.update_candidate(
                candidate,
                restore_status="in_progress",
                restore_started_at=utc_now(),
                restore_artifact=str(dump),
                restore_sha256=sha256_file(dump),
            )
            suffix = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{os.getpid()}"
            temporary_database = validate_identifier(f"{database}_restore_{suffix}")
            old_database = validate_identifier(f"{database}_before_{suffix}")
            # Recorded before anything exists, so an interruption at any point can be reconciled on the next run.
            candidate = self.update_candidate(
                candidate,
                restore_temporary_database=temporary_database,
                restore_retained_database=old_database,
            )
            try:
                self.psql(
                    compose_file,
                    user,
                    "postgres",
                    f'CREATE DATABASE "{temporary_database}" OWNER "{user}";',
                )
                if kind == "custom":
                    with dump.open("rb") as source:
                        self.runner.from_file(
                            self.compose_command(
                                compose_file,
                                "exec",
                                "-T",
                                "db",
                                "pg_restore",
                                "--username",
                                user,
                                "--dbname",
                                temporary_database,
                                "--exit-on-error",
                                "--no-owner",
                                "--no-privileges",
                            ),
                            source,
                        )
                else:
                    command = self.compose_command(
                        compose_file,
                        "exec",
                        "-T",
                        "db",
                        "psql",
                        "--username",
                        user,
                        "--dbname",
                        temporary_database,
                        "--set",
                        "ON_ERROR_STOP=1",
                        "--quiet",
                    )
                    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=sys.stderr)
                    assert process.stdin is not None
                    opener = lzma.open if kind == "sql-xz" else open
                    with opener(dump, "rb") as source:
                        shutil.copyfileobj(source, process.stdin)
                    process.stdin.close()
                    if process.wait() != 0:
                        raise CatalogError("plain SQL restore failed")
                counts = self.database_counts(compose_file, user, temporary_database)
                if counts["citation_publication"] <= 0:
                    raise CatalogError("restored database contains no citation publications")
                invalid_constraints = self.psql(
                    compose_file,
                    user,
                    temporary_database,
                    "SELECT count(*) FROM pg_constraint WHERE NOT convalidated;",
                )
                if int(invalid_constraints) != 0:
                    raise CatalogError("restored database has unvalidated constraints")
                # The receipt and the swap's names are on disk before any rename, so an interrupted
                # record can be finished later instead of leaving a restored database unrecorded.
                receipt_path = self.write_restore_receipt(candidate, compose_file, user, dump, database, old_database, counts)
                candidate = self.update_candidate(candidate, restore_receipt=str(receipt_path))
                self.terminate_connections(compose_file, user, database)
                self.terminate_connections(compose_file, user, temporary_database)
                self.psql(
                    compose_file,
                    user,
                    "postgres",
                    f'ALTER DATABASE "{database}" RENAME TO "{old_database}";',
                )
                try:
                    self.psql(
                        compose_file,
                        user,
                        "postgres",
                        f'ALTER DATABASE "{temporary_database}" RENAME TO "{database}";',
                    )
                except Exception:
                    self.psql(
                        compose_file,
                        user,
                        "postgres",
                        f'ALTER DATABASE "{old_database}" RENAME TO "{database}";',
                    )
                    raise
            except Exception as error:
                with contextlib.suppress(Exception):
                    self.terminate_connections(compose_file, user, temporary_database)
                    self.psql(
                        compose_file,
                        user,
                        "postgres",
                        f'DROP DATABASE IF EXISTS "{temporary_database}";',
                    )
                self.update_candidate(
                    candidate,
                    restore_status="failed",
                    restore_failed_at=utc_now(),
                    restore_error=str(error),
                )
                raise
            self.update_candidate(candidate, restore_status="succeeded")
            log(f"Restore complete: {database} contains {counts['citation_publication']} publications")
            return {
                "phase": "restore",
                "ok": True,
                "database": database,
                "retained_database": old_database,
                "counts": counts,
                "sha256": candidate["restore_sha256"],
                "receipt": str(receipt_path),
            }

    def write_restore_receipt(
        self, candidate: dict[str, Any], compose_file: Path, user: str, dump: Path,
        database: str, retained_database: str, counts: dict[str, int],
    ) -> Path:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "kind": "restore",
            "host_id": self.host().host_id,
            "created_at": utc_now(),
            "artifact": str(dump),
            "bytes": dump.stat().st_size,
            "sha256": sha256_file(dump),
            "database": database,
            "retained_database": retained_database,
            "counts": counts,
            "postgres": self.postgres_versions(compose_file, user, database),
            "release_id": candidate["release_id"],
        }
        receipt_path = self.layout.receipts / "restores" / f"restore-{candidate['release_id']}.json"
        atomic_json(receipt_path, receipt)
        return receipt_path

    def database_exists(self, compose_file: Path, user: str, database: str) -> bool:
        return self.psql(
            compose_file, user, "postgres", f"SELECT count(*) FROM pg_database WHERE datname = '{database}';"
        ) == "1"

    def reconcile_interrupted_restore(
        self, candidate: dict[str, Any], compose_file: Path, user: str, database: str
    ) -> dict[str, Any] | None:
        """Settles what an interrupted restore left behind before a new attempt starts.

        The temporary and retained names are recorded before anything is created, so each boundary is recognisable:
        a populated temporary copy with no swap started is dropped, a swap that lost its second rename is finished,
        and a swap that completed but was never recorded is recorded."""
        temporary = candidate.get("restore_temporary_database")
        retained = candidate.get("restore_retained_database")
        if not temporary and not retained:
            return None
        target_exists = self.database_exists(compose_file, user, database)
        temporary_exists = bool(temporary) and self.database_exists(compose_file, user, temporary)
        retained_exists = bool(retained) and self.database_exists(compose_file, user, retained)
        if retained_exists and not target_exists and temporary_exists:
            self.psql(compose_file, user, "postgres", f'ALTER DATABASE "{temporary}" RENAME TO "{database}";')
            log(f"Finished the interrupted database swap: {temporary} is now {database}")
            target_exists, temporary_exists = True, False
        if retained_exists and target_exists:
            counts = self.database_counts(compose_file, user, database)
            finished = self.finish_interrupted_restore(candidate, compose_file, user, counts)
            if finished:
                return finished
        if temporary_exists and not retained_exists:
            self.terminate_connections(compose_file, user, temporary)
            self.psql(compose_file, user, "postgres", f'DROP DATABASE IF EXISTS "{temporary}";')
            log(f"Dropped the unfinished restore database {temporary}")
            self.update_candidate(candidate, restore_temporary_database=None, restore_retained_database=None)
        return None

    def finish_interrupted_restore(
        self, candidate: dict[str, Any], compose_file: Path, user: str, counts: dict[str, int]
    ) -> dict[str, Any] | None:
        """A restore whose database swap happened but whose success was never recorded is recognised and finished."""
        receipt_path = candidate.get("restore_receipt")
        retained = candidate.get("restore_retained_database")
        receipt = read_json(Path(receipt_path)) if receipt_path else None
        if not receipt or not retained or receipt.get("counts") != counts:
            return None
        if not self.database_exists(compose_file, user, retained):
            return None
        self.update_candidate(candidate, restore_status="succeeded")
        log(f"Restore had completed before its record was written; recorded now ({receipt['database']})")
        return {
            "phase": "restore",
            "ok": True,
            "already": True,
            "database": receipt["database"],
            "retained_database": retained,
            "counts": counts,
            "sha256": receipt["sha256"],
            "receipt": str(receipt_path),
        }
