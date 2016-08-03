#!/bin/sh

python manage.py build_solr_schema > /etc/solr/mycores/catalog_core/conf/schema.xml
cp -p /code/deploy/solr/solrconfig.xml /etc/solr/mycores/catalog_core/conf/
curl "http://localhost:8983/solr/admin/cores?action=RELOAD&core=catalog_core"
python manage.py runserver
