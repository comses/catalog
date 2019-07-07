#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

restore_db() {
echo "Restore from catalog.sql (y/N)"
read restore_confirm

if [[ "$restore_confirm" == [yY] || "$restore_confirm" == [yY][eE][sS] ]]; then
django_service_id=$(docker service ps catalog_django -q)
django_container_id=$(docker ps --filter label=com.docker.swarm.service.name=catalog_django -q)
echo "Copying catalog.sql to container"
docker cp catalog.sql ${django_container_id}:/code

echo "Restoring database and reindexing"
docker exec -i ${django_container_id} bash <<-EOF
inv restore-from-dump
EOF
fi
}

tag_app() {
git describe --tags >| release-version.txt
}

down_app() {
# Ensure catalog stack is down before deploying again
if [[ $(docker service ls -q --filter label="com.docker.stack.namespace=catalog" | wc -l) == 0 ]]; then
echo "Catalog already torn down"
else
echo "Catalog is being torn down"
docker stack rm catalog
sleep 12
echo "Catalog successfully torn down"
fi
}

deploy_app() {
tag_app

# Setup shared folders
mkdir -p docker/shared/catalog/logs
mkdir -p docker/shared/nginx/logs

down_app

# Deploy catalog
local environment="$1"
echo "Deploying catalog"
./compose $environment
docker-compose build --pull
docker-compose pull db nginx redis
docker stack deploy -c docker-compose.yml catalog
}

case "${1:-deploy}" in
    'deploy') deploy_app "${2:-prod}";;
    'down') down_app;;
    'restore') restore_db;;
    'tag') tag_app;;
    *) echo "Invalid option choose on of deploy, down, restore" 1>&2; exit 1;;
esac
