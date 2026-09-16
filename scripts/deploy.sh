#!/usr/bin/env bash
#
# Deploy the catalog stack on a single Docker host via Docker Compose
# (stable project name: catalog).
#
# The deployment **and** rollback unit is an immutable application image
# reference (explicit tag or digest) TOGETHER WITH an explicit ES endpoint
# (CATALOG_ES_HOST). Mutable image references (:latest, or a bare reference
# whose implicit tag is :latest) are rejected so a rollback can never drift
# to a different image than the one that was recorded before the rollout.
# There is NO ES endpoint default: every release declares the endpoint it
# runs against, and a rollback restores the dedicated prior-production
# anchor. If a deploy
# omits CATALOG_IMAGE/CATALOG_ES_HOST, they default to the last recorded
# release (deploy/state/release.env): this is how a validated staging
# release is promoted to prod with a plain `make deploy ENV=prod`.
#
# The selected release is recorded in non-secret state under deploy/state
# (git-ignored, created on first use):
#   docker-compose.yml               rendered Compose file of the release
#   deploy/state/release.env         current + previous release
#                                    (env, image, ES host, timestamp)
#   deploy/state/deploy-history.log  append-only, timestamped rollouts
#
# deploy/rollback reconcile with `docker compose up -d`: changed containers
# are recreated as needed; named volumes are left untouched. No down, no
# teardown, or volume deletion occurs in the deploy path.

set -o errexit
set -o nounset
set -o pipefail

project_name=catalog
state_dir=deploy/state
compose_file=docker-compose.yml
root_compose_file=docker-compose.yml
legacy_compose_file="${state_dir}/docker-compose.yml"
release_state_file="${state_dir}/release.env"
production_anchor_file="${state_dir}/production-rollback.env"
# Override the history log location with DEPLOY_HISTORY_FILE.
deploy_history_file="${DEPLOY_HISTORY_FILE:-${state_dir}/deploy-history.log}"
# Valid per-release ES endpoints (service names from base.yml).
# Every release must pick one explicitly; there is no default:
#   elasticsearch  = Elasticsearch 6.6.2
#   elasticsearch8 = Elasticsearch 8.15.5 (gated cutover, see runbook)
es_hosts=(elasticsearch elasticsearch8)

die() {
    echo "ERROR: $*" >&2
    exit 1
}

# All commands operate on the stable project name and resolve relative
# paths (./deploy/..., ./docker/shared/...) from the repository root, where
# the rendered operational Compose file lives.
compose() {
    docker compose --project-directory . -p "${project_name}" -f "${compose_file}" "$@"
}

select_operational_compose() {
    # Never silently choose one of two deployment artifacts.  In particular,
    # do not let a stale root file mask the legacy state file.
    if [[ -s "${compose_file}" && -s "${legacy_compose_file}" ]]; then
        die "both ${compose_file} and ${legacy_compose_file} exist; resolve the deployment conflict manually"
    fi
    if [[ -s "${compose_file}" ]]; then
        return 0
    fi
    [[ -s "${legacy_compose_file}" ]] \
        || die "no rendered compose file; run a deploy (make deploy ENV=staging|prod) first"
    compose_file="${legacy_compose_file}"
}

require_release_state() {
    [[ -s "${release_state_file}" ]] \
        || die "missing ${release_state_file}; refusing to operate an untracked Compose deployment"
    load_release_state
    [[ "${release_env}" == staging || "${release_env}" == prod ]] \
        || die "incompatible release metadata in ${release_state_file}"
    validate_image_ref "${release_image}"
    validate_es_host "${release_es_host}"
    select_operational_compose
    validate_compose_matches_release
}

validate_compose_matches_release() {
    local expected_domain
    case "${release_env}" in
        staging) expected_domain=staging-catalog.comses.net ;;
        prod) expected_domain=catalog.comses.net ;;
        *) die "incompatible release environment '${release_env}'" ;;
    esac
    grep -Fq 'name: catalog' "${compose_file}" \
        || die "${compose_file} does not use the catalog Compose project"
    grep -Fq "image: ${release_image}" "${compose_file}" \
        || die "${compose_file} does not match release metadata (image)"
    grep -Fq "ELASTICSEARCH_HOST: ${release_es_host}" "${compose_file}" \
        || die "${compose_file} does not match release metadata (ES host)"
    grep -Fq "DOMAIN_NAME: ${expected_domain}" "${compose_file}" \
        || die "${compose_file} does not match release metadata (environment)"
}

