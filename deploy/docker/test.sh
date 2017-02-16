#!/bin/sh
/bin/sh /code/deploy/docker/common.sh
/code/deploy/docker/wait-for-it.sh db:5432 -- invoke initialize_database_schema
/code/deploy/docker/wait-for-it.sh solr:8983 -- invoke coverage
