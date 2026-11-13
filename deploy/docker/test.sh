#!/bin/sh
set -e

/bin/sh /code/deploy/docker/common.sh
cd /code
# The image ships the locked production environment only; the dev
# dependency group (invoke, coverage, coveralls) is synced on demand so
# the test suite can run.
uv sync --locked
# CI validation gate: model changes must ship with their migration files.
# makemigrations runs with --check --dry-run, so the test run validates
# instead of generating migration files as a side effect.
invoke check-migrations
/code/deploy/docker/wait-for-it.sh db:5432 -- invoke migrate
# The test suite exercises Elasticsearch-backed search paths.
/code/deploy/docker/wait-for-it.sh -t 0 elasticsearch:9200 -- echo "Elasticsearch is ready."
invoke coverage