require_compose_file() {
    require_release_state
}

require_dev_override_or_clean() {
    if [[ "${DEV_OVERRIDE:-0}" == 1 ]]; then
        return 0
    fi
    [[ ! -s "${release_state_file}" ]] \
        || die "deployment state is present; refusing a development mutation (set DEV_OVERRIDE=1 only if intentional)"
    if [[ -s "${compose_file}" && -s "${legacy_compose_file}" ]]; then
        die "both root and legacy Compose files exist; refusing development mutation"
    fi
    if [[ -s "${compose_file}" ]] && grep -Fq 'comses.catalog.image' "${compose_file}"; then
        die "root Compose file looks like a deployment but release metadata is missing; refusing development mutation"
    fi
}

require_docker() {
    docker info >/dev/null 2>&1 || die "docker daemon is not reachable"
}

require_config() {
    bash scripts/config.sh validate
}

validate_image_ref() {
    local ref="$1"
    [[ -n "${ref}" ]] || die "CATALOG_IMAGE is required (use an explicit tag or sha256 digest)"
    [[ "${ref}" != *":latest" ]] || die ":latest is mutable and cannot be deployed"
    if [[ "${ref}" == *@* ]]; then
        [[ "${ref}" =~ @sha256:[0-9a-fA-F]{64}$ ]] || die "malformed image digest: ${ref}"
    else
        # Only a colon in the LAST path component is a tag separator; a
        # colon earlier in the reference is a registry port
        # (registry.example.com:5000/name) and does not tag the image.
        local image_name="${ref##*/}"
        [[ "${image_name}" == *":"* && -n "${image_name##*:}" ]] \
            || die "image reference needs an explicit tag: ${ref}"
    fi
}

validate_es_host() {
    local host="$1" known
    [[ -n "${host}" ]] || die "CATALOG_ES_HOST is required (elasticsearch or elasticsearch8)"
    for known in "${es_hosts[@]}"; do
        [[ "${host}" == "${known}" ]] && return 0
    done
    die "unknown CATALOG_ES_HOST '${host}'; expected one of: ${es_hosts[*]}"
}

ensure_image_resolvable() {
    # Pre-flight check, run BEFORE anything on the running release changes:
    # the exact requested reference must resolve on this host. A pull
    # failure means the reference does not exist in a reachable registry,
    # so the deploy is refused instead of substituting a different image.
    if docker image inspect "${CATALOG_IMAGE}" >/dev/null 2>&1; then
        echo "Image ${CATALOG_IMAGE} is present locally"
    else
        echo "Image ${CATALOG_IMAGE} is not present locally; attempting pull"
        docker pull "${CATALOG_IMAGE}" || die "cannot resolve ${CATALOG_IMAGE} on this host; build/push or load the exact image first (refusing to deploy a different image than requested)"
    fi
}

validate_environment() {
    local environment="$1"
    [[ "${environment}" == staging || "${environment}" == prod ]] \
        || die "deployment environment must be staging or prod, got '${environment}'"
}

load_release_state() {
    # The state file is written by this script only, with values that pass
    # the validations above; parse it into fixed variables (no sourcing).
    release_env=none release_image=none release_es_host=none
    previous_env=none previous_image=none previous_es_host=none
    [[ -s "${release_state_file}" ]] || return 0
    local key value
    while IFS='=' read -r key value; do
        case "${key}" in
            CATALOG_ENV) release_env="${value}" ;;
            CATALOG_IMAGE) release_image="${value}" ;;
            CATALOG_ES_HOST) release_es_host="${value}" ;;
            PREVIOUS_ENV) previous_env="${value}" ;;
            PREVIOUS_IMAGE) previous_image="${value}" ;;
            PREVIOUS_ES_HOST) previous_es_host="${value}" ;;
        esac
    done < "${release_state_file}"
}

