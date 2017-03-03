# catalog
[![Build Status](https://travis-ci.org/comses/catalog.svg?branch=master)](https://travis-ci.org/comses/catalog)
[![Coverage Status](https://coveralls.io/repos/github/comses/catalog/badge.svg?branch=master)](https://coveralls.io/github/comses/catalog?branch=master)
[![Code Health](https://landscape.io/github/comses/catalog/master/landscape.svg?style=flat)](https://landscape.io/github/comses/catalog/master)

Provides web tools for annotating and managing bibliographic references for publications that reference computational artifacts. Developed by  [CoMSES Net](http://www.comses.net) to catalog the state of reproducible scientific computation.

## Development Environment
To build a development environment for the project you will need to install:

* Up-to-date versions of [Docker](https://docs.docker.com/engine/installation/) and [Docker Compose](https://docs.docker.com/compose/install/)

Copy `development.yml` to `docker-compose.yml` and then run `docker-compose up django` to build and bring up a `solr` instance, `postgres` container, and the
`Django` web app container.
