# Deployment Runbook (staging / prod, Docker Swarm)

Applies to the `catalog` stack deployed by `deploy.sh` on the swarm manager.
Environments: `staging` (base.yml + staging.yml) and `prod`
(base.yml + staging.yml + prod.yml) — same stack name `catalog`, different
`DOMAIN_NAME`. Staging is therefore a release state of the same stack, not a
parallel cluster: the standard sequence is deploy the staging release,
validate, then deploy the prod release.

## Deployment unit: immutable image references only

The deployment **and** rollback unit is the exact application image
reference (an explicit tag or a digest). `comses/catalog/prod:latest` is no
longer a valid deployment unit:

- `deploy.sh` **rejects** `:latest`, malformed digests, and bare references
  (a bare reference implicitly means `:latest`).
- The reference is passed per deploy: `./deploy.sh deploy <env> <image-ref>`
  or `CATALOG_IMAGE=<image-ref> ./deploy.sh deploy <env>`.
- `staging.yml` pins the django service to `image: ${CATALOG_IMAGE}`; the
  compose script bakes the exact reference into the generated
  `docker-compose.yml`.

### Producing an immutable reference

```sh
# 1. Build locally from a tagged/committed checkout, tagged immutably:
./deploy.sh build comses/catalog/prod:v2026.08.27
#    (runs ./compose staging + docker compose build --pull django)

# 2. Make the exact reference resolvable from the swarm manager, either by
#    pushing it to a registry the manager can reach:
docker push comses/catalog/prod:v2026.08.27
#    or by pinning the immutable digest of what was pushed:
docker buildx imagetools inspect comses/catalog/prod:v2026.08.27
#    then deploy with comses/catalog/prod@sha256:<digest>
```

Prefer digest references (`name@sha256:...`) when a registry tag could ever
be re-pushed; an explicit content tag is acceptable only if the tag is
guaranteed immutable.

### Prior deployed image is recorded before every rollout

Before tearing the stack down, `deploy.sh` captures the currently deployed
image from `docker service inspect catalog_django` and records it in two
places:

1. As the service label `comses.catalog.previous-image` on the **next**
   release (also `comses.catalog.image` and `comses.catalog.es-host`):

   ```sh
   docker service inspect catalog_django --format '{{json .Spec.Labels}}'
   ```

2. As an append-only, timestamped line in `docker/deploy-history.log`
   (git-ignored; override the path with `DEPLOY_HISTORY_FILE`):

   ```
   2026-08-27T09:15:00Z env=prod previous_image=comses/catalog/prod:v2026.08.20 next_image=comses/catalog/prod:v2026.08.27 es_host=elasticsearch
   ```

The deploy then verifies the requested reference resolves on the manager
(local image or `docker pull`) **before** the stack is torn down; if it
cannot, the deploy aborts and the old release keeps running.

## Hard operational prerequisites

The steps below **do not assert** that these prerequisites are in place.
Verify each one before any deploy; `deploy.sh` cannot check them for you.

1. **Swarm**: a swarm the manager node can `docker stack deploy` to.
   `elasticsearch8` must run as **exactly one replica**
   (`discovery.type: single-node`; extra swarm replicas form independent
   clusters — see `staging.yml`).
2. **Swarm secrets**: the swarm secrets `catalog_django_config` (config.ini)
   and `catalog_db_password` must already exist on the swarm, and the
   corresponding files under `deploy/conf/` must exist on the deploy host
   (the compose `secrets:` blocks reference them).
3. **Swarm storage**:
   - Postgres data: bind mount `./docker/shared/pgdata` on the manager must
     already hold the database (or be restored via `./deploy.sh restore`).
   - Named volumes `esdata` (ES6 data), `esdata8` (ES8 data), `solr`,
     `static`, `uwsgisocket` must persist across rollouts on the nodes that
     run those services. An **empty `esdata8` is not a problem** for an ES8
     cutover: `rebuild_es_index` recreates the indices from PostgreSQL.
   - `docker/shared/catalog/logs` and `docker/shared/nginx/logs` on the
     manager (created automatically by `deploy.sh`).
4. **Image resolvability**: the immutable reference must be resolvable from
   the nodes that schedule tasks (registry reachability, or the image
   pre-loaded on those nodes).
5. **Endpoint/DNS**: `DOMAIN_NAME` (`staging-catalog.comses.net` /
   `catalog.comses.net`) resolves to the manager and ports 80 is published
   by the nginx (global) service.

## Standard release (ES6 endpoint, default)

```sh
./deploy.sh build comses/catalog/prod:<immutable-tag>
docker push comses/catalog/prod:<immutable-tag>        # if the manager cannot see the local build
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> ./deploy.sh deploy staging
# smoke-test the staging domain, then:
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> ./deploy.sh deploy prod
```

`CATALOG_ES_HOST` is not set, so the release runs with
`ELASTICSEARCH_HOST=elasticsearch` (ES 6.6.2).

## ES8 cutover (gated): rebuild + validate BEFORE switching any release to ES8

The application ES endpoint is the per-release env var
`ELASTICSEARCH_HOST` (composed into `settings.ELASTICSEARCH` at runtime).
A release only runs against ES8 when it is deployed with
`CATALOG_ES_HOST=elasticsearch8`. Never switch an already-running release by
changing only that endpoint (see Rollback).