write_release_state() {
    # $1=env $2=image $3=es_host $4=deployed_at $5..$7=previous release.
    # Non-secret state only (image refs, endpoint, env, timestamp),
    # written atomically.
    local tmp
    mkdir -p "${state_dir}"
    tmp="$(mktemp "${release_state_file}.XXXXXX")"
    {
        echo "CATALOG_ENV=$1"
        echo "CATALOG_IMAGE=$2"
        echo "CATALOG_ES_HOST=$3"
        echo "DEPLOYED_AT=$4"
        echo "PREVIOUS_ENV=$5"
        echo "PREVIOUS_IMAGE=$6"
        echo "PREVIOUS_ES_HOST=$7"
    } > "${tmp}"
    mv "${tmp}" "${release_state_file}"
}

append_history() {
    local environment="$1"
    mkdir -p "$(dirname "${deploy_history_file}")"
    printf '%s env=%s previous_image=%s previous_es_host=%s next_image=%s next_es_host=%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${environment}" \
        "${release_image}" "${release_es_host}" "${CATALOG_IMAGE}" "${CATALOG_ES_HOST}" \
        >> "${deploy_history_file}"
}

preflight() {
    require_docker
    require_config
    validate_image_ref "${CATALOG_IMAGE:-}"
    validate_es_host "${CATALOG_ES_HOST:-}"
    ensure_image_resolvable
    echo "Preflight passed: ${CATALOG_IMAGE} (es_host=${CATALOG_ES_HOST})"
}

verify_database_ready() {
    compose exec -T db pg_isready -U catalog -d comses_catalog >/dev/null \
        || die "database is not ready"
}

restore_after_persistence_failure() {
    local runtime_backup="$1" root_backup="$2" state_backup="$3" anchor_backup="$4" history_backup="$5" candidate="$6"
    local runtime_ok=0
    if [[ -n "${runtime_backup}" ]]; then
        compose_file="${runtime_backup}"
        if compose up -d --no-build --wait; then
            runtime_ok=1
        fi
    else
        compose_file="${candidate}"
        if compose rm -sf >/dev/null 2>&1; then
            runtime_ok=1
        fi
    fi
    restore_deployment_state "${root_backup}" "${state_backup}" "${anchor_backup}" "${history_backup}"
    rm -f "${runtime_backup}" "${root_backup}" "${state_backup}" "${anchor_backup}" "${history_backup}"
    if [[ "${runtime_ok}" == 1 ]]; then
        die "post-start metadata persistence failed; previous runtime and deployment files were restored"
    fi
    die "post-start metadata persistence failed and runtime recovery failed; deployment files were restored where possible, manual intervention is required"
}

host_is_fresh() {
    [[ ! -s "${release_state_file}" && ! -s "${legacy_compose_file}" ]] || return 1
    [[ ! -s "${compose_file}" ]] || ! grep -Fq 'comses.catalog.image' "${compose_file}"
    [[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=${project_name}")" ]]
}

schema_migrate() {
    local environment="$1" candidate operational_compose fresh_host=0
    [[ "${CONFIRM_PRODUCTION_MIGRATION:-}" == 1 ]] \
        || die "set CONFIRM_PRODUCTION_MIGRATION=1 to run an explicit schema migration"
    validate_environment "${environment}"
    [[ -n "${CATALOG_IMAGE:-}" ]] || die "CATALOG_IMAGE is required for schema-migrate"
    [[ -n "${CATALOG_ES_HOST:-}" ]] || die "CATALOG_ES_HOST is required for schema-migrate"
    validate_image_ref "${CATALOG_IMAGE}"
    validate_es_host "${CATALOG_ES_HOST}"
    require_docker
    require_config

    if [[ -s "${release_state_file}" ]]; then
        require_release_state
        operational_compose="${compose_file}"
    elif host_is_fresh; then
        fresh_host=1
        operational_compose="${compose_file}"
    else
        die "no tracked release state on a non-fresh host; refusing schema migration"
    fi
    if [[ "${CATALOG_ES_HOST}" == elasticsearch8 && ( "${fresh_host}" == 1 || "${release_es_host}" != elasticsearch8 ) ]]; then
        die "ES8 schema migration is gated; use make es8-cutover after the ES8 rebuild and validation"
    fi
    ensure_image_resolvable
    if [[ "${fresh_host}" == 0 ]]; then
        verify_database_ready
    fi

    candidate="$(mktemp "${root_compose_file}.schema.XXXXXX")"
    trap 'if [[ "${fresh_host}" == 1 ]]; then compose_file="${candidate}"; compose rm -sf >/dev/null 2>&1 || true; fi; rm -f "${candidate}"' RETURN
    export CATALOG_PREVIOUS_IMAGE="${release_image:-none}"
    export CATALOG_PREVIOUS_ES_HOST="${release_es_host:-none}"
    bash scripts/compose.sh "${environment}" "${candidate}"
    compose_file="${candidate}"
    if [[ "${fresh_host}" == 1 ]]; then
        compose up -d --wait db
    fi
    verify_database_ready
    compose run --rm --no-deps django python3 manage.py makemigrations --check --dry-run
    compose run --rm --no-deps django python3 manage.py migrate --plan
    compose run --rm --no-deps django python3 manage.py migrate --noinput
    compose run --rm --no-deps django python3 manage.py migrate --check
    compose_file="${operational_compose}"
    trap - RETURN
    rm -f "${candidate}"
    echo "Schema migration completed for ${environment}; deploy the tested image with make deploy"
}

