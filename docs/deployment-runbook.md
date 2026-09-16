# Deployment Runbook (staging / prod, single-host Docker Compose)

Applies to the `catalog` Compose stack deployed through the root `Makefile`
on a single Docker host. Environments: `staging` (base.yml + staging.yml)
and `prod` (base.yml + staging.yml + prod.yml) — same Compose project name
`catalog`, different `DOMAIN_NAME`. Staging is therefore a release state of
the same stack, not a parallel cluster: the standard sequence is deploy the
staging release, validate, then deploy the prod release.

No Docker Swarm is required: the stack is a plain Docker Compose project,
and rollouts are a rolling `docker compose up -d` (changed containers are
recreated, everything else — and every named volume — is untouched).

## Deployment unit: immutable image references only

The deployment **and** rollback unit is the exact application image
reference (an explicit tag or a digest). `comses/catalog/prod:latest` is no
longer a valid deployment unit:

- `make` release targets **reject** `:latest`, malformed digests, and bare references
  (a bare reference implicitly means `:latest`).
- `CATALOG_IMAGE` and `CATALOG_ES_HOST` are required for every deployment.
- `staging.yml` pins the django service to `image: ${CATALOG_IMAGE}`;
  `scripts/compose.sh` bakes the exact reference into the rendered root
  `docker-compose.yml`.

### Producing an immutable reference

```sh
# 1. Build locally from a tagged/committed checkout, tagged immutably
#    (scripts/deploy.sh runs `docker build` directly):
CATALOG_IMAGE=comses/catalog/prod:v2026.08.27 make image-build

# 2. Make the exact reference resolvable on the deploy host, either by
#    pushing it to a registry the host can reach:
docker push comses/catalog/prod:v2026.08.27
#    or by pinning the immutable digest of what was pushed:
docker buildx imagetools inspect comses/catalog/prod:v2026.08.27
#    then deploy with comses/catalog/prod@sha256:<digest>
```

Prefer digest references (`name@sha256:...`) when a registry tag could ever
be re-pushed; an explicit content tag is acceptable only if the tag is
guaranteed immutable.

### Release state is recorded before every rollout

`scripts/deploy.sh` keeps the release state in non-secret files under
`deploy/state/` (git-ignored):

1. `deploy/state/release.env` — the current release (environment, image,
   ES host, timestamp) and the previous one (the rollback unit):

   ```
   CATALOG_ENV=prod
   CATALOG_IMAGE=comses/catalog/prod:v2026.08.27
   CATALOG_ES_HOST=elasticsearch
   DEPLOYED_AT=2026-08-27T09:15:00Z
   PREVIOUS_ENV=staging
   PREVIOUS_IMAGE=comses/catalog/prod:v2026.08.20
   PREVIOUS_ES_HOST=elasticsearch
   ```

2. `deploy/state/deploy-history.log` — an append-only, timestamped line per
   rollout (override the path with `DEPLOY_HISTORY_FILE`):

   ```
   2026-08-27T09:15:00Z env=prod previous_image=comses/catalog/prod:v2026.08.20 previous_es_host=elasticsearch next_image=comses/catalog/prod:v2026.08.27 next_es_host=elasticsearch
   ```

Before anything on the running release changes, the deploy verifies the
requested reference resolves on the host (local image or `docker pull`); if
it cannot, the deploy aborts and the old release keeps running. The rendered
compose file is kept at the repository root as `docker-compose.yml`, so
ordinary `docker compose` commands and `make start` / `make stop` always
operate on the last rendered release. On the first lifecycle command after
upgrading from the old layout, a legacy `deploy/state/docker-compose.yml` is
moved to the root automatically.

## Hard operational prerequisites

The steps below **do not assert** that these prerequisites are in place.
Verify each one before any deploy; `scripts/deploy.sh` cannot check them for
you.

1. **Docker**: a single Docker host with Docker Compose v2. No Swarm is
   required. The host's `vm.max_map_count` must satisfy Elasticsearch
   (>= 262144).
2. **Credentials**: the files under `deploy/conf/` (`config.ini`,
   `postgres_password`) must exist on the deploy host — `make config-validate`
   checks this, and `scripts/deploy.sh` preflight enforces it. The compose
   file mounts them into the django and db services.
3. **Storage**:
   - Postgres data: bind mount `./docker/shared/pgdata` must already hold
     the database (or be restored through the database maintenance workflow,
     `make restore`).
   - Named volumes `esdata` (ES6 data), `esdata8` (ES8 data), `solr`,
     `static`, `gunicornsocket` persist across rollouts. An **empty
     `esdata8` is not a problem** for an ES8 cutover: `rebuild_es_index`
     recreates the indices from PostgreSQL.
   - `docker/shared/catalog/logs` and `docker/shared/nginx/logs` (created
     automatically by the deploy target).
