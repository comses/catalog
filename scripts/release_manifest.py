#!/usr/bin/env python3
"""Write or check the release manifest of a published Catalog image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from catalogctl.constants import MANIFEST_KIND, MANIFEST_SCHEMA_VERSION
from catalogctl.manifest import load_manifest, validate_image


ROOT = Path(__file__).resolve().parent.parent
PACKAGES = (
    "citation",
    "Django",
    "djangorestframework",
    "elasticsearch",
    "elasticsearch-dsl",
    "gunicorn",
    "numpy",
    "pandas",
    "plotly",
    "psycopg2-binary",
)
VERSION_PROBE = """
import importlib.metadata, json, platform, subprocess, sys
packages = {}
for name in sys.argv[1:]:
    try:
        packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        packages[name] = None
pg_dump = subprocess.run(["pg_dump", "--version"], capture_output=True, text=True, check=True).stdout.strip()
print(json.dumps({"python": platform.python_version(), "packages": packages, "pg_dump": pg_dump}))
"""
BUILD_RUN_LABEL = "org.comses.catalog.build-run"


def output(command: list[str], **kwargs: Any) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs).stdout.strip()


def base_image(dockerfile: str) -> str:
    match = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)
    if not match:
        raise ValueError("the Dockerfile has no FROM line")
    return match.group(1)


def support_images(image_lists: list[list[str]], application_image: str) -> list[str]:
    return sorted({image for images in image_lists for image in images if image != application_image})


def search_backend(images: list[str]) -> str:
    for image in images:
        if "elasticsearch" in image.split("@", 1)[0]:
            return image.split("@", 1)[0]
    raise ValueError("no search engine among the support images")


def rendered_images(environment: str, image: str, revision: str) -> list[str]:
    domains = {"staging": "staging-catalog.comses.net", "prod": "catalog.comses.net"}
    env = os.environ.copy()
    env.update(
        COMPOSE_PROJECT_NAME="comses-catalog",
        CATALOG_IMAGE=image,
        CATALOG_BUNDLE_REVISION=revision,
        CATALOG_CONFIG_DIR=str(ROOT / "deploy" / "conf"),
        CATALOG_SHARED_DIR="/srv/apps/comses-catalog/docker/deploy/shared",
        CATALOG_BUNDLE_DIR=str(ROOT),
        CATALOG_HTTP_BIND="127.0.0.1:80",
        CATALOG_ENV=environment,
        CATALOG_DOMAIN=domains[environment],
    )
    with tempfile.TemporaryDirectory() as directory:
        rendered = Path(directory) / "docker-compose.yml"
        subprocess.run(
            ["bash", "scripts/compose.sh", environment, str(rendered)],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return output(["docker", "compose", "-f", str(rendered), "config", "--images"]).splitlines()


def dependency_versions(image: str) -> dict[str, Any]:
    probe = output(["docker", "run", "--rm", image, "python3", "-c", VERSION_PROBE, *PACKAGES])
    versions = json.loads(probe.splitlines()[-1])
    versions["uv_lock_sha256"] = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    return versions


def build_facts(image: str) -> dict[str, str]:
    """The image's creation time and build-run label, so the manifest describes the published image, not this run."""
    created, workflow_run = output(
        ["docker", "image", "inspect", image, "--format", "{{.Created}}\t{{index .Config.Labels \"" + BUILD_RUN_LABEL + "\"}}"]
    ).split("\t", 1)
    built_at = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0)
    if not workflow_run or workflow_run == "unknown":
        raise ValueError(f"{image} has no {BUILD_RUN_LABEL} label; build it with CATALOG_BUILD_RUN set")
    return {"workflow_run": workflow_run, "built_at": built_at.isoformat().replace("+00:00", "Z")}


def write(image: str, destination: Path) -> dict[str, Any]:
    validate_image(image)
    revision = output(["git", "rev-parse", "HEAD"], cwd=ROOT)
    support = support_images([rendered_images(environment, image, revision) for environment in ("staging", "prod")], image)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "catalog_revision": revision,
        "citation_revision": output(["git", "rev-parse", "HEAD:citation"], cwd=ROOT),
        "image": image,
        "support_images": support,
        "search_backend": search_backend(support),
        "base_image": base_image((ROOT / "deploy" / "images" / "django.Dockerfile").read_text(encoding="utf-8")),
        "dependencies": dependency_versions(image),
        "build": build_facts(image),
    }
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    check(destination, revision)
    return manifest


def check(path: Path, revision: str) -> dict[str, Any]:
    manifest, _digest = load_manifest(path)
    if manifest["catalog_revision"] != revision:
        raise ValueError(f"{path} describes {manifest['catalog_revision']}, not {revision}")
    return manifest


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("--image", required=True)
    write_parser.add_argument("--output", required=True, type=Path)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("manifest", type=Path)
    check_parser.add_argument("--revision", required=True)
    args = parser.parse_args(arguments)
    try:
        if args.command == "write":
            write(args.image, args.output)
        else:
            check(args.manifest, args.revision)
    except (ValueError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