deploy_release() {
    local environment="$1"
    validate_environment "${environment}"

    # Load the currently recorded release before validating requested values
    # so a deploy
    # invoked with no CATALOG_IMAGE/CATALOG_ES_HOST promotes that release
    # as-is: after `make deploy ENV=staging` with explicit values and a
    # staging smoke test, `make deploy ENV=prod` alone redeploys that same
    # validated image/ES host to prod.
    load_release_state
    if [[ -z "${CATALOG_IMAGE:-}" ]]; then
        [[ "${release_image}" != "none" ]] \
            || die "CATALOG_IMAGE is required (no prior release recorded to promote)"
        CATALOG_IMAGE="${release_image}"
        echo "CATALOG_IMAGE not set; promoting recorded release image ${CATALOG_IMAGE}"
    fi
    if [[ -z "${CATALOG_ES_HOST:-}" ]]; then
        [[ "${release_es_host}" != "none" ]] \
            || die "CATALOG_ES_HOST is required (no prior release recorded to promote)"
        CATALOG_ES_HOST="${release_es_host}"
        echo "CATALOG_ES_HOST not set; promoting recorded release ES host ${CATALOG_ES_HOST}"
    fi

    preflight

    if [[ "${CATALOG_ES_HOST:-}" == elasticsearch8 && "${release_es_host}" != elasticsearch8 && "${ES8_CUTOVER:-0}" != 1 ]]; then
        die "ES6 to ES8 is a gated transition; use make es8-cutover ENV=${environment}"
    fi

    if [[ -s "${compose_file}" && -s "${legacy_compose_file}" ]]; then
        die "both ${compose_file} and ${legacy_compose_file} exist; resolve the deployment conflict before deploying"
    fi

    # Passed through for the YAML lane's release labels; harmless once the
    # labels are gone.
    export CATALOG_PREVIOUS_IMAGE="${release_image}"
    export CATALOG_PREVIOUS_ES_HOST="${release_es_host}"

    # Render and operate on a candidate.  The last-known-good root file and
    # any legacy fallback remain untouched until Compose reports success.
    local candidate previous_root previous_runtime previous_state previous_anchor previous_history
    previous_root="" previous_runtime="" previous_state="" previous_anchor="" previous_history=""
    if [[ -s "${compose_file}" ]]; then
        previous_root="$(mktemp)"
        cp "${compose_file}" "${previous_root}"
        [[ "${release_env}" == none ]] || previous_runtime="${previous_root}"
    elif [[ -s "${legacy_compose_file}" && "${release_env}" != none ]]; then
        previous_runtime="$(mktemp)"
        cp "${legacy_compose_file}" "${previous_runtime}"
    fi
    if [[ -s "${release_state_file}" ]]; then previous_state="$(mktemp)"; cp "${release_state_file}" "${previous_state}"; fi
    if [[ -s "${production_anchor_file}" ]]; then previous_anchor="$(mktemp)"; cp "${production_anchor_file}" "${previous_anchor}"; fi
    if [[ -s "${deploy_history_file}" ]]; then previous_history="$(mktemp)"; cp "${deploy_history_file}" "${previous_history}"; fi
    candidate="$(mktemp "${compose_file}.deploy.XXXXXX")"
    trap 'rm -f "${candidate}"' RETURN
    bash scripts/compose.sh "${environment}" "${candidate}"
    compose_file="${candidate}"

    verify_database_ready
    compose run --rm --no-deps django python3 manage.py migrate --check \
        || die "pending database migrations; run explicit make schema-migrate before deploying"

    mkdir -p docker/shared/catalog/logs docker/shared/nginx/logs

    # solr is the only service still defined with a `build:` section
    # (comses/catalog/solr:6.6 is not published to any registry); build it
    # locally if it's missing or stale so `up --no-build` below never tries
    # to pull it. This never touches the django image, which is pinned via
    # `image: ${CATALOG_IMAGE}` with no build section.
    compose build solr

    # Reconcile the single-host stack: changed services are recreated as
    # needed; platform services and all named volumes stay untouched.
    compose up -d --no-build --wait

    mv "${candidate}" "${PWD}/docker-compose.yml"
    # Preserve the prior production tuple before generic release metadata is
    # replaced. A staging deploy replacing prod also advances the anchor, so
    # later promotion can roll back to that immediately prior prod release.
    if [[ "${release_env}" == prod ]]; then
        if ! write_production_anchor prod "${release_image}" "${release_es_host}"; then
            restore_after_persistence_failure "${previous_runtime}" "${previous_root}" "${previous_state}" "${previous_anchor}" "${previous_history}" "${root_compose_file}"
        fi
    fi
    if ! write_release_state "${environment}" "${CATALOG_IMAGE}" "${CATALOG_ES_HOST}" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "${release_env}" "${release_image}" "${release_es_host}"; then
        restore_after_persistence_failure "${previous_runtime}" "${previous_root}" "${previous_state}" "${previous_anchor}" "${previous_history}" "${root_compose_file}"
    fi
    if ! append_history "${environment}"; then
        restore_after_persistence_failure "${previous_runtime}" "${previous_root}" "${previous_state}" "${previous_anchor}" "${previous_history}" "${root_compose_file}"
    fi
    rm -f "${legacy_compose_file}"
    rm -f "${previous_root}" "${previous_state}" "${previous_anchor}" "${previous_history}"
    trap - RETURN

    echo "Deployed ${CATALOG_IMAGE} to ${environment} with ${CATALOG_ES_HOST}"
    echo "Previous release metadata: env=${release_env} image=${release_image} es_host=${release_es_host} (${release_state_file})"
    echo "Rollback = make rollback (redeploys the prior production anchor)"
}

