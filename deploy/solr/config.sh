#!/bin/sh

# configure solr core for catalog app

cp -p /code/deploy/solr/*.xml /etc/solr/mycores/catalog_core/conf/
curl "http://solr:8983/solr/admin/cores?action=RELOAD&core=catalog_core"
