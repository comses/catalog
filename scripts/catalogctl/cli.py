"""Command line entry point: one phase per invocation, one JSON result on stdout."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .controller import Controller
from .common import CatalogError
from .constants import HOST_IDS
from .layout import Layout


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="catalogctl", description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    configure = subparsers.add_parser("configure")
    configure.add_argument("--host-id", required=True, choices=sorted(HOST_IDS))
    configure.add_argument("--http-bind")
    configure.add_argument("--import-config", type=Path)
    subparsers.add_parser("storage-prepare")
    subparsers.add_parser("storage-preflight")
    subparsers.add_parser("host-check")
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", required=True, type=Path)
    subparsers.add_parser("backup")
    backup_status = subparsers.add_parser("backup-status")
    backup_status.add_argument("--max-age", type=int)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--dump", required=True, type=Path)
    restore.add_argument("--confirm", required=True)
    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--confirmed", action="store_true")
    retry = subparsers.add_parser("candidate-retry")
    retry.add_argument("--confirmed", action="store_true")
    for command in (
        "drain",
        "rebuild",
        "activate",
        "validate",
        "rollback",
        "recover",
        "status",
        "release-report",
        "start",
        "stop",
        "logs",
    ):
        subparsers.add_parser(command)
    return result


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    controller = Controller(repository_root(), Layout.from_environment())
    if args.command == "logs":
        try:
            controller.logs()
        except CatalogError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        return 0
    handlers = {
        "configure": lambda: controller.configure(args.host_id, args.http_bind, args.import_config),
        "storage-prepare": controller.storage_prepare,
        "storage-preflight": controller.storage_preflight,
        "host-check": controller.host_check,
        "prepare": lambda: controller.prepare(args.manifest),
        "backup": controller.backup,
        "backup-status": lambda: controller.backup_status(args.max_age),
        "restore": lambda: controller.restore(args.dump, args.confirm),
        "drain": controller.drain,
        "migrate": lambda: controller.migrate(args.confirmed),
        "rebuild": controller.rebuild,
        "activate": controller.activate,
        "validate": controller.validate,
        "candidate-retry": lambda: controller.candidate_retry(args.confirmed),
        "rollback": controller.rollback_release,
        "recover": controller.recover,
        "status": controller.status,
        "release-report": controller.release_report,
        "start": controller.start,
        "stop": controller.stop,
    }
    try:
        result = handlers[args.command]()
    except CatalogError as error:
        message = str(error)
    except subprocess.CalledProcessError as error:
        message = f"command failed with exit code {error.returncode}: {' '.join(map(str, error.cmd))}"
    except OSError as error:
        message = f"operating system failure: {error}"
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok", True) else 1
    print(f"ERROR: {message}", file=sys.stderr)
    print(json.dumps({"phase": args.command, "ok": False, "error": message}, indent=2, sort_keys=True))
    return 1
