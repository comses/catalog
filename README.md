# catalog
[![Build Status](https://travis-ci.org/comses/catalog.svg?branch=master)](https://travis-ci.org/comses/catalog)
[![Coverage Status](https://coveralls.io/repos/github/comses/catalog/badge.svg?branch=master)](https://coveralls.io/github/comses/catalog?branch=master)
[![Code Health](https://landscape.io/github/comses/catalog/master/landscape.svg?style=flat)](https://landscape.io/github/comses/catalog/master)

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
```
