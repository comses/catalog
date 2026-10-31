"""The controller base: the host lock, Compose and Docker plumbing, and release state readers."""

from __future__ import annotations

import contextlib
import fcntl
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Generator

from .common import CatalogError, atomic_json, log, read_json, require_json, sha256_file, sha256_tree
from .layout import HostConfig, Layout
from .runner import Runner


# Lock nesting per process, so one phase can call another while holding the host lock once.
_LOCK_DEPTH: dict[Path, int] = {}


class ControllerBase:
    """Shared plumbing every operation layer builds on; holds no phase logic itself."""

    def __init__(self, root: Path, layout: Layout, runner: Runner | None = None):
        self.root = root.resolve()
        self.layout = layout
        self.runner = runner or Runner()

    @contextlib.contextmanager
    def locked(self) -> Generator[None, None, None]:
        path = self.layout.lock
        if _LOCK_DEPTH.get(path):
            _LOCK_DEPTH[path] += 1
            try:
                yield
            finally:
                _LOCK_DEPTH[path] -= 1
            return
        if not path.parent.is_dir():
            raise CatalogError(f"backups root {path.parent} is missing; run make storage-preflight")
        inherited = os.environ.get('CATALOG_LOCK_FD')
        if inherited is not None:
            try:
                descriptor = int(inherited)
                actual = os.fstat(descriptor)
                expected = path.stat()
                if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                    raise ValueError('descriptor does not name the backup lock')
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, ValueError) as error:
                raise CatalogError(f'invalid inherited lock: {error}') from error
            _LOCK_DEPTH[path] = 1
            try:
                yield
            finally:
                _LOCK_DEPTH.pop(path, None)
            return
        try:
            lock_file = path.open("a+")
        except PermissionError:
            # The application's backup command (root in its container) may have created it; flock needs no write access.
            lock_file = path.open("r")
        with lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                log(f"Waiting for {path}: another Catalog operation is running")
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            _LOCK_DEPTH[path] = 1
            try:
                yield
            finally:
                _LOCK_DEPTH.pop(path, None)
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def command_output(self, command: list[str], *, cwd: Path | None = None) -> str:
        try:
            result = self.runner.run(command, cwd=cwd)
        except subprocess.CalledProcessError as error:
            stderr = (error.stderr or "").strip() if isinstance(error.stderr, str) else ""
            raise CatalogError(f"command failed: {' '.join(command)}{': ' + stderr if stderr else ''}") from error
        return (result.stdout or "").strip()

    def host(self) -> HostConfig:
        host = HostConfig.load(self.layout)
        self.require_safe_file(self.layout.host_env, secret=False)
        return host

    @staticmethod
    def require_safe_file(path: Path, *, secret: bool) -> None:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as error:
            raise CatalogError(f"cannot inspect {path}: {error}") from error
        forbidden = 0o077 if secret else 0o022
        if mode & forbidden:
            expected = "owner-only" if secret else "not group/other writable"
            raise CatalogError(f"unsafe permissions on {path}: expected {expected}")
        if not path.is_file() or path.is_symlink():
            raise CatalogError(f"expected a regular file: {path}")

    def compose_command(self, compose_file: Path, *arguments: str) -> list[str]:
        host = self.host()
        return [
            "docker",
            "compose",
            "--project-directory",
            str(compose_file.parent),
            "-p",
            host.project_name,
            "-f",
            str(compose_file),
            *arguments,
        ]

    def compose(
        self,
        compose_file: Path,
        *arguments: str,
        capture: bool = True,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        try:
            return self.runner.run(
                self.compose_command(compose_file, *arguments),
                capture=capture,
                check=check,
            )
        except subprocess.CalledProcessError as error:
            stderr = (error.stderr or "").strip() if isinstance(error.stderr, str) else ""
            raise CatalogError(f"Compose command failed: {' '.join(arguments)}{': ' + stderr if stderr else ''}") from error

    def manage(self, compose_file: Path, *arguments: str, capture: bool = False) -> subprocess.CompletedProcess:
        return self.compose(
            compose_file,
            "run",
            "--rm",
            "--no-deps",
            "django",
            "python3",
            "manage.py",
            *arguments,
            capture=capture,
        )

    def candidate_state(self) -> dict[str, Any]:
        candidate = require_json(self.layout.candidate)
        if candidate["host_id"] != self.host().host_id:
            raise CatalogError("candidate belongs to another host")
        compose_file = Path(candidate["compose_file"])
        if not compose_file.is_file() or sha256_file(compose_file) != candidate["compose_sha256"]:
            raise CatalogError("candidate Compose file is missing or changed")
        release_dir = Path(candidate["release_dir"])
        if sha256_tree(release_dir, excluded={"docker-compose.yml"}) != candidate["bundle_sha256"]:
            raise CatalogError("candidate release bundle is missing or changed")
        return candidate

    def verify_release_artifact(self, release: dict[str, Any], name: str) -> Path:
        if release.get("host_id") != self.host().host_id:
            raise CatalogError(f"{name} release belongs to another host")
        compose_file = Path(release["compose_file"])
        if not compose_file.is_file() or sha256_file(compose_file) != release.get("compose_sha256"):
            raise CatalogError(f"{name} Compose artifact is missing or changed")
        release_dir = Path(release["release_dir"])
        if sha256_tree(release_dir, excluded={"docker-compose.yml"}) != release.get("bundle_sha256"):
            raise CatalogError(f"{name} release bundle is missing or changed")
        return compose_file

    def update_candidate(self, candidate: dict[str, Any], **values: Any) -> dict[str, Any]:
        candidate = dict(candidate)
        candidate.update(values)
        atomic_json(self.layout.candidate, candidate)
        return candidate

    def active_state(self) -> dict[str, Any] | None:
        return read_json(self.layout.active)

    def read_rollback(self) -> dict[str, Any] | None:
        return read_json(self.layout.rollback)

    def active_compose(self) -> Path:
        active = require_json(self.layout.active)
        self.verify_release_artifact(active, "active")
        if not self.layout.canonical_compose.is_file():
            raise CatalogError("canonical active Compose file is missing")
        if sha256_file(self.layout.canonical_compose) != active["compose_sha256"]:
            raise CatalogError("canonical active Compose file does not match active state")
        return self.layout.canonical_compose
