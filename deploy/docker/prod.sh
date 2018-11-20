#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
cd /code
python3 manage.py collectstatic --noinput --clear
chmod a+x /etc/cron.daily/*
chmod a+x /etc/cron.monthly/*
/code/deploy/docker/wait-for-it.sh solr:8983 -- echo "Solr is ready."
/code/deploy/docker/wait-for-it.sh elasticsearch:9200 -- echo "ElasticSearch is ready."
#echo "Indexing elasticsearch and solr"
#python3 manage.py rebuild_index --noinput
#echo "Starting UWSGI"
exec uwsgi --ini /code/deploy/uwsgi/catalog.ini
