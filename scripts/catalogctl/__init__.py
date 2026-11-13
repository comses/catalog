"""Release controller for Catalog hosts: explicit deployment phases with JSON results.

Run as ``python3 -m catalogctl <phase>`` (the Makefile's host targets); each phase
prints one JSON object on stdout and its progress on stderr.
"""

from . import activation, backup, candidate, cli, core, database, host, layout, operations, search
from .cli import main, parser
from .common import (
    CatalogError,
    append_json_line,
    atomic_json,
    atomic_write,
    log,
    parse_utc,
    read_json,
    require_json,
    sha256_file,
    sha256_tree,
    utc_now,
)
from .constants import (
    APPLICATION_SERVICES,
    MANIFEST_KIND,
    MANIFEST_SCHEMA_VERSION,
    REQUIRED_SERVICES,
    SCHEMA_VERSION,
)
from .controller import Controller
from .layout import HostConfig, Layout, valid_http_bind
from .manifest import load_manifest, release_id, validate_image, validate_revision
from .runner import Runner

__all__ = [
    "APPLICATION_SERVICES",
    "CatalogError",
    "Controller",
    "HostConfig",
    "Layout",
    "MANIFEST_KIND",
    "MANIFEST_SCHEMA_VERSION",
    "REQUIRED_SERVICES",
    "Runner",
    "SCHEMA_VERSION",
    "activation",
    "append_json_line",
    "atomic_json",
    "atomic_write",
    "backup",
    "candidate",
    "cli",
    "core",
    "database",
    "host",
    "layout",
    "load_manifest",
    "log",
    "main",
    "operations",
    "parse_utc",
    "parser",
    "read_json",
    "release_id",
    "require_json",
    "search",
    "sha256_file",
    "sha256_tree",
    "utc_now",
    "valid_http_bind",
    "validate_image",
    "validate_revision",
]
