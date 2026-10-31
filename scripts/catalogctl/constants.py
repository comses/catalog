"""Names, paths and service lists the controller relies on."""

from __future__ import annotations

import re
from pathlib import Path

SCHEMA_VERSION = 1
CONTROLLER_VERSION = 1
MANIFEST_SCHEMA_VERSION = 2
MANIFEST_KIND = "catalog-release"
DATABASE_NAME = "comses_catalog"
IMAGE_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HOST_IDS = {"staging", "prod"}
HOST_DOMAINS = {
    "staging": "staging-catalog.comses.net",
    "prod": "catalog.comses.net",
}
# Hosts use the project name the CoMSES infrastructure declares; local development keeps base.yml's catalog.
COMPOSE_PROJECT = "comses-catalog"
# Durable host state lives on the /srv volume, inside the canonical checkout's ignored docker/ tree;
# the infrastructure binds the workload's backups root onto docker/deploy/shared/backups.
SRV_ROOT = Path("/srv")
CANONICAL_CHECKOUT = Path("/srv/apps/comses-catalog")
HOST_DIR = CANONICAL_CHECKOUT / "docker"
BACKUP_DIR = Path("/srv/backups/comses_model_catalog")
BACKUP_MARKER = "last-successful-backup"
DEFAULT_HTTP_BIND = "127.0.0.1:80"
OPERATORS_GROUP = "operators"
WRITER_SERVICES = ("scheduler", "django")
APPLICATION_SERVICES = ("django", "scheduler")
REQUIRED_SERVICES = ("db", "redis", "elasticsearch", "django", "scheduler", "nginx")
DEPENDENCY_SERVICES = ("db", "redis", "elasticsearch")
# Facts about the host's database and writers; a replacement candidate inherits them.
HOST_CANDIDATE_FIELDS = (
    "restore_status",
    "restore_started_at",
    "restore_artifact",
    "restore_sha256",
    "restore_receipt",
    "restore_temporary_database",
    "restore_retained_database",
    "drain_status",
    "drained_at",
    "migration_applied",
    "migration_started_at",
)
# Journal checkpoints past which the new runtime was verified, so recovery finishes the transition instead of reverting it.
FINALIZABLE_CHECKPOINTS = ("runtime-ready", "committed")
MAX_MAP_COUNT = 262144
MAX_MAP_COUNT_PATH = Path("/proc/sys/vm/max_map_count")
MANAGED_ALIASES = {
    "publication",
    "publication_curator",
    "author",
    "container",
    "model_documentation",
    "platform",
    "sponsor",
    "tag",
}
