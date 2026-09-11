#!/usr/bin/env bash
# Deprecated: forwarding shim for scripts/config.sh.
#
# ./build.sh generated deploy/conf/config.ini and
# deploy/conf/postgres_password from deploy/conf/config.template.ini.
# That logic now lives in scripts/config.sh (make config-generate).
# Legacy behavior is preserved:
#   - no configuration yet: generate it
#   - configuration already exists: the old interactive "replace?" prompt
#     is replaced by the FORCE=1 migration path (back up + rotate)
#
# Prefer: make config-generate   (FORCE=1 make config-generate to rotate)

set -o errexit
set -o nounset
set -o pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

config_ini="deploy/conf/config.ini"
postgres_password_file="deploy/conf/postgres_password"

echo "NOTE: ./build.sh is deprecated; use 'make config-generate' (scripts/config.sh)" >&2

if [[ -e "${config_ini}" || -e "${postgres_password_file}" ]]; then
    if [[ "${FORCE:-0}" != "1" ]]; then
        echo "ERROR: ${config_ini} already exists; replacing it rotates the db password" >&2
        echo "       Re-run with FORCE=1 to back up the existing configuration and rotate credentials:" >&2
        echo "         FORCE=1 ./build.sh     (or: FORCE=1 make config-generate)" >&2
        exit 1
    fi
fi

# FORCE, when set, is passed through to scripts/config.sh via the environment
exec bash "${script_dir}/scripts/config.sh" generate
