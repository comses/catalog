"""Where host state lives, and the fixed host identity."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .common import CatalogError
from .constants import BACKUP_DIR, BACKUP_MARKER, COMPOSE_PROJECT, HOST_DIR, HOST_DOMAINS, HOST_IDS


def valid_http_bind(value: str) -> bool:
    address, _, port = value.rpartition(":")
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        return False
    if address.startswith("[") and address.endswith("]"):
        address = address[1:-1]
    elif ":" in address:
        return False
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class Layout:
    root: Path
    backups: Path

    @classmethod
    def from_environment(cls) -> "Layout":
        return cls(
            Path(os.environ.get("CATALOG_HOST_DIR", HOST_DIR)).resolve(),
            Path(os.environ.get("CATALOG_BACKUP_DIR", BACKUP_DIR)).resolve(),
        )

    @property
    def system(self) -> bool:
        return self.root == HOST_DIR.resolve()

    @property
    def secrets(self) -> Path:
        return self.root / "secrets"

    @property
    def var(self) -> Path:
        return self.root / "deploy"

    @property
    def host_env(self) -> Path:
        return self.var / "host.env"

    @property
    def state(self) -> Path:
        return self.var / "state"

    @property
    def runtime(self) -> Path:
        return self.var / "runtime"

    @property
    def releases(self) -> Path:
        return self.var / "releases"

    @property
    def shared(self) -> Path:
        return self.var / "shared"

    @property
    def receipts(self) -> Path:
        return self.var / "receipts"

    @property
    def reports(self) -> Path:
        return self.var / "reports"

    @property
    def lock(self) -> Path:
        return self.backups / ".backup.lock"

    @property
    def backup_marker(self) -> Path:
        return self.backups / BACKUP_MARKER

    @property
    def backups_bind(self) -> Path:
        # The infrastructure binds the backups root here; containers mount shared/ as /shared.
        return self.shared / "backups"

    @property
    def active(self) -> Path:
        return self.state / "active.json"

    @property
    def rollback(self) -> Path:
        return self.state / "rollback.json"

    @property
    def candidate(self) -> Path:
        return self.state / "candidate.json"

    @property
    def journal(self) -> Path:
        return self.state / "journal.json"

    @property
    def history(self) -> Path:
        return self.state / "history.jsonl"

    @property
    def canonical_compose(self) -> Path:
        return self.runtime / "docker-compose.yml"


@dataclass(frozen=True)
class HostConfig:
    host_id: str
    environment: str
    project_name: str
    domain: str
    http_bind: str

    @classmethod
    def load(cls, layout: Layout) -> "HostConfig":
        values: dict[str, str] = {}
        try:
            lines = layout.host_env.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise CatalogError(f"cannot read {layout.host_env}: {error}") from error
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise CatalogError(f"malformed host identity line: {line}")
            key, value = line.split("=", 1)
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not value:
                raise CatalogError(f"malformed host identity line: {line}")
            values[key] = value
        required = {
            "CATALOG_HOST_ID",
            "CATALOG_ENV",
            "COMPOSE_PROJECT_NAME",
            "CATALOG_DOMAIN",
            "CATALOG_HTTP_BIND",
        }
        missing = sorted(required.difference(values))
        if missing:
            raise CatalogError(f"host identity is missing: {', '.join(missing)}")
        host_id = values["CATALOG_HOST_ID"]
        if host_id not in HOST_IDS or values["CATALOG_ENV"] != host_id:
            raise CatalogError("CATALOG_HOST_ID and CATALOG_ENV must be the same staging or prod value")
        if values["COMPOSE_PROJECT_NAME"] != COMPOSE_PROJECT:
            raise CatalogError(f"COMPOSE_PROJECT_NAME must be {COMPOSE_PROJECT}")
        if values["CATALOG_DOMAIN"] != HOST_DOMAINS[host_id]:
            raise CatalogError(f"CATALOG_DOMAIN does not match fixed {host_id} identity")
        if not valid_http_bind(values["CATALOG_HTTP_BIND"]):
            raise CatalogError("CATALOG_HTTP_BIND must be an explicit <address>:<port>, such as 127.0.0.1:80")
        return cls(
            host_id,
            values["CATALOG_ENV"],
            values["COMPOSE_PROJECT_NAME"],
            values["CATALOG_DOMAIN"],
            values["CATALOG_HTTP_BIND"],
        )
