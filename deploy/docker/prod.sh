#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
cd /code
python manage.py collectstatic --noinput --clear
uwsgi --ini /code/deploy/uwsgi/catalog.ini
