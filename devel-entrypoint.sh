#!/bin/sh

sleep 10
# python manage.py build_solr_schema > /etc/solr/mycores/catalog_core/conf/schema.xml
cp -p /code/deploy/solr/*.xml /etc/solr/mycores/catalog_core/conf/
curl "http://solr:8983/solr/admin/cores?action=RELOAD&core=catalog_core"
invoke restore_from_dump
python manage.py runserver
