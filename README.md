# catalog
[![Catalog Docker CI](https://github.com/comses/catalog/actions/workflows/docker-build.yml/badge.svg)](https://github.com/comses/catalog/actions/workflows/docker-build.yml)

Provides web tools for annotating and managing bibliographic references for publications that reference computational artifacts. Developed by  [CoMSES Net](http://www.comses.net) to catalog the current state of reproducible scientific computation up to early 2019.

# Community support needed: in search of maintainers

If you find this software useful please consider stepping up to help us support it in the Open Source spirit. We're looking for maintainers, so let us know if you are interested in contributing! The [citation](https://github.com/comses/citation/) is also a key component that would need side maintenance as well.

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
