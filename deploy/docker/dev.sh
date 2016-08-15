#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
invoke restore_from_dump
python manage.py runserver
