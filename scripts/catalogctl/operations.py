"""Validation, status, and the release report."""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .activation import ActivationOperations
from .common import CatalogError, atomic_json, log, read_json, require_json, utc_now
from .constants import APPLICATION_SERVICES, REQUIRED_SERVICES, SCHEMA_VERSION


class ReportingOperations(ActivationOperations):
    """Read-only views of the host for operators and the deployment adapter."""

    def running_containers(self, compose_file: Path) -> dict[str, dict[str, Any]]:
        ids = self.compose(compose_file, "ps", "--all", "--quiet").stdout.split()
        if not ids:
            return {}
        inspected = json.loads(self.command_output(["docker", "inspect", *ids]) or "[]")
        containers: dict[str, dict[str, Any]] = {}
        for item in inspected:
            labels = item.get("Config", {}).get("Labels") or {}
            service = labels.get("com.docker.compose.service")
            if service:
                containers[service] = {
                    "image": item.get("Config", {}).get("Image"),
                    "revision": labels.get("org.opencontainers.image.revision"),
                    "state": item.get("State", {}).get("Status"),
                    "health": (item.get("State", {}).get("Health") or {}).get("Status"),
                }
        return containers

    def validate(self) -> dict[str, Any]:
        with self.locked():
            active = require_json(self.layout.active)
            compose_file = self.active_compose()
            checks: dict[str, dict[str, Any]] = {}
            containers = self.running_containers(compose_file)
            for service in REQUIRED_SERVICES:
                container = containers.get(service)
                healthy = bool(
                    container
                    and container["state"] == "running"
                    and container["health"] in (None, "healthy")
                )
                checks[f"service:{service}"] = {"ok": healthy, "detail": container}
            for service in APPLICATION_SERVICES:
                container = containers.get(service) or {}
                checks[f"artifact:{service}"] = {
                    "ok": container.get("image") == active["image"]
                    and container.get("revision") == active["bundle_revision"],
                    "detail": {"running": container.get("image"), "revision": container.get("revision")},
                }
            support = set(active.get("support_images", []))
            for service in set(REQUIRED_SERVICES).difference(APPLICATION_SERVICES):
                image = (containers.get(service) or {}).get("image")
                checks[f"artifact:{service}"] = {"ok": image in support, "detail": {"running": image}}
            for name, action in (
                ("migrations", lambda: self.manage(compose_file, "migrate", "--check")),
                ("search", lambda: self.manage(compose_file, "validate_search_indexes")),
                ("http", lambda: self.verify_runtime(compose_file)),
            ):
                try:
                    action()
                    checks[name] = {"ok": True}
                except CatalogError as error:
                    checks[name] = {"ok": False, "detail": str(error)}
            ok = all(check["ok"] for check in checks.values())
            log(f"Validation {'passed' if ok else 'FAILED'} for {active['release_id']}")
            return {
                "phase": "validate",
                "ok": ok,
                "release_id": active["release_id"],
                "manifest_sha256": active.get("manifest_sha256"),
                "checks": checks,
            }

    def status(self) -> dict[str, Any]:
        host = self.host()
        active = self.active_state()
        rollback = read_json(self.layout.rollback)
        candidate = read_json(self.layout.candidate)
        journal = read_json(self.layout.journal)
        stages = (
            "restore_status",
            "drain_status",
            "migration_status",
            "migration_applied",
            "data_rebuild_status",
        )
        result: dict[str, Any] = {
            "phase": "status",
            "ok": True,
            "lock_protocol": "inherited-fd-v1",
            "host_id": host.host_id,
            "domain": host.domain,
            "project": host.project_name,
            "http_bind": host.http_bind,
            "active": {key: active.get(key) for key in ("release_id", "image", "bundle_revision", "manifest_sha256", "deployed_at")}
            if active
            else None,
            "rollback": {key: rollback.get(key) for key in ("release_id", "image")} if rollback else None,
            "candidate": {
                key: candidate.get(key)
                for key in ("release_id", "image", "bundle_revision", "manifest_sha256", *stages)
            }
            if candidate
            else None,
            "journal": {key: journal.get(key) for key in ("operation", "checkpoint")} if journal else None,
        }
        if active:
            with contextlib.suppress(CatalogError, json.JSONDecodeError):
                result["services"] = {
                    service: {"state": info["state"], "health": info["health"]}
                    for service, info in self.running_containers(self.active_compose()).items()
                }
        return result

    def release_report(self) -> dict[str, Any]:
        with self.locked():
            host = self.host()
            active = require_json(self.layout.active)
            compose_file = self.active_compose()
            user, database = self.db_identity(compose_file)
            settings_output = self.command_output(
                self.compose_command(
                    compose_file,
                    "run",
                    "--rm",
                    "--no-deps",
                    "django",
                    "python3",
                    "-c",
                    "import django; django.setup(); "
                    "from django.conf import settings; import psycopg2; "
                    "print(settings.EMAIL_BACKEND); print(psycopg2.__version__)",
                )
            ).splitlines()
            search_validation = (
                self.manage(compose_file, "validate_search_indexes", capture=True).stdout or ""
            ).strip()
            images = self.command_output(self.compose_command(compose_file, "config", "--images")).splitlines()
            report = {
                "schema_version": SCHEMA_VERSION,
                "phase": "release-report",
                "ok": True,
                "generated_at": utc_now(),
                "host_id": host.host_id,
                "domain": host.domain,
                "active": active,
                "rollback": read_json(self.layout.rollback),
                "candidate": read_json(self.layout.candidate),
                "service_images": images,
                "postgres": self.postgres_versions(compose_file, user, database),
                "database_counts": self.database_counts(compose_file, user, database),
                "email_backend": settings_output[0] if settings_output else "unknown",
                "psycopg2": settings_output[1] if len(settings_output) > 1 else "unknown",
                "search_aliases": self.alias_targets(compose_file),
                "search_validation": search_validation,
                "latest_backup": self.backup_status(),
                "warnings": ["Backups are on-host only; host or attached-volume loss is unrecoverable."],
            }
            path = self.layout.reports / f"release-{active['release_id']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
            atomic_json(path, report)
            report["path"] = str(path)
            log(f"Release report written: {path}")
            return report
