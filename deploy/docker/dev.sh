#!/bin/sh

cd /code

/bin/sh /code/deploy/docker/common.sh
# The image ships the locked production environment only; the dev
# dependency group (invoke, ...) is synced on demand so the invoke tasks
# below can run.
uv sync --locked
/code/deploy/docker/wait-for-it.sh db:5432 -- invoke restore-from-dump
# /code/deploy/docker/wait-for-it.sh solr:8983 -- python3 manage.py rebuild_index --noinput

exec python3 manage.py runserver 0.0.0.0:8000
