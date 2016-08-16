#!/bin/sh

/bin/sh /code/deploy/docker/common.sh
invoke initialize_database_schema coverage
