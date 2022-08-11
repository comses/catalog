# catalog
[![Catalog Docker CI](https://github.com/comses/catalog/actions/workflows/docker-build.yml/badge.svg)](https://github.com/comses/catalog/actions/workflows/docker-build.yml)

Provides web tools for annotating and managing bibliographic references for publications that reference computational artifacts. Developed by  [CoMSES Net](http://www.comses.net) to catalog the state of reproducible scientific computation.

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