write_production_anchor() {
    local tmp
    mkdir -p "${state_dir}"
    tmp="$(mktemp "${production_anchor_file}.XXXXXX")"
    {
        echo "CATALOG_ENV=$1"
        echo "CATALOG_IMAGE=$2"
        echo "CATALOG_ES_HOST=$3"
    } > "${tmp}"
    mv "${tmp}" "${production_anchor_file}"
}

restore_deployment_state() {
    local root_backup="$1" state_backup="$2" anchor_backup="$3" history_backup="$4"
    rm -f "${root_compose_file}"
    [[ -z "${root_backup}" ]] || cp "${root_backup}" "${root_compose_file}"
    rm -f "${release_state_file}"
    [[ -z "${state_backup}" ]] || { mkdir -p "${state_dir}"; cp "${state_backup}" "${release_state_file}"; }
    rm -f "${production_anchor_file}"
    [[ -z "${anchor_backup}" ]] || { mkdir -p "${state_dir}"; cp "${anchor_backup}" "${production_anchor_file}"; }
    rm -f "${deploy_history_file}"
    [[ -z "${history_backup}" ]] || { mkdir -p "$(dirname "${deploy_history_file}")"; cp "${history_backup}" "${deploy_history_file}"; }
}

rollback() {
    # Redeploy the recorded previous production release as-is (immutable image
    # and ES host). It is NOT an endpoint-only change.
    require_docker
    require_release_state
    local key value anchor_env=none anchor_image=none anchor_es_host=none
    [[ -s "${production_anchor_file}" ]] \
        || die "no production rollback anchor in ${production_anchor_file}"
    while IFS='=' read -r key value; do
        case "${key}" in
            CATALOG_ENV) anchor_env="${value}" ;;
            CATALOG_IMAGE) anchor_image="${value}" ;;
            CATALOG_ES_HOST) anchor_es_host="${value}" ;;
        esac
    done < "${production_anchor_file}"
    [[ "${anchor_env}" == prod ]] || die "incompatible production rollback anchor"
    validate_image_ref "${anchor_image}"
    validate_es_host "${anchor_es_host}"
    echo "Rolling back to env=prod image=${anchor_image} es_host=${anchor_es_host}"
    ES8_CUTOVER=1 CATALOG_IMAGE="${anchor_image}" CATALOG_ES_HOST="${anchor_es_host}" \
        deploy_release prod
}