4. **Image resolvability**: the immutable reference must be resolvable on
   the host (registry reachability, or the image pre-loaded/built there).
5. **Endpoint/DNS**: `DOMAIN_NAME` (`staging-catalog.comses.net` /
   `catalog.comses.net`) resolves to the host and port 80 is published by
   nginx.

**Solr 6 has not been removed as a dependency.** `base.yml` still defines a
required `solr` service (`comses/catalog/solr:6.6`, built from
`deploy/images/solr.Dockerfile`) alongside `elasticsearch` (6.6.2) and
`elasticsearch8` — all three are started by every deploy today. That image
is not published to any registry, so `make deploy` now runs
`docker compose build solr` before `up --no-build` to build it locally
on the deploy host if it's missing or stale (a fresh host previously hit
`pull access denied for comses/catalog/solr` because `--no-build` tried to
pull it instead of building it).

### Why three search backends run at once

None of Solr, ES6, or ES8 has been retired; each is kept running until its
replacement is proven safe to cut over to (see [README.md](../README.md)'s
"migrate fully from Solr to elasticsearch" maintenance note):

- **Solr 6** is the original, still-authoritative backend for some search
  paths — Django's `SOLR_HOST`/`SOLR_PORT`/`SOLR_CORE_NAME` settings and the
  citation admin/model sync code still depend on it, so it cannot be
  dropped from the stack yet.
- **Elasticsearch 6.6.2** (`elasticsearch`) is the current default
  application ES endpoint (`CATALOG_ES_HOST=elasticsearch`), a step already
  taken away from Solr for the read paths it serves.
- **Elasticsearch 8** (`elasticsearch8`) is the migration target. It runs
  from the first deploy so it can be rebuilt and validated (`make
  es8-rebuild` / `make es8-validate`) against live data before any release
  is cut over to it (see ES8 cutover below), and it stays up afterward so a
  rollback to an ES6-backed release remains possible.


## Standard release (ES6 endpoint)

```sh
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-build
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-push
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> CATALOG_ES_HOST=elasticsearch make deploy ENV=staging
# smoke-test the staging domain, then promote that exact release to prod:
make deploy ENV=prod
make status   # recorded current + previous release, container status
```

`CATALOG_ES_HOST=elasticsearch` explicitly selects Elasticsearch 6.6.2.

### Promotion: `make deploy ENV=prod` with no other variables

`scripts/deploy.sh` records the image and ES host of the last deploy in
`deploy/state/release.env` regardless of environment. When `CATALOG_IMAGE`
and/or `CATALOG_ES_HOST` are omitted, `deploy` fills them in from that
recorded release instead of failing, so once a release has been deployed
and smoke-tested on staging, promoting it to prod is exactly:

```sh
make deploy ENV=prod
```

This redeploys the **identical** image/ES host that was just validated on
staging — no re-typing the tag, no risk of prod drifting to a different
build. It is still a normal, recorded rollout: `deploy/state/release.env`
and `deploy/state/deploy-history.log` are updated, and `make rollback`
reverts it the same way as any other deploy. Pass `CATALOG_IMAGE=` and/or
`CATALOG_ES_HOST=` explicitly whenever prod should run something other than
the last-deployed release (e.g. redeploying an older tag directly to prod
without going through staging first).

## ES8 cutover (gated): rebuild + validate BEFORE switching any release to ES8

The application ES endpoint is the per-release env var
`ELASTICSEARCH_HOST` (composed into `settings.ELASTICSEARCH` at runtime).
A release only runs against ES8 when it is deployed with
`CATALOG_ES_HOST=elasticsearch8`. Never switch an already-running release by
changing only that endpoint (see Rollback).

Precondition: a release is already deployed on the `catalog` stack (any
endpoint) and the ES8 container is healthy. `make es8-rebuild` health-checks
ES8 first and fails early if it is down; for a manual check:

```sh
docker compose --project-directory . -p catalog \
    exec -T elasticsearch8 curl -fsS 'http://localhost:9200/_cluster/health?pretty'
# expect: cluster status green or yellow, no unassigned shards
```

### 1. Rebuild the public indices against ES8 (one-off Compose command)

```sh
make es8-rebuild
```

This runs `rebuild_es_index` from the **deployed django image** in a one-off
Compose container pointed at ES8 (`docker compose run --rm --no-deps
-e ELASTICSEARCH_HOST=elasticsearch8 django python3 manage.py
rebuild_es_index`). The running release may still be on ES6 — that does not
matter, this only talks to ES8 and Postgres.

