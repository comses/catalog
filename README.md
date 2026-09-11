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

Staging and prod are deployed to a single Docker host as one Docker Compose
stack (project `catalog`) via Make targets. The deployment **and** rollback
unit is an **immutable application image reference** (explicit tag or
digest); `:latest` is rejected. Every release explicitly selects its
Elasticsearch endpoint. Before every rollout, the deployment records the
currently deployed release (environment, image, endpoint) in
`deploy/state/release.env` plus an append-only `deploy/state/deploy-history.log`;
a rollback redeploys the recorded previous release. Rollouts are a rolling
`docker compose up -d` — no teardown, and named volumes are never deleted.

```
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-build
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> make image-push
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> CATALOG_ES_HOST=elasticsearch make deploy ENV=staging
# Smoke-test staging, then:
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> CATALOG_ES_HOST=elasticsearch make deploy ENV=prod
make status                    # recorded release + container status
make rollback                  # redeploy the recorded previous release
```

Switching a release to Elasticsearch 8 is a **gated action**: run
`make es8-rebuild` and `make es8-validate` (Compose one-off commands) before
deploying any release with `CATALOG_ES_HOST=elasticsearch8`. The full
procedure — including hard operational prerequisites (storage, registry) and
the rollback steps — is in [docs/deployment-runbook.md](docs/deployment-runbook.md).
