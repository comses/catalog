#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

# Setup shared folders
mkdir -p docker/shared/catalog/logs
mkdir -p docker/shared/nginx/logs

# Ensure catalog stack is down before deploying again
catalog=$(docker stack ls --format '{{.Name}}' | { grep -i catalog || test $? -eq 1; } )
if [[ "$catalog" == "catalog" ]]; then
  echo "Not deploying because 'catalog' stack already exists"
  echo "Run 'docker stack rm catalog' and wait a while for it to finish"
  exit 1
fi

# Deploy catalog
echo "Deploying catalog"
./compose prod
docker stack deploy -c docker-compose.yml catalog

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
