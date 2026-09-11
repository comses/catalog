#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

config_ini="deploy/conf/config.ini"
config_template_ini="deploy/conf/config.template.ini"
postgres_password_file="deploy/conf/postgres_password"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

validate() {
    [[ -s "${config_ini}" ]] || die "missing or empty ${config_ini}; run make config-generate"
    [[ -s "${postgres_password_file}" ]] || die "missing or empty ${postgres_password_file}; run make config-generate"
}

generate() {
    if [[ -e "${config_ini}" || -e "${postgres_password_file}" ]]; then
        [[ "${FORCE:-0}" == "1" ]] || die "configuration already exists; use FORCE=1 make config-generate to rotate credentials"

        if [[ -e "${config_ini}" ]]; then
            backup_name="deploy/conf/config-backup-$(date '+%Y-%m-%d.%H-%M-%S').ini"
            mv "${config_ini}" "${backup_name}"
            echo "Backed up ${config_ini} to ${backup_name}"
        fi
    fi

    export DB_USER=catalog
    export DB_NAME=comses_catalog
    export DB_PASSWORD
    export SECRET_KEY
    DB_PASSWORD=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c 60)
    SECRET_KEY=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c 100)

    umask 077
    envsubst < "${config_template_ini}" > "${config_ini}"
    printf '%s\n' "${DB_PASSWORD}" > "${postgres_password_file}"
    chmod 600 "${config_ini}" "${postgres_password_file}"
    echo "Created ${config_ini} and ${postgres_password_file}"
}

case "${1:-}" in
    generate) generate ;;
    validate) validate ;;
    *) die "usage: $0 <generate|validate>" ;;
esac