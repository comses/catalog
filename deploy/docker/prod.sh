#!/bin/sh
set -e

/bin/sh /code/deploy/docker/common.sh
cd /code
python3 manage.py collectstatic --noinput --clear
chmod a+x /etc/cron.daily/*
chmod a+x /etc/cron.monthly/*
# Block until the release's configured Elasticsearch endpoint is
# reachable before the application starts.
ES_HOST="${ELASTICSEARCH_HOST:-elasticsearch}"
ES_PORT="${ELASTICSEARCH_PORT:-9200}"
/code/deploy/docker/wait-for-it.sh -t 0 "${ES_HOST}:${ES_PORT}" -- echo "Elasticsearch is ready (${ES_HOST})."
echo "Starting Gunicorn"
# Nginx proxies over the shared unix socket (umask 002 keeps it group-writable);
# gunicorn maps nginx's X-Forwarded-Proto to wsgi.url_scheme for unix-socket peers.
mkdir -p /catalog/socket
exec gunicorn catalog.wsgi:application \
    --bind unix:/catalog/socket/gunicorn.sock \
    --workers 4 \
    --threads 2 \
    --umask 002 \
    --timeout 0 \
    --error-logfile - \
    --access-logfile -
