#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
cd /code
python manage.py collectstatic --noinput --clear
chmod a+x /etc/periodic/daily/*
/code/deploy/docker/wait-for-it.sh -- python manage.py rebuild_index --noinput
uwsgi --ini /code/deploy/uwsgi/catalog.ini
