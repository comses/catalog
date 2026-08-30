#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
cd /code
python3 manage.py collectstatic --noinput --clear
chmod a+x /etc/cron.daily/*
chmod a+x /etc/cron.monthly/*
/code/deploy/docker/wait-for-it.sh solr:8983 -- echo "Solr is ready."
/code/deploy/docker/wait-for-it.sh elasticsearch:9200 -- echo "ElasticSearch is ready."
# The application's Elasticsearch endpoint is ES8 (ELASTICSEARCH_HOST
# defaults to elasticsearch8, see catalog/settings/base.py). Block until
# ES8 is reachable before the application or any reindex action runs.
/code/deploy/docker/wait-for-it.sh -t 0 elasticsearch8:9200 -- echo "ElasticSearch 8 is ready."
#echo "Indexing elasticsearch and solr"
#python3 manage.py rebuild_index --noinput
echo "Starting Gunicorn"
# Gunicorn 26.2.0 over the shared unix socket (replaces the legacy
# uWSGI config in deploy/uwsgi/catalog.ini, which is retired):
#   - workers 4 / threads 2  == uwsgi processes/threads
#   - umask 002              == uwsgi chmod-socket 664
#   - timeout 0              == uwsgi had no harakiri (no request timeout)
#   - no stats socket: gunicorn has no uwsgi-style stats equivalent
# X-Forwarded-Proto (set by Nginx) is mapped to wsgi.url_scheme by
# gunicorn's default secure_scheme_headers for trusted unix-socket peers.
mkdir -p /shared/logs /catalog/socket
exec gunicorn catalog.wsgi:application \
    --bind unix:/catalog/socket/gunicorn.sock \
    --workers 4 \
    --threads 2 \
    --umask 002 \
    --timeout 0 \
    --env DJANGO_SETTINGS_MODULE=catalog.settings.prod \
    --error-logfile /shared/logs/gunicorn-error.log \
    --access-logfile /shared/logs/gunicorn-access.log
