#!/bin/sh

set -eu

# Cron starts jobs with a minimal environment, so preserve the container config.
umask 077
export -p > /run/catalog-scheduler.env
exec /usr/sbin/cron -f
