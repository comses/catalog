catalog
=======

Provides web tools for annotating and managing bibliographic references for publications that involve computational modeling. Developed by  [CoMSES Net](http://www.openabm.org) to catalog the state of computational model archival.

To build a development environment for the project you will need to install:

* [Docker Compose](https://docs.docker.com/compose/install/), version 1.6 or later

Copy `development.yml` to `docker-compose.yml` and then run `docker-compose up django` to build and bring up a `solr` instance, `postgres` container, and the
`Django` web app container.

[![Build Status](https://travis-ci.org/comses/catalog.svg?branch=master)](https://travis-ci.org/comses/catalog)
[![Coverage Status](https://coveralls.io/repos/comses/catalog/badge.svg)](https://coveralls.io/r/comses/catalog)
[![Code Health](https://landscape.io/github/comses/catalog/master/landscape.svg?style=flat)](https://landscape.io/github/comses/catalog/master)
