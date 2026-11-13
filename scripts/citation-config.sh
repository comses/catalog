#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

cd citation

[[ -f docker/.env ]] || {
    echo "ERROR: citation/docker/.env is required" >&2
    exit 1
}

config_file=docker/config/django/config.ini
compose_file=docker-compose.yml

if [[ -s "${config_file}" && -s "${compose_file}" ]]; then
    echo "Citation Docker configuration already exists"
    exit 0
fi

if [[ -e "${config_file}" || -e "${compose_file}" ]]; then
    echo "ERROR: citation Docker configuration is incomplete" >&2
    echo "       stop the Citation stack, remove both generated files, and rerun make cite-config" >&2
    exit 1
fi

set -a
source docker/.env
set +a

export DB_PASSWORD
export DJANGO_SECRET_KEY
DB_PASSWORD=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c 30)
DJANGO_SECRET_KEY=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c 30)

umask 077
envsubst < docker/templates/django/config.ini.template > "${config_file}"
envsubst < docker-compose.yml.template > "${compose_file}"
echo "Created citation Docker configuration"
