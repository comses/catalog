"""Release manifest validation and release identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .common import CatalogError
from .constants import IMAGE_RE, MANIFEST_KIND, MANIFEST_SCHEMA_VERSION, REVISION_RE


def validate_image(value: object) -> str:
    if not isinstance(value, str) or not IMAGE_RE.fullmatch(value):
        raise CatalogError(f"image must be a complete name@sha256:<64 lowercase hex> reference: {value}")
    return value


def validate_revision(value: object) -> str:
    if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
        raise CatalogError(f"revision must be a full 40-character lowercase Git SHA: {value}")
    return value


def release_id(revision: object, image: object) -> str | None:
    """A release is its Catalog commit plus its image digest; None when either is unknown."""
    if not isinstance(revision, str) or not isinstance(image, str) or "@sha256:" not in image:
        return None
    return f"{revision[:12]}-{image.rsplit('@sha256:', 1)[1][:12]}"


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise CatalogError(f"cannot read release manifest {path}: {error}") from error
    try:
        manifest = json.loads(payload)
    except json.JSONDecodeError as error:
        raise CatalogError(f"release manifest {path} is not valid JSON: {error}") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest.get("kind") != MANIFEST_KIND
    ):
        raise CatalogError(f"{path} is not a schema {MANIFEST_SCHEMA_VERSION} Catalog release manifest")
    required = {
        "catalog_revision",
        "citation_revision",
        "image",
        "support_images",
        "search_backend",
        "base_image",
        "dependencies",
        "build",
    }
    missing = sorted(required.difference(manifest))
    if missing:
        raise CatalogError(f"release manifest is missing: {', '.join(missing)}")
    validate_revision(manifest["catalog_revision"])
    validate_revision(manifest["citation_revision"])
    validate_image(manifest["image"])
    support_images = manifest["support_images"]
    if not isinstance(support_images, list) or not support_images:
        raise CatalogError("release manifest support_images must be a non-empty list")
    for image in support_images:
        validate_image(image)
    return manifest, hashlib.sha256(payload).hexdigest()
