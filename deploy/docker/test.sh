#!/bin/sh

echo "running coveralls? ${RUN_COVERALLS:-false}"

/bin/sh /code/deploy/docker/common.sh
/code/deploy/docker/wait-for-it.sh db:5432 -- invoke initialize_database_schema coverage
if [[ $RUN_COVERALLS ]]; then
    coveralls
fi
