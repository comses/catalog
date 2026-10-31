"""Operator-run host setup: storage preparation and preflight, configuration, and the host check."""

from __future__ import annotations

import configparser
import getpass
import grp
import io
import os
import shutil
import stat
import string
import sys
import tarfile
from pathlib import Path
from typing import Any

from .common import CatalogError, atomic_write, log, read_json
from .constants import CANONICAL_CHECKOUT, COMPOSE_PROJECT, DATABASE_NAME, DEFAULT_HTTP_BIND, HOST_DOMAINS, HOST_IDS, MAX_MAP_COUNT, MAX_MAP_COUNT_PATH, OPERATORS_GROUP, SRV_ROOT
from .core import ControllerBase
from .layout import HostConfig, valid_http_bind


def import_settings(config_text: str, source: Path) -> tuple[str, list[str]]:
    """Copies an existing installation's values for the template's keys, except the database's."""
    old = configparser.ConfigParser(interpolation=None)
    try:
        with source.open(encoding="utf-8") as handle:
            old.read_file(handle)
    except (OSError, configparser.Error) as error:
        raise CatalogError(f"cannot read settings to import from {source}: {error}") from error
    new = configparser.ConfigParser(interpolation=None)
    new.optionxform = str  # type: ignore[assignment,method-assign]
    new.read_string(config_text)
    imported = []
    for section in new.sections():
        if section == "db" or not old.has_section(section):
            continue
        for option in new.options(section):
            if old.has_option(section, option):
                new.set(section, option, old.get(section, option))
                imported.append(f"{section}.{option}")
    buffer = io.StringIO()
    new.write(buffer)
    return buffer.getvalue(), imported


