#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

DOMAIN_NAME=${DOMAIN_NAME:-localhost:8000}

export BOKEH_SECRET_KEY=$(</run/secrets/bokeh_secret_key)
export BOKEH_SIGN_SESSIONS=yes

cd /code/visualization/bokeh_example
/code/deploy/docker/wait-for-it.sh elasticsearch:9200 -- echo "ElasticSearch is ready. Starting bokeh"
exec bokeh serve --address 0.0.0.0 --allow-websocket-origin=${DOMAIN_NAME} --session-ids external-signed visualization
