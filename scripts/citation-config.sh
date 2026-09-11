#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

cd citation

[[ -f docker/.env ]] || {
    echo "ERROR: citation/docker/.env is required" >&2
    exit 1
}

set -a
source docker/.env
set +a

export DB_PASSWORD
export DJANGO_SECRET_KEY
DB_PASSWORD=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c 30)
DJANGO_SECRET_KEY=$(head /dev/urandom | tr -dc '[:alnum:]' | head -c 30)

umask 077
envsubst < docker/templates/django/config.ini.template > docker/config/django/config.ini
envsubst < docker-compose.yml.template > docker-compose.yml
echo "Created citation Docker configuration"