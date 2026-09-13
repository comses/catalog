SHELL := /bin/bash

COMPOSE ?= docker compose
FORCE ?= 0

.DEFAULT_GOAL := help

.PHONY: help compose-dev compose-staging compose-prod config-generate config-validate bootstrap up down logs shell clean migrations-check test check test-all cite-config cite-build cite-up cite-down cite-test cite-check cite-migrations-check cite-format cite-lock cite-publish image-build image-push release-version deploy rollback status start stop backup restore es8-rebuild es8-validate es8-cutover

help:
	@printf '%s\n' \
		'Catalog commands:' \
		'  bootstrap              Render development Compose config and create credentials' \
		'  up | down | logs       Manage the local development stack' \
		'  shell                  Open a shell in the Django service' \
		'  check                  Run Django system checks' \
		'  migrations-check       Verify committed Django migrations' \
		'  test                   Run the catalog test suite' \
		'  test-all               Run catalog and citation test suites' \
		'  config-generate        Create credentials; use FORCE=1 to rotate existing files' \
		'  config-validate        Verify local credential files exist and are nonempty' \
		'  cite-<target>          Delegate config, build, up, down, test, check, migrations-check, format, lock, or publish to citation/' \
		'' \
		'Release commands (single-host Docker Compose, project "catalog";' \
		'  ENV=staging|prod for deploy/es8-cutover; CATALOG_IMAGE required;' \
		'  CATALOG_ES_HOST required for deploy/es8-cutover):' \
		'  image-build | image-push' \
		'  deploy | rollback | status | start | stop' \
		'  backup | restore | release-version' \
		'  es8-rebuild | es8-validate | es8-cutover'

compose-dev:
	bash scripts/compose.sh dev

compose-staging:
	bash scripts/compose.sh staging

compose-prod:
	bash scripts/compose.sh prod

config-generate:
	FORCE=$(FORCE) bash scripts/config.sh generate

config-validate:
	bash scripts/config.sh validate

bootstrap: compose-dev config-generate

up: compose-dev config-validate
	$(COMPOSE) up -d

down: compose-dev
	$(COMPOSE) down --remove-orphans

logs: compose-dev
	$(COMPOSE) logs -f

shell: compose-dev
	$(COMPOSE) exec django bash

clean: compose-dev
	$(COMPOSE) down --volumes --remove-orphans

migrations-check: compose-dev config-validate
	$(COMPOSE) run --rm django python3 manage.py makemigrations --check --dry-run

test: compose-dev config-validate
	$(COMPOSE) run --rm django /code/deploy/docker/test.sh

check: compose-dev config-validate
	$(COMPOSE) run --rm django python3 manage.py check

test-all: test cite-config cite-test

cite-config:
	bash scripts/citation-config.sh

cite-build cite-up cite-down cite-test cite-check cite-migrations-check cite-format cite-lock cite-publish:
	$(MAKE) -C citation $(@:cite-%=%)

image-build:
	CATALOG_IMAGE="$(CATALOG_IMAGE)" bash scripts/deploy.sh build

image-push:
	CATALOG_IMAGE="$(CATALOG_IMAGE)" bash scripts/deploy.sh push

release-version:
	bash scripts/deploy.sh tag

# deploy requires ENV=staging|prod plus CATALOG_IMAGE and CATALOG_ES_HOST;
# it runs the preflight checks and performs a rolling `docker compose up -d`
# (no down, no volume deletion). State lives in deploy/state/.
deploy:
	CATALOG_IMAGE="$(CATALOG_IMAGE)" CATALOG_ES_HOST="$(CATALOG_ES_HOST)" bash scripts/deploy.sh deploy "$(ENV)"

rollback:
	bash scripts/deploy.sh rollback

status:
	bash scripts/deploy.sh status

stop:
	bash scripts/deploy.sh stop

start:
	bash scripts/deploy.sh start

backup:
	bash scripts/deploy.sh backup

restore:
	bash scripts/deploy.sh restore

es8-rebuild:
	bash scripts/deploy.sh es8-rebuild

es8-validate:
	bash scripts/deploy.sh es8-validate

es8-cutover:
	CATALOG_IMAGE="$(CATALOG_IMAGE)" CONFIRM_ES8_CUTOVER="$(CONFIRM_ES8_CUTOVER)" bash scripts/deploy.sh es8-cutover "$(ENV)"