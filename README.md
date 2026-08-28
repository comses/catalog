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
./compose dev
./build.sh
docker-compose up -d
```

Then the database and search indices need to be loaded and populated with data

```
docker-compose exec django bash
inv rfd -f
inv ri
./manage.py populate_visualization_cache
```

## Deployment (staging / prod)

Staging and prod are deployed to Docker Swarm via `deploy.sh`. The
deployment **and** rollback unit is an **immutable application image
reference** (explicit tag or digest); `prod:latest` is rejected by the
deploy flow. Before every rollout, `deploy.sh` records the currently
deployed image (service label `comses.catalog.previous-image` plus an
append-only `docker/deploy-history.log`) — that recorded reference is what
a rollback redeploys, with the ES6 endpoint.

```
./deploy.sh build comses/catalog/prod:<immutable-tag>
docker push comses/catalog/prod:<immutable-tag>     # if the swarm manager cannot see the local build
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> ./deploy.sh deploy staging
CATALOG_IMAGE=comses/catalog/prod:<immutable-tag> ./deploy.sh deploy prod
```

Switching a release to Elasticsearch 8 is a **gated action**: run
`manage.py rebuild_es_index` against ES8 and validate the rebuilt indices
*before* deploying any release with `CATALOG_ES_HOST=elasticsearch8`
(releases run on ES6 by default). The full procedure — including hard
operational prerequisites (swarm secrets/storage, registry) and the
rollback steps — is in [docs/deployment-runbook.md](docs/deployment-runbook.md).
