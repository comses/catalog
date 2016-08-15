#!/bin/sh

/code/deploy/solr/config.sh
supervisord -c /code/deploy/supervisord/supervisord.conf
