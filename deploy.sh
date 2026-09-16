#!/usr/bin/env bash
# This compatibility name is intentionally not a command surface.

set -o errexit
set -o nounset
set -o pipefail

cat >&2 <<'EOF'
ERROR: ./deploy.sh is deprecated and no longer executes deployments.

Use the documented Make commands instead:
  make deploy ENV=staging|prod CATALOG_IMAGE=... CATALOG_ES_HOST=...
  make rollback | make status | make start | make stop
  make image-build | make image-push | make release-version
  make backup | make restore
EOF
exit 1
