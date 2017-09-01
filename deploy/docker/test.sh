#!/bin/sh
/bin/sh /code/deploy/docker/common.sh
cd /code
/code/deploy/docker/wait-for-it.sh db:5432 -- invoke idb
/code/deploy/docker/wait-for-it.sh solr:8983 -- invoke coverage