status() {
    require_docker
    require_release_state
    echo "Current release:  env=${release_env} image=${release_image} es_host=${release_es_host}"
    echo "Previous release metadata: env=${previous_env} image=${previous_image} es_host=${previous_es_host}"
    echo
    docker ps --filter "label=com.docker.compose.project=${project_name}" \
        --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
}

stop_stack() {
    require_docker
    require_compose_file
    # Stop containers only: networks and named volumes are kept, so the
    # release restarts with `make start` (or a plain redeploy).
    compose stop
}

start_stack() {
    require_docker
    require_compose_file
    # Bring the last rendered release back up without re-rendering or
    # touching the release state.
    compose up -d --no-build --wait
}

backup_database() {
    require_docker
    require_compose_file
    local container_id
    container_id="$(compose ps -q django | head -n 1)"
    [[ -n "${container_id}" ]] \
        || die "no running django container; start the stack first (make start or make deploy)"
    echo "Creating database backup via invoke backup"
    compose exec -T django invoke backup
}

restore_database() {
    require_docker
    require_compose_file
    [[ -s catalog.sql ]] || die "catalog.sql is missing from the working directory"
    read -r -p 'Restore from catalog.sql (y/N) ' restore_confirm
    [[ "${restore_confirm}" =~ ^[Yy]([Ee][Ss])?$ ]] || return 0
    local container_id
    container_id="$(compose ps -q django | head -n 1)"
    [[ -n "${container_id}" ]] \
        || die "no running django container; start the stack first (make start or make deploy)"
    echo "Copying catalog.sql to the django container"
    docker cp catalog.sql "${container_id}:/code"
    echo "Restoring database"
    compose exec -T django invoke restore-from-dump
}

es8_rebuild() {
    require_docker
    require_compose_file
    # Fail early when ES8 itself is not healthy.
    compose exec -T elasticsearch8 curl -fsS http://localhost:9200/_cluster/health >/dev/null \
        || die "Elasticsearch 8 is not healthy; check the elasticsearch8 container before rebuilding"
    # One-off Compose container from the deployed django image, pointed at
    # ES8: the command reads ELASTICSEARCH_HOST/ELASTICSEARCH_PORT, and the
    # running release may still be on ES6 - that does not matter, this only
    # talks to ES8 and Postgres. Foreground: a clean exit means success, a
    # nonzero exit means failure (output is streamed to this terminal; the
    # --rm container leaves nothing behind).
    compose run --rm --no-deps \
        -e ELASTICSEARCH_HOST=elasticsearch8 \
        -e ELASTICSEARCH_PORT=9200 \
        django python3 manage.py rebuild_es_index
    echo "ES8 rebuild finished successfully. Run make es8-validate before switching any release to ES8."
}

