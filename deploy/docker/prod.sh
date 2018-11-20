#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
cd /code
python3 manage.py collectstatic --noinput --clear
chmod a+x /etc/cron.daily/*
chmod a+x /etc/cron.monthly/*
# /code/deploy/docker/wait-for-it.sh solr:8983 -- python3 manage.py rebuild_index --noinput
/code/deploy/docker/wait-for-it.sh elasticsearch:9200
exec uwsgi --ini /code/deploy/uwsgi/catalog.ini
