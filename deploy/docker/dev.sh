#!/bin/sh
set -e

cd /code

/bin/sh /code/deploy/docker/common.sh
# The image ships the locked production environment only; install the dev
# dependency group for local tooling.
uv sync --locked
/code/deploy/docker/wait-for-it.sh db:5432 -- python3 manage.py migrate --noinput
/code/deploy/docker/wait-for-it.sh -t 0 elasticsearch:9200 -- echo "Elasticsearch is ready."

exec python3 manage.py runserver 0.0.0.0:8000