es8_validate() {
    require_docker
    require_compose_file
    local alias index_count database_count
    for alias in publication author container platform sponsor tag; do
        compose exec -T elasticsearch8 curl -fsS "http://localhost:9200/_alias/${alias}" >/dev/null \
            || die "ES8 read alias '${alias}' is missing; run make es8-rebuild first"
    done
    index_count="$(compose exec -T elasticsearch8 curl -fsS http://localhost:9200/publication/_count | sed -n 's/.*"count"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
    database_count="$(compose exec -T django python3 manage.py shell -c "from citation.models import Publication; print(Publication.api.primary().filter(status='REVIEWED').count())")"
    [[ "${index_count}" == "${database_count}" ]] \
        || die "publication count mismatch: ES8=${index_count:-unknown}, database=${database_count:-unknown}"
    compose exec -T elasticsearch8 curl -fsS -H 'Content-Type: application/json' \
        -d '{"size":1,"query":{"match_all":{}}}' http://localhost:9200/publication/_search >/dev/null
    echo "ES8 aliases, publication counts, and query validation succeeded"
}

es8_cutover() {
    local environment="$1"
    [[ "${CONFIRM_ES8_CUTOVER:-}" == 1 ]] || die "set CONFIRM_ES8_CUTOVER=1 to continue"
    validate_environment "${environment}"
    require_release_state
    if [[ -n "${CATALOG_IMAGE:-}" && "${CATALOG_IMAGE}" != "${release_image}" ]]; then
        die "CATALOG_IMAGE must exactly match the already deployed release (${release_image})"
    fi
    CATALOG_IMAGE="${release_image}"
    es8_rebuild
    es8_validate
    ES8_CUTOVER=1 CATALOG_IMAGE="${release_image}" CATALOG_ES_HOST=elasticsearch8 deploy_release "${environment}"
}

dev_compose() {
    require_dev_override_or_clean
    COMPOSE_ALLOW_DEPLOY_RENDER="${DEV_OVERRIDE:-0}" \
        bash scripts/compose.sh dev "${compose_file}"
}

existing_compose() {
    if [[ -s "${compose_file}" && -s "${legacy_compose_file}" ]]; then
        die "both ${compose_file} and ${legacy_compose_file} exist; refusing inspection"
    fi
    if [[ -s "${release_state_file}" ]]; then
        require_release_state
    else
        [[ -s "${compose_file}" ]] || die "no root docker-compose.yml; run make bootstrap first"
    fi
}

logs_stack() {
    require_docker
    existing_compose
    compose logs -f
}

build_image() {
    # Independent of compose rendering: the build needs no CATALOG_ES_HOST
    # and no deploy/conf files. Build the django image directly with the
    # same Dockerfile, build arg, and context that staging.yml declares,
    # tagged with the requested immutable reference.
    validate_image_ref "${CATALOG_IMAGE:-}"
    # Release-version metadata (release-version.txt) is generated as part
    # of the build, as in the legacy build flow.
    tag_release
    docker build --pull \
        --file deploy/images/django.Dockerfile \
        --build-arg RUN_SCRIPT=./deploy/docker/prod.sh \
        --tag "${CATALOG_IMAGE}" \
        .
    docker image inspect "${CATALOG_IMAGE}" >/dev/null \
        || die "build did not produce the requested image ${CATALOG_IMAGE}"
    echo "Built ${CATALOG_IMAGE} (release version $(cat release-version.txt))"
}

push_image() {
    validate_image_ref "${CATALOG_IMAGE:-}"
    docker push "${CATALOG_IMAGE}"
}

tag_release() {
    git describe --tags --always > release-version.txt
}

case "${1:-}" in
    build) build_image ;;
    push) push_image ;;
    tag) tag_release ;;
    preflight) preflight ;;
    deploy) deploy_release "${2:?environment required (staging or prod)}" ;;
    rollback) rollback ;;
    status) status ;;
    stop) stop_stack ;;
    start) start_stack ;;
    backup) backup_database ;;
    restore) restore_database ;;
    es8-rebuild) es8_rebuild ;;
    es8-validate) es8_validate ;;
    es8-cutover) es8_cutover "${2:?environment required (staging or prod)}" ;;
    schema-migrate) schema_migrate "${2:?environment required (staging or prod)}" ;;
    dev-compose) dev_compose ;;
    existing-compose) existing_compose ;;
    logs) logs_stack ;;
    *) die "usage: $0 <build|push|tag|preflight|deploy|schema-migrate|rollback|status|stop|start|backup|restore|es8-rebuild|es8-validate|es8-cutover>" ;;
esac
