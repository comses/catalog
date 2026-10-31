SHELL := /bin/bash

COMPOSE ?= docker compose
FORCE ?= 0
DEV_OVERRIDE ?= 0
ALLOW_DIRTY_BUILD ?= 0
CITATION_OWNER ?= comses
CATALOG_COMPOSE = $(COMPOSE) --project-directory . -p catalog -f docker-compose.yml
CATALOGCTL = PYTHONPATH=scripts python3 -m catalogctl

.DEFAULT_GOAL := help

.PHONY: help compose-dev config-generate config-validate bootstrap up down dev-logs dev-restore shell clean migrations-check test check test-all cite-config cite-build cite-up cite-clean cite-test cite-check cite-migrations-check cite-format cite-lock cite-publish image-build image-push release-version deploy-controller-test storage-prepare storage-preflight configure host-check prepare backup backup-status restore drain migrate rebuild activate validate candidate-retry rollback recover status release-report start stop logs search-rebuild search-validate

help:
	@printf '%s\n' \
		'Local development:' \
		'  bootstrap              Render Compose and create local credentials' \
		'  up | down | dev-logs   Manage the development stack' \
		'  dev-restore            Replace local data from DUMP (requires CONFIRM=comses_catalog)' \
		'  shell                  Open a shell in the Django service' \
		'  check                  Run Django system checks' \
		'  migrations-check       Verify committed Django migrations' \
		'  test | test-all        Run Catalog or Catalog plus Citation tests' \
		'  config-generate        Create local credentials; FORCE=1 rotates them' \
		'  cite-<target>          Delegate a target to citation/' \
		'' \
		'Build:' \
		'  image-build CATALOG_IMAGE=<name:tag>' \
		'  image-push  CATALOG_IMAGE=<name:tag>' \
		'  release-version' \
		'' \
		'Host (run as the operator in /srv/apps/comses-catalog at the manifest commit; each prints a JSON result):' \
		'  make storage-prepare | make storage-preflight' \
		'  make configure HOST_ID=staging|prod [HTTP_BIND=<address>:<port>] [IMPORT_CONFIG=<old config.ini>]' \
		'  make host-check' \
		'  make prepare MANIFEST=<release-manifest.json>     # current release keeps serving' \
		'  make backup | make backup-status [MAX_AGE=<seconds>]' \
		'  make restore DUMP=<dump> CONFIRM=comses_catalog   # fresh host only' \
		'  make drain                                       # stops the writers' \
		'  CONFIRM_SCHEMA_MIGRATION=1 make migrate' \
		'  make rebuild | make activate | make validate' \
		'  CONFIRM_CANDIDATE_RETRY=1 make candidate-retry   # after investigation' \
		'  make status | release-report | rollback | recover' \
		'  make start | stop | logs'

compose-dev:
	DEV_OVERRIDE="$(DEV_OVERRIDE)" bash scripts/deploy.sh dev-compose

config-generate:
	FORCE=$(FORCE) bash scripts/config.sh generate

config-validate:
	bash scripts/config.sh validate

bootstrap: compose-dev config-generate

up: compose-dev config-validate
	$(CATALOG_COMPOSE) up -d

down: compose-dev
	$(CATALOG_COMPOSE) down --remove-orphans

dev-logs: compose-dev
	$(CATALOG_COMPOSE) logs -f

dev-restore: compose-dev config-validate
	DUMP="$(DUMP)" CONFIRM="$(CONFIRM)" bash scripts/dev-restore.sh

shell: compose-dev
	$(CATALOG_COMPOSE) exec django bash

clean: compose-dev
	$(CATALOG_COMPOSE) down --volumes --remove-orphans

migrations-check: compose-dev config-validate
	$(CATALOG_COMPOSE) run --rm django python3 manage.py makemigrations --check --dry-run

test: compose-dev config-validate
	$(CATALOG_COMPOSE) run --rm django /code/deploy/docker/test.sh

check: compose-dev config-validate
	$(CATALOG_COMPOSE) run --rm django python3 manage.py check

test-all: test cite-config cite-test

cite-config:
	bash scripts/citation-config.sh

cite-build cite-up cite-clean cite-test cite-check cite-migrations-check cite-format cite-lock cite-publish:
	$(MAKE) -C citation $(@:cite-%=%)

image-build:
	CATALOG_IMAGE="$(CATALOG_IMAGE)" ALLOW_DIRTY_BUILD="$(ALLOW_DIRTY_BUILD)" bash scripts/deploy.sh build

image-push:
	CATALOG_IMAGE="$(CATALOG_IMAGE)" bash scripts/deploy.sh push

release-version:
	bash scripts/deploy.sh tag

deploy-controller-test:
	python3 -m unittest discover -s scripts/tests -p 'test_*.py'

storage-prepare:
	$(CATALOGCTL) storage-prepare

storage-preflight:
	$(CATALOGCTL) storage-preflight

configure:
	$(CATALOGCTL) configure --host-id "$(HOST_ID)" $(if $(HTTP_BIND),--http-bind "$(HTTP_BIND)",) $(if $(IMPORT_CONFIG),--import-config "$(IMPORT_CONFIG)",)

host-check:
	$(CATALOGCTL) host-check

prepare:
	bash scripts/checkout-citation.sh "$(CITATION_OWNER)"
	$(CATALOGCTL) prepare --manifest "$(MANIFEST)"

backup:
	$(CATALOGCTL) backup

backup-status:
	$(CATALOGCTL) backup-status $(if $(MAX_AGE),--max-age "$(MAX_AGE)",)

restore:
	$(CATALOGCTL) restore --dump "$(DUMP)" --confirm "$(CONFIRM)"

drain:
	$(CATALOGCTL) drain

migrate:
	$(CATALOGCTL) migrate $(if $(filter 1,$(CONFIRM_SCHEMA_MIGRATION)),--confirmed,)

rebuild:
	$(CATALOGCTL) rebuild

activate:
	$(CATALOGCTL) activate

validate:
	$(CATALOGCTL) validate

candidate-retry:
	$(CATALOGCTL) candidate-retry $(if $(filter 1,$(CONFIRM_CANDIDATE_RETRY)),--confirmed,)

rollback:
	$(CATALOGCTL) rollback

recover:
	$(CATALOGCTL) recover

status:
	$(CATALOGCTL) status

release-report:
	$(CATALOGCTL) release-report

start:
	$(CATALOGCTL) start

stop:
	$(CATALOGCTL) stop

logs:
	$(CATALOGCTL) logs

search-rebuild:
	$(CATALOG_COMPOSE) run --rm --no-deps django python3 manage.py rebuild_es_index

search-validate:
	$(CATALOG_COMPOSE) run --rm --no-deps django python3 manage.py validate_search_indexes