The command runs in the foreground and is removed on exit (`--rm`): a clean
exit means success; a nonzero exit means failure — do **not** continue the
cutover. Its output is streamed to the terminal while it runs; capture that
output (e.g. `make es8-rebuild 2>&1 | tee es8-rebuild.log`) if you need it
after the fact.

`manage.py rebuild_es_index` rebuilds every public read alias
(`publication`, `author`, `container`, `platform`, `sponsor`, `tag`) into
fresh generation indices (`<alias>-<utc-stamp>`), validates each document
count, and swaps the aliases atomically. It **exits nonzero** on any bulk
failure, count mismatch, or alias-swap failure, and on failure leaves the
live read aliases untouched.

### 2. Validate ES8 before switching any application release to it

```sh
make es8-validate
```

This checks, via one-off Compose execs into the running containers:

- (a) every read alias (`publication`, `author`, `container`, `platform`,
  `sponsor`, `tag`) exists on ES8 and points at a generation index,
- (b) the ES8 publication count equals the database count
  (`Publication.api.primary().filter(status='REVIEWED')`),
- (c) a live `match_all` query against `publication/_search` works.

Manual equivalent (after `make es8-rebuild` succeeded):

```sh
COMPOSE=(docker compose --project-directory . -p catalog)
"${COMPOSE[@]}" exec -T elasticsearch8 curl -fsS 'http://localhost:9200/_alias?pretty'
"${COMPOSE[@]}" exec -T elasticsearch8 curl -fsS 'http://localhost:9200/publication/_count'
"${COMPOSE[@]}" exec -T django python3 manage.py shell -c \
    "from citation.models import Publication; print(Publication.api.primary().filter(status='REVIEWED').count())"
"${COMPOSE[@]}" exec -T elasticsearch8 curl -fsS -H 'Content-Type: application/json' \
    -d '{"size":1,"query":{"match_all":{}}}' 'http://localhost:9200/publication/_search'
```

Only after the rebuild succeeded and validation passes may a release be
switched to ES8.

### 3. Switch the release to ES8 (a release change, not a config tweak)

Either the gated one-shot (rebuild + validate + deploy):

```sh
CATALOG_IMAGE="<CATALOG_IMAGE>" CONFIRM_ES8_CUTOVER=1 make es8-cutover ENV=staging
```

or the manual sequence:

```sh
CATALOG_IMAGE="<CATALOG_IMAGE>" CATALOG_ES_HOST=elasticsearch8 make deploy ENV=staging
# smoke-test: search on the staging domain, autocomplete, facet counts;
# check for ES errors:
docker logs --since 10m catalog-django-1
# then the same for prod:
CATALOG_IMAGE="<CATALOG_IMAGE>" CATALOG_ES_HOST=elasticsearch8 make deploy ENV=prod
```

## Rollback

**Rollback is redeploying the recorded prior release (environment +
immutable image + ES host). It is not an endpoint-only change** (pointing a
running release at a different endpoint without redeploying is not a
rollback: the prior release is the unit that was validated against the prior
index state).

```sh
make status    # shows the recorded current and previous release
make rollback  # redeploys the recorded previous release, as recorded
```

Verify: `make status` shows the django container running with the previous
image, and search works on the domain.

Notes:

- The recorded reference is the exact release that was running before the
  rollout, so rollback is deterministic and does not depend on any mutable
  tag. Because the rollout is a rolling `docker compose up -d`, rollback
  redeploys that release the same safe way — no teardown, no volume
  deletion.
- The ES6 service (`elasticsearch`, data in `esdata`) stays deployed by
  `base.yml` for the lifetime of the rollback window; do not remove it while
  ES6 rollbacks are possible.
- ES8 index state is independent of the application rollback: generation
  indices and the previous generation per alias are retained by
  `rebuild_es_index`, so an ES8 alias rollback is a separate, index-level
  operation and is not part of the application rollback.

## Day-2 commands

```sh
make status                    # recorded release + container status
make stop                      # stop containers (networks + volumes kept)
make start                     # restart the last rendered release
make backup                    # create compressed database backup in /shared/backups/postgres
make restore                   # restore Postgres from catalog.sql + reindex
make release-version           # write release-version.txt (git describe)
```

Notes:

- `make stop`/`make start` never delete volumes or networks; `make stop`
  is the only "down" on the deployment surface.
- `make backup` runs `invoke backup` inside the running django container,
  which generates a timestamped, gzip-compressed dump in
  `/shared/backups/postgres/` using `pg_dump` and prunes old backups to retain
  the last 14 copies.
- `make restore` copies `catalog.sql` into the running django container and
  runs `invoke restore-from-dump`. That task **refuses to run when the
  database already contains publications** (use `invoke rfd -f` inside the
  container to override) and reinitializes the schema + search indices.
