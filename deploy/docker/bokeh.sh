#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

DOMAIN_NAME=${DOMAIN_NAME:-localhost}

cd /code/visualization/bokeh_example
/code/deploy/docker/wait-for-it.sh elasticsearch:9200 -- echo "ElasticSearch is ready. Starting bokeh"
exec bokeh serve --address 0.0.0.0 --allow-websocket-origin=${DOMAIN_NAME} visualization
