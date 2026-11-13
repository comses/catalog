#!/usr/bin/env bash
# This compatibility name is intentionally not a command surface.

set -o errexit
set -o nounset
set -o pipefail

cat >&2 <<'EOF'
ERROR: ./deploy.sh is deprecated and no longer executes deployments.

Use the documented release phases instead (see docs/deployment-runbook.md):
  make prepare MANIFEST=<release-manifest.json>
  make backup | make backup-status | make restore | make drain
  CONFIRM_SCHEMA_MIGRATION=1 make migrate
  make rebuild | make activate | make validate
  make rollback | make recover | make status | make release-report
  make start | make stop | make logs
EOF
exit 1
