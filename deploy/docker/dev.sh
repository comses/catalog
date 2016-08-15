#!/bin/sh

sleep 10
/code/deploy/solr/config.sh
invoke restore_from_dump
python manage.py runserver
