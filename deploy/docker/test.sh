#!/bin/sh
/bin/sh /code/deploy/docker/common.sh
cd /code
# The image ships the locked production environment only; the dev
# dependency group (invoke, coverage, coveralls) is synced on demand so
# the test suite can run.
uv sync --locked
# CI validation gate: model changes must ship with their migration files.
# makemigrations runs with --check --dry-run, so the test run validates
# instead of generating migration files as a side effect.
invoke check_migrations
/code/deploy/docker/wait-for-it.sh db:5432 -- invoke migrate
# The test suite exercises the Elasticsearch 8 index code paths; block
# until ES8 is reachable (internal service port 9200) before testing.
/code/deploy/docker/wait-for-it.sh -t 0 elasticsearch8:9200 -- echo "ElasticSearch 8 is ready."
/code/deploy/docker/wait-for-it.sh solr:8983 -- invoke coverage