class HostOperations(ControllerBase):
    """Host setup an operator runs without root; the infrastructure owns everything that needs it."""

    def require_operator(self) -> str:
        if os.geteuid() == 0:
            raise CatalogError("run this as the deployment operator, not root; root steps on a host belong to the infrastructure")
        return getpass.getuser()

    def private_directories(self) -> tuple[Path, ...]:
        return (
            self.layout.secrets,
            self.layout.var,
            self.layout.state,
            self.layout.runtime,
            self.layout.releases,
            self.layout.shared,
            self.layout.shared / "mail",
            self.layout.receipts / "restores",
            self.layout.reports,
        )

    def storage_prepare(self) -> dict[str, Any]:
        """Creates the operator-owned private directories; the backups root is the infrastructure's."""
        operator = self.require_operator()
        for directory in self.private_directories():
            if directory.is_symlink():
                raise CatalogError(f"refusing to prepare a symlink: {directory}")
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        if not self.layout.system:
            # Outside a managed host nothing binds the backups root, so stand in for the infrastructure.
            self.layout.backups.mkdir(parents=True, exist_ok=True)
        log(f"Prepared {self.layout.root} for {operator}")
        return {
            "phase": "storage-prepare",
            "ok": True,
            "operator": operator,
            "root": str(self.layout.root),
            "backups": str(self.layout.backups),
        }

    def require_directory(self, path: Path, *, hint: str) -> None:
        if path.is_symlink():
            raise CatalogError(f"{path} must not be a symlink")
        if not path.is_dir():
            raise CatalogError(f"{path} is missing; {hint}")

    def mount_target(self, path: Path) -> str:
        return self.command_output(["findmnt", "-n", "-o", "TARGET", "-T", str(path)])

    def require_writable(self, path: Path) -> None:
        probe = path / f".storage-preflight-probe.{os.getpid()}"
        try:
            probe.touch()
        except OSError as error:
            raise CatalogError(f"{path} is not writable by {getpass.getuser()}: {error}") from error
        finally:
            probe.unlink(missing_ok=True)

    def storage_preflight(self) -> dict[str, Any]:
        """Verifies the host layout the phases rely on; changes nothing."""
        system = self.layout.system
        if system:
            if self.root != CANONICAL_CHECKOUT:
                raise CatalogError(f"run the controller from the canonical checkout {CANONICAL_CHECKOUT}")
            mounted = self.command_output(["findmnt", "-n", "-o", "TARGET", "--mountpoint", str(SRV_ROOT)])
            if mounted != str(SRV_ROOT):
                raise CatalogError(f"{SRV_ROOT} is not a mountpoint; the infrastructure mounts the persistent volume there")
        for directory in self.private_directories():
            self.require_directory(directory, hint="run make storage-prepare")
        if stat.S_IMODE(self.layout.secrets.stat().st_mode) & 0o077:
            raise CatalogError(f"{self.layout.secrets} must be owner-only (0700)")
        backups = self.layout.backups
        self.require_directory(backups, hint="the infrastructure creates and binds this backups root")
        mode = stat.S_IMODE(backups.stat().st_mode)
        if mode & 0o002:
            raise CatalogError(f"{backups} must not be world-writable")
        if mode & 0o020 and backups.stat().st_gid not in self.collaborative_gids():
            raise CatalogError(f"{backups} is group-writable by an unexpected group")
        self.require_writable(backups)
        if system:
            if self.mount_target(backups) == "/":
                raise CatalogError(f"{backups} is on the root filesystem, not the persistent volume")
            bind = self.layout.backups_bind
            self.require_directory(bind, hint="the infrastructure binds the backups root onto it")
            if (backups.stat().st_dev, backups.stat().st_ino) != (bind.stat().st_dev, bind.stat().st_ino):
                raise CatalogError(f"{bind} is not the infrastructure's bind of {backups}")
        if MAX_MAP_COUNT_PATH.exists() and int(MAX_MAP_COUNT_PATH.read_text().strip()) < MAX_MAP_COUNT:
            raise CatalogError(f"vm.max_map_count must be at least {MAX_MAP_COUNT}; the infrastructure sets it")
        log(f"Storage preflight passed for {self.layout.root}")
        return {
            "phase": "storage-preflight",
            "ok": True,
            "root": str(self.layout.root),
            "backups": str(backups),
            "bind": str(self.layout.backups_bind) if system else None,
        }

    @staticmethod
    def collaborative_gids() -> set[int]:
        gids = {os.getgid()}
        try:
            gids.add(grp.getgrnam(OPERATORS_GROUP).gr_gid)
        except KeyError:
            pass
        return gids

    def configure(
        self,
        host_id: str,
        http_bind: str | None = None,
        import_config: Path | None = None,
    ) -> dict[str, Any]:
        """Writes the fixed host identity and generates the secrets once."""
        if host_id not in HOST_IDS:
            raise CatalogError("HOST_ID must be staging or prod")
        if http_bind is not None and not valid_http_bind(http_bind):
            raise CatalogError("HTTP_BIND must be an explicit <address>:<port>, such as 127.0.0.1:80")
        if import_config is not None and (self.layout.secrets / "config.ini").exists():
            raise CatalogError("secrets already exist; edit their config.ini instead of importing settings")
        self.storage_prepare()

        new_bind = http_bind or DEFAULT_HTTP_BIND
        if self.layout.host_env.exists():
            existing = HostConfig.load(self.layout)
            if existing.host_id != host_id:
                raise CatalogError("host identity is immutable and does not match HOST_ID")
            new_bind = http_bind if http_bind and http_bind != existing.http_bind else None
        if new_bind:
            host_payload = (
                f"CATALOG_HOST_ID={host_id}\n"
                f"CATALOG_ENV={host_id}\n"
                f"COMPOSE_PROJECT_NAME={COMPOSE_PROJECT}\n"
                f"CATALOG_DOMAIN={HOST_DOMAINS[host_id]}\n"
                f"CATALOG_HTTP_BIND={new_bind}\n"
            )
            atomic_write(self.layout.host_env, host_payload.encode(), 0o640)
            log(f"Nginx will publish HTTP on {new_bind}")

        password_path = self.layout.secrets / "postgres_password"
        config_path = self.layout.secrets / "config.ini"
        imported: list[str] = []
        if not password_path.exists() and not config_path.exists():
            import secrets

            password = secrets.token_urlsafe(45)
            secret_key = secrets.token_urlsafe(75)
            template_path = self.root / "deploy" / "conf" / "config.template.ini"
            template = string.Template(template_path.read_text(encoding="utf-8"))
            config = template.substitute(
                DB_NAME=DATABASE_NAME,
                DB_USER="catalog",
                DB_PASSWORD=password,
                SECRET_KEY=secret_key,
            )
            if import_config is not None:
                config, imported = import_settings(config, import_config)
            atomic_write(password_path, f"{password}\n".encode(), 0o600)
            atomic_write(config_path, config.encode(), 0o600)
        elif not password_path.exists() or not config_path.exists():
            raise CatalogError("secret configuration is incomplete; refusing to replace either file")
        log(f"Configured {host_id}; review {config_path} before running host-check")
        return {
            "phase": "configure",
            "ok": True,
            "host_id": host_id,
            "http_bind": HostConfig.load(self.layout).http_bind,
            "config": str(config_path),
            "imported": imported,
        }

    def host_check(self) -> dict[str, Any]:
        host = self.host()
        self.storage_preflight()
        # extraction filters were backported, so test the feature, not the version
        if sys.version_info < (3, 10) or not hasattr(tarfile, "data_filter"):
            raise CatalogError("Python 3.12 or newer is required (3.10.12+ and 3.11.4+ also work)")
        for secret in (self.layout.secrets / "config.ini", self.layout.secrets / "postgres_password"):
            self.require_safe_file(secret, secret=True)
            if secret.stat().st_size == 0:
                raise CatalogError(f"empty secret file: {secret}")
        # Read the file exactly as Django does (with % interpolation), so what fails here would fail the application.
        parser = configparser.ConfigParser()
        try:
            parser.read(self.layout.secrets / "config.ini")
        except configparser.Error as error:
            raise CatalogError(f"invalid config.ini: {error}") from error

        def setting(section: str, option: str) -> str:
            try:
                return parser.get(section, option, fallback="").strip()
            except configparser.Error as error:
                raise CatalogError(f"config.ini {section}.{option} cannot be read as Django reads it: {error}") from error

        required_options = [("db", "PASSWORD"), ("django", "SECRET_KEY")]
        if host.host_id == "prod":
            required_options.extend(
                ("email", option)
                for option in ("EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD")
            )
        missing_options = [
            f"{section}.{option}" for section, option in required_options if not setting(section, option)
        ]
        if missing_options:
            raise CatalogError(f"config.ini is missing required values: {', '.join(missing_options)}")
        database_password = (self.layout.secrets / "postgres_password").read_text(
            encoding="utf-8"
        ).rstrip("\r\n")
        if setting("db", "PASSWORD") != database_password:
            raise CatalogError("database passwords differ between config.ini and postgres_password")
        if host.host_id == "prod":
            try:
                email_port = int(setting("email", "EMAIL_PORT"))
            except ValueError as error:
                raise CatalogError("email.EMAIL_PORT must be an integer") from error
            if not 1 <= email_port <= 65535:
                raise CatalogError("email.EMAIL_PORT must be between 1 and 65535")
        self.command_output(["docker", "info"])
        self.command_output(["docker", "compose", "version"])
        if shutil.disk_usage(self.layout.var).free < 10 * 1024**3:
            raise CatalogError(f"less than 10 GiB free under {self.layout.var}")
        read_json(self.layout.journal, required=False)
        log(f"Host check passed: {host.host_id} ({host.domain})")
        return {
            "phase": "host-check",
            "ok": True,
            "host_id": host.host_id,
            "domain": host.domain,
            "project": host.project_name,
            "http_bind": host.http_bind,
        }
