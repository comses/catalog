# catalog
[![Catalog Docker CI](https://github.com/comses/catalog/actions/workflows/docker-build.yml/badge.svg)](https://github.com/comses/catalog/actions/workflows/docker-build.yml)

Provides web tools for annotating and managing bibliographic references for publications that reference computational artifacts. Developed by  [CoMSES Net](http://www.comses.net) to catalog the current state of reproducible scientific computation up to early 2019.

# Community support needed: in search of maintainers

If you find this software useful please consider stepping up to help us support it in the Open Source spirit. We're looking for maintainers, so let us know if you are interested in contributing! The [citation](https://github.com/comses/citation/) Python package is also a key component that would need maintenance alongside.

Maintenance would be to keep up with dependency upgrades, migrate fully from Solr to elasticsearch, etc.

## Development Environment
To build a development environment for the project you will need to install:

* Up-to-date versions of [Docker](https://docs.docker.com/engine/installation/) and [Docker Compose](https://docs.docker.com/compose/install/)

## Development Environment Setup

```
git clone --recurse-submodules git@github.com:comses/catalog.git
cd catalog
make bootstrap
make up
```

Then the database and search indices need to be loaded and populated with data

```
make shell
inv rfd -f
inv ri
./manage.py populate_visualization_cache
```

## Deployment (staging / prod)

Use the root `Makefile` as the supported deployment interface. Staging and
prod share the single Compose project `catalog`. A release is an immutable
application image reference (explicit tag or digest; `:latest`, bare
references, and malformed digests are rejected) together with an explicit
`CATALOG_ES_HOST` (`elasticsearch` or `elasticsearch8`).

The root `docker-compose.yml` is the last-known-good generated release
configuration. A deploy renders a temporary candidate and runs Compose from
that candidate; only after `docker compose up -d --wait` succeeds is the
candidate atomically published at the root. If rendering, image resolution,
build, or startup fails, the previous root file and any legacy fallback remain
untouched. `deploy/state/release.env` and `deploy/state/deploy-history.log`
hold non-secret release metadata; they are not Compose files.

```
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-build
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-push
# Fresh host: schema-migrate starts only the candidate database.
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> CATALOG_ES_HOST=elasticsearch \
CONFIRM_PRODUCTION_MIGRATION=1 make schema-migrate ENV=staging
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> CATALOG_ES_HOST=elasticsearch make deploy ENV=staging
# Smoke-test staging, then promote the recorded image and endpoint:
make deploy ENV=prod
make status
```

For a new release, `ENV`, `CATALOG_IMAGE`, and `CATALOG_ES_HOST` are required.
When deploying with an existing release state, either missing image or
endpoint variable is filled from the current recorded release; this makes
`make deploy ENV=prod` the promotion form. Supplying values explicitly starts
a different release. A direct successful prod-to-prod deploy replaces the
anchor with the immediately prior prod tuple. A staging deploy replacing a
tracked prod release likewise records that immediately prior prod tuple before
generic release state changes; staging-to-prod promotion then preserves it.
Staging can never become the rollback target.

Schema changes are never automatic. Run the explicit, confirmed
`schema-migrate` once before the staging deploy; on a subsequent release,
run `make backup` first. Staging and prod share a database, so do not run the
migration again during promotion. Migrations should use an
expand/contract-compatible application rollout. There is no automatic schema
rollback; investigate failed or partly applied migrations manually.

For inspection only, root Compose commands such as `docker compose ps`,
`docker compose logs`, and `docker compose config` may be used. Do not use
ordinary root `docker compose up` or `down` as a deployment procedure; use
`make deploy`, `make start`, or `make stop`.

Switching a release to Elasticsearch 8 is a **gated action**: use
`CATALOG_IMAGE=<current-image> CONFIRM_ES8_CUTOVER=1 make es8-cutover ENV=staging`.
This performs the rebuild, validation, and deployment as one path; the image
must be the already deployed candidate. See [docs/deployment-runbook.md](docs/deployment-runbook.md)
for operational prerequisites, lifecycle, rollback, and migration details.
