#!/usr/bin/env bash
# Deprecated: forwarding shim for scripts/deploy.sh.
#
# Preserves the legacy invocation forms:
#   ./deploy.sh deploy [staging|prod] [image-ref]
#   ./deploy.sh build [image-ref]
#   ./deploy.sh down        # maps to 'stop' (keeps volumes; no teardown)
#   ./deploy.sh restore
#   ./deploy.sh tag
#
# The image reference is taken from the positional argument, or from
# CATALOG_IMAGE when absent. CATALOG_ES_HOST (elasticsearch | elasticsearch8)
# is passed through unchanged and is required for deploy.
#
# Prefer the Make targets: make deploy ENV=staging|prod | make rollback |
# make status | make start | make stop | make image-build | make image-push |
# make release-version  (see docs/deployment-runbook.md)

set -o errexit
set -o nounset
set -o pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat >&2 <<'EOF'
usage:
  ./deploy.sh deploy [staging|prod] [image-ref]
  ./deploy.sh build [image-ref]
  ./deploy.sh down | backup | restore | tag

(deprecated) This script forwards to scripts/deploy.sh. Prefer the Make targets:
  make deploy ENV=staging|prod    CATALOG_IMAGE + CATALOG_ES_HOST required
  make rollback | make status | make start | make stop
  make image-build | make image-push        CATALOG_IMAGE required
  make backup | make restore | make release-version

'./deploy.sh down' maps to 'stop': containers stop, but networks and named
volumes are kept (the legacy stack teardown is gone).

The image reference is taken from the positional argument, or from
CATALOG_IMAGE when absent. CATALOG_ES_HOST (elasticsearch | elasticsearch8)
is passed through unchanged and is required for deploy.
See docs/deployment-runbook.md.
EOF
    exit 1
}

command="${1:-}"
case "${command}" in
    deploy)
        environment="${2:-prod}"
        if [[ "${environment}" != "staging" && "${environment}" != "prod" ]]; then
            usage
        fi
        if [[ -n "${3:-}" ]]; then
            export CATALOG_IMAGE="${3}"
        fi
        exec bash "${script_dir}/scripts/deploy.sh" deploy "${environment}"
        ;;
    build)
        if [[ -n "${2:-}" ]]; then
            export CATALOG_IMAGE="${2}"
        fi
        exec bash "${script_dir}/scripts/deploy.sh" build
        ;;
    down)
        echo "NOTE: 'down' is deprecated and maps to 'stop' (containers stop; networks and named volumes are kept)" >&2
        exec bash "${script_dir}/scripts/deploy.sh" stop
        ;;
    backup | restore | tag)
        exec bash "${script_dir}/scripts/deploy.sh" "${command}"
        ;;
    *)
        usage
        ;;
esac