Precondition: a release is already deployed on the `catalog` stack (any
endpoint) and the ES8 service is healthy:

```sh
docker service ls --filter name=catalog_elasticsearch8        # 1 replica, Running
ES8_TASK=$(docker service ps catalog_elasticsearch8 --filter desired-state=running -q | head -n1)
docker exec "${ES8_TASK}" curl -fsS 'http://localhost:9200/_cluster/health?pretty'
# expect: cluster status green or yellow, no unassigned shards
```

### 1. Rebuild the public indices against ES8

Run the management command from the **same immutable image** in a one-off
service on the stack network, pointed at ES8 (the command reads
`ELASTICSEARCH_HOST`/`ELASTICSEARCH_PORT`; the running release may still be
on ES6 — that does not matter, this only talks to ES8 and Postgres):

```sh
docker service create \
  --name catalog_es8_rebuild --rm \
  --network catalog_default \
  --secret catalog_django_config \
  -e DJANGO_SETTINGS_MODULE=catalog.settings.prod \
  -e LANG=C.UTF-8 \
  -e DB_USER=catalog -e DB_HOST=db -e DB_NAME=comses_catalog -e DB_PORT=5432 \
  -e SOLR_HOST=solr -e SOLR_PORT=8983 -e SOLR_CORE_NAME=catalog_core \
  -e ELASTICSEARCH_HOST=elasticsearch8 -e ELASTICSEARCH_PORT=9200 \
  "<CATALOG_IMAGE>" python3 manage.py rebuild_es_index
```

`manage.py rebuild_es_index` rebuilds every public read alias
(`publication`, `author`, `container`, `platform`, `sponsor`, `tag`) into
fresh generation indices (`<alias>-<utc-stamp>`), validates each document
count, and swaps the aliases atomically. It **exits nonzero** on any bulk
failure, count mismatch, or alias-swap failure, and on failure leaves the
live read aliases untouched. A nonzero exit here means: do **not** continue
the cutover.

### 2. Validate ES8 before switching any application release to it

```sh
# a) the rebuild reported success:
docker service logs catalog_es8_rebuild
#    expect: "Public search indices rebuilt successfully." and a clean exit

# b) every read alias points at a fresh generation index:
docker exec "${ES8_TASK}" curl -fsS 'http://localhost:9200/_alias?pretty'
#    expect: publication, author, container, platform, sponsor, tag
#    each mapped to a <alias>-<utc-stamp> index

# c) document counts match the database:
docker exec "${ES8_TASK}" curl -fsS 'http://localhost:9200/publication/_count'
DJANGO_TASK=$(docker service ps catalog_django --filter desired-state=running -q | head -n1)
docker exec "${DJANGO_TASK}" python3 manage.py shell -c \
  "from citation.models import Publication; print(Publication.api.primary().filter(status='REVIEWED').count())"
#    the two numbers must be equal

# d) a live query against ES8 works:
docker exec "${ES8_TASK}" curl -fsS 'http://localhost:9200/publication/_search' \
  -H 'Content-Type: application/json' -d '{"size":1,"query":{"match_all":{}}}'
```

Only after (a)–(d) pass may a release be switched to ES8.

### 3. Switch the release to ES8 (a release change, not a config tweak)

Redeploy with the ES8 endpoint:

```sh
CATALOG_IMAGE="<CATALOG_IMAGE>" CATALOG_ES_HOST=elasticsearch8 ./deploy.sh deploy staging
# smoke-test: search on the staging domain, autocomplete, facet counts;
# check for ES errors:
docker service logs catalog_django --since 10m
# then the same for prod:
CATALOG_IMAGE="<CATALOG_IMAGE>" CATALOG_ES_HOST=elasticsearch8 ./deploy.sh deploy prod
```

## Rollback

**Rollback is redeploying the recorded prior application image with ES6. It
is not an endpoint-only change** (pointing a running release at
`elasticsearch` without redeploying is not a rollback: the prior release is
the unit that was validated against the prior index state).

1. Retrieve the recorded prior image reference:

   ```sh
   docker service inspect catalog_django --format '{{index .Spec.Labels "comses.catalog.previous-image"}}'
   # and/or:
   tail -n 5 docker/deploy-history.log
   ```

2. Redeploy it with the ES6 endpoint (the default when `CATALOG_ES_HOST` is
   unset):

   ```sh
   CATALOG_IMAGE="<recorded previous image reference>" ./deploy.sh deploy prod
   ```

   (Use `deploy staging` first if you want to validate the rollback on the
   staging release before prod.)

3. Verify: the django tasks are Running, search works, and the label on the
   rolled-back service shows `comses.catalog.es-host=elasticsearch`.

Notes:

- The recorded reference is the exact image that was running before the
  rollout, so rollback is deterministic and does not depend on any mutable
  tag.
- The ES6 service (`elasticsearch`, data in `esdata`) stays deployed by
  `base.yml` for the lifetime of the rollback window; do not remove it while
  ES6 rollbacks are possible.
- ES8 index state is independent of the application rollback: generation
  indices and the previous generation per alias are retained by
  `rebuild_es_index`, so an ES8 alias rollback is a separate, index-level
  operation and is not part of the application rollback.

## Day-2 commands

```sh
./deploy.sh down                # tear down the catalog stack
./deploy.sh restore             # restore Postgres from catalog.sql + reindex
./deploy.sh tag                 # write release-version.txt (git describe)
```
