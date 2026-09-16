# Deployment runbook

This runbook covers the single-host Docker Compose project `catalog`. Use the
root `Makefile` for every deployment mutation. Staging and prod use the same
stack and project name; normally deploy to staging, validate, then promote the
same release to prod.

## Release contract

`CATALOG_IMAGE` must be an immutable reference: an explicit tag guaranteed not
to be retagged, or a `sha256` digest. `:latest`, bare references, and malformed
digests are rejected. `CATALOG_ES_HOST` must be explicitly selected as
`elasticsearch` (ES 6.6.2) or `elasticsearch8` (ES 8.15.5). There is no ES
default for a first deployment.

With an existing `deploy/state/release.env`, omitted image and endpoint values
are filled from the current recorded release. Thus promotion is:

```sh
make deploy ENV=prod
```

For a new or intentionally different release, provide all values:

```sh
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> \
CATALOG_ES_HOST=elasticsearch make deploy ENV=staging
```

Build and publish the exact image separately when needed:

```sh
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-build
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-push
```

The deploy preflight validates credentials, image immutability and image
resolvability before changing the running stack. Solr is built locally before
Compose startup because its image is not published.

## Root config and state safety

`docker-compose.yml` at the repository root is generated release config and
must be treated as the last-known-good deployment file. `deploy/state/` holds
metadata (`release.env`, `production-rollback.env`, and the append-only history
log), not the canonical Compose file. `production-rollback.env` is the prior
production tuple used by `make rollback`. A direct prod-to-prod deploy replaces
it with the immediately prior prod tuple. A staging deploy replacing a tracked
prod release also records that immediately prior prod tuple before generic
release state changes; promotion then preserves it.

Deployment renders a temporary candidate and runs `up -d --wait` against it.
Only successful startup publishes that candidate atomically at the root and
removes a legacy `deploy/state/docker-compose.yml`. Any render, pull, build, or
startup failure leaves both the old root file and legacy fallback untouched.

Lifecycle commands reconcile the selected Compose file with release metadata.
Missing/incompatible state, a stale root file, or both root and legacy files
being present fails closed; the root file is never silently preferred. Resolve
a legacy migration or conflict manually, then use Make commands again.

## Prerequisites

- Docker Compose v2 and a reachable single Docker host; no Swarm is required.
- Elasticsearch hosts should meet the host prerequisite `vm.max_map_count >= 262144`.
- `deploy/conf/config.ini` and `deploy/conf/postgres_password` must exist and
  be nonempty. Run `make config-validate`.
- The Postgres bind mount is `./docker/pgdata`. Named volumes include
  `catalog_esdata`, `catalog_esdata8`, `catalog_solr`, `catalog_static`, and
  `catalog_gunicornsocket`; deployment lifecycle commands do not delete them.
- Deploy creates `docker/shared/catalog/logs` and
  `docker/shared/nginx/logs`.
- The selected image must be available locally or pullable, and the staging or
  production DNS name must reach the host on port 80.

## Development boundary and inspection

`make bootstrap` followed by `make up` is the normal local development flow.
`make down` and `make clean` are local operations; `clean` also removes local
volumes. `make shell`, tests, checks, and migration checks are development
operations too.

When deployment metadata exists, development-mutating targets refuse to render
or operate on the checkout. An intentional override is explicit:

```sh
DEV_OVERRIDE=1 make up       # likewise shell, down, clean, or compose-dev
```

Do not use that override on a deployment checkout unless the consequence is
understood. `make logs` is inspection and uses the existing selected
root-or-legacy configuration in one process.
For deployment observability and lifecycle use:

```sh
make status                  # metadata plus catalog containers
make logs                    # existing Compose configuration
make stop                    # stop containers; keep networks and volumes
make start                   # restart the recorded release
```

Plain root `docker compose` commands are inspection-only guidance (`ps`,
`logs`, `config`). They do not provide a safe deployment/up/down interface.

## Standard release and rollback

Schema changes are explicit and never run automatically. For a release that
contains migrations on a fresh host, use this order:

```sh
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> \
CATALOG_ES_HOST=elasticsearch CONFIRM_PRODUCTION_MIGRATION=1 \
make schema-migrate ENV=staging
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> \
CATALOG_ES_HOST=elasticsearch make deploy ENV=staging
# smoke-test staging, then promote without rerunning schema-migrate:
make deploy ENV=prod
```

`schema-migrate` requires an explicit immutable image, explicit ES host, and
`CONFIRM_PRODUCTION_MIGRATION=1`. It verifies credentials and database
readiness. On a fresh host (no release state, no legacy file, and no existing
`catalog` containers), it starts only the candidate database so this command
can bootstrap the database. It renders a temporary candidate and runs these
commands there, in order: `makemigrations --check --dry-run`,
`migrate --plan`, `migrate --noinput`, and `migrate --check`. It never
publishes the candidate or changes Compose/release/history state. A normal
deploy performs only a non-mutating `migrate --check` guard and refuses pending
migrations.
Because staging and prod share the database, apply the migration once. Use
expand/contract-compatible changes when old and new application versions can
overlap. There is no automatic schema rollback; a failed or partly applied
migration requires manual investigation before retrying. For later releases,
an existing tracked deployment is required and `schema-migrate` uses its
existing database without starting a new stack; run `make backup` before it.
Do not reapply the migration during promotion.

For a subsequent release, the complete sequence is:

```sh
make backup
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> \
CATALOG_ES_HOST=elasticsearch CONFIRM_PRODUCTION_MIGRATION=1 \
make schema-migrate ENV=staging
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> \
CATALOG_ES_HOST=elasticsearch make deploy ENV=staging
# smoke-test, then promote the same image/endpoint:
make deploy ENV=prod
```

After staging smoke tests, promote with `make deploy ENV=prod`. A successful
deploy records current and previous environment, image, endpoint, and time in
`deploy/state/release.env` (its previous fields are informational; rollback
uses the production anchor); history is appended after success. A successful
prod deploy that replaces an existing prod release also updates
`production-rollback.env` to that prior prod tuple. A staging deployment that
replaces an existing prod release likewise records that prior prod tuple;
staging is never a production rollback target. The deployment operation recreates changed
services as needed, but this is not a promise of zero downtime.

Rollback is a release redeploy, never an endpoint-only edit:

```sh
make status
make rollback
make status
```

It uses the dedicated recorded prior-production environment, immutable image,
and ES endpoint. If no prior production deploy exists, rollback fails closed.
`make stop`/`make start` are the production-safe lifecycle pair; they do not
tear down networks or delete volumes. Database operations are:

```sh
make backup
make restore
```

`make backup` invokes the application backup task in the running Django
container. `make restore` requires `catalog.sql`, prompts for confirmation, and
runs the application restore task.

## ES8 cutover

ES8 remains a separate, explicitly gated decision. With a deployed release and
healthy ES8 container, run the single cutover command:

```sh
CATALOG_IMAGE=<already-deployed-image> CONFIRM_ES8_CUTOVER=1 \
make es8-cutover ENV=staging
```

The command rejects a different image, then runs the foreground ES8 rebuild,
alias/count/query validation, and the ES8 deployment. It does not accept a
normal `make deploy` transition from ES6 to ES8. After staging smoke tests,
promote the same release with `make deploy ENV=prod`; the recorded ES8 endpoint
is reused. Run the same gated command for prod only when a separate prod
cutover is intended.

The existing direct search routes and ES8 alias/index behavior are unchanged;
this runbook does not redesign them. Keep ES6 data available while ES6-backed
rollback remains possible. ES8 index/alias rollback is a separate operational
decision from application release rollback.

## Legacy migration

Do not run or delete `deploy/state/docker-compose.yml` manually as part of a
normal rollout. A legacy-only checkout can be used by validated lifecycle
commands as a fallback. If both the legacy file and root file exist, commands
fail closed rather than choosing one. Resolve the conflict by an operator,
verify the release metadata and selected file agree, then continue with
`make status`, `make start`, `make stop`, or `make deploy`.

The old root `./deploy.sh` is a deprecation error and performs no action. Use
the Make targets listed above.
