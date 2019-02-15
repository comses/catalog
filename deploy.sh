#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

# Ensure catalog stack is down before deploying again
catalog=$(docker stack ls --format '{{.Name}}' | { grep -i catalog || test $? 1; } )
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
echo "Copying catalog.sql to container"
django_id=$(docker service ps catalog_django -q)
docker cp catalog.sql ${django_id}:/code

echo "Restoring database and reindexing"
docker exec -i ${django_id} bash <<'EOF'
inv restore-from-dump
inv rebuild-index
EOF
fi
