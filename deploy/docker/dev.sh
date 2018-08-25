#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
/code/deploy/docker/wait-for-it.sh db:5432 -- invoke restore_from_dump
/code/deploy/docker/wait-for-it.sh solr:8983 -- python3 manage.py rebuild_index --noinput

# python3 manage.py runserver 0.0.0.0:8000
tail -f /dev/null
