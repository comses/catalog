#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

environment="${1:-dev}"
# The default output is the repo-root development Compose file.
output="${2:-docker-compose.yml}"

# Refuse to mutate a checkout still carrying state from the retired
# single-host deploy script unless the operator explicitly wants local dev.
if [[ "${output}" == "docker-compose.yml" && -s deploy/state/release.env && "${DEV_OVERRIDE:-0}" != 1 ]]; then
    echo "ERROR: legacy deployment state exists at deploy/state/release.env" >&2
    echo "       follow docs/deployment-runbook.md, or set DEV_OVERRIDE=1 for local development" >&2
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
