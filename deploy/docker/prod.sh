#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
supervisord -c /code/deploy/supervisord/supervisord.conf
