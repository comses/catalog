#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

environment="${1:-dev}"
# Default output is the repo-root docker-compose.yml for every environment.
# This is the operational file used by both development and deployment.
output="${2:-docker-compose.yml}"

# A direct render to the canonical root is a development convenience, not a
# way to rewrite a tracked deployment checkout. Deployment renders use a
# temporary candidate path and therefore do not trip this guard.
if [[ "${output}" == "docker-compose.yml" && -s deploy/state/release.env && "${COMPOSE_ALLOW_DEPLOY_RENDER:-0}" != 1 ]]; then
    echo "ERROR: deployment state is present; refusing to overwrite root docker-compose.yml" >&2
    echo "       use make deploy/rollback/start/stop, or set DEV_OVERRIDE=1 deliberately" >&2
    exit 1
fi

case "${environment}" in
    dev)
        files=(-f base.yml -f dev.yml)
        ;;
    staging)
        files=(-f base.yml -f staging.yml)
        ;;
    prod)
        files=(-f base.yml -f staging.yml -f prod.yml)
        ;;
    *)
        echo "ERROR: environment must be one of: dev, staging, prod" >&2
        exit 1
        ;;
esac

# Render atomically: write to a temporary file and rename it into place, so
# a failed render (unset variable, missing config file) exits without
# truncating a previously rendered compose file.
mkdir -p "$(dirname "${output}")"
rendered=$(mktemp "${output}.XXXXXX")
trap 'rm -f "${rendered}"' EXIT
docker compose "${files[@]}" config > "${rendered}"
mv "${rendered}" "${output}"
