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
# runs against, and a rollback restores the recorded release. If a deploy
# omits CATALOG_IMAGE/CATALOG_ES_HOST, they default to the last recorded
# release (deploy/state/release.env): this is how a validated staging
# release is promoted to prod with a plain `make deploy ENV=prod`.
#
# The selected release is recorded in non-secret state under deploy/state
# (git-ignored, created on first use):
#   deploy/state/docker-compose.yml  rendered Compose file of the release
#   deploy/state/release.env         current + previous release
#                                    (env, image, ES host, timestamp)
#   deploy/state/deploy-history.log  append-only, timestamped rollouts
#
# deploy/rollback is a rolling `docker compose up -d`: changed containers
# are recreated (django with the new image); everything else - and every
# named volume - is left untouched. No down, no teardown, no volume
# deletion anywhere in the deploy path. See docs/deployment-runbook.md.

set -o errexit
set -o nounset
set -o pipefail

project_name=catalog
state_dir=deploy/state
compose_file="${state_dir}/docker-compose.yml"
release_state_file="${state_dir}/release.env"
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
# paths (./deploy/..., ./docker/shared/...) from the repository root -
# the CWD these scripts assume - not from the directory that holds the
# rendered file (deploy/state/).
compose() {
    docker compose --project-directory . -p "${project_name}" -f "${compose_file}" "$@"
}

require_compose_file() {
    [[ -s "${compose_file}" ]] \
        || die "no rendered compose file at ${compose_file}; run a deploy (make deploy ENV=staging|prod) first"
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

deploy_release() {
    local environment="$1"
    validate_environment "${environment}"

    # The currently recorded release becomes the rollback unit for this
    # rollout. Load it before validating requested values so a deploy
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

    # Passed through for the YAML lane's release labels; harmless once the
    # labels are gone.
    export CATALOG_PREVIOUS_IMAGE="${release_image}"
    export CATALOG_PREVIOUS_ES_HOST="${release_es_host}"

    # Bake CATALOG_IMAGE and CATALOG_ES_HOST into the rendered Compose file.
    bash scripts/compose.sh "${environment}" "${compose_file}"

    mkdir -p docker/shared/catalog/logs docker/shared/nginx/logs

    # solr is the only service still defined with a `build:` section
    # (comses/catalog/solr:6.6 is not published to any registry); build it
    # locally if it's missing or stale so `up --no-build` below never tries
    # to pull it. This never touches the django image, which is pinned via
    # `image: ${CATALOG_IMAGE}` with no build section.
    compose build solr

    # Rolling update of the single-host stack: recreate only what changed
    # (django with the new image); platform services and all named volumes
    # stay untouched.
    compose up -d --no-build --wait

    write_release_state "${environment}" "${CATALOG_IMAGE}" "${CATALOG_ES_HOST}" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "${release_env}" "${release_image}" "${release_es_host}"
    append_history "${environment}"

    echo "Deployed ${CATALOG_IMAGE} to ${environment} with ${CATALOG_ES_HOST}"
    echo "Previous release (rollback unit): env=${release_env} image=${release_image} es_host=${release_es_host} (${release_state_file})"
    echo "Rollback = make rollback (redeploys that recorded release)"
}

rollback() {
    # Redeploy the recorded previous release as-is (its own environment,
    # immutable image, and ES host). It is NOT an endpoint-only change.
    require_docker
    load_release_state
    [[ "${release_image}" != "none" ]] \
        || die "no release state in ${release_state_file}; nothing to roll back"
    [[ "${previous_image}" != "none" ]] \
        || die "no previous release is recorded in ${release_state_file}"
    [[ "${previous_es_host}" != "none" ]] \
        || die "no previous ES host is recorded in ${release_state_file}"
    echo "Rolling back to env=${previous_env} image=${previous_image} es_host=${previous_es_host}"
    CATALOG_IMAGE="${previous_image}" CATALOG_ES_HOST="${previous_es_host}" \
        deploy_release "${previous_env}"
}

status() {
    require_docker
    load_release_state
    if [[ "${release_image}" == "none" ]]; then
        echo "No release state recorded (${release_state_file})"
    else
        echo "Current release:  env=${release_env} image=${release_image} es_host=${release_es_host}"
        echo "Previous release: env=${previous_env} image=${previous_image} es_host=${previous_es_host} (rollback unit)"
    fi
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
    echo "Restoring database and reindexing"
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
    es8_rebuild
    es8_validate
    CATALOG_ES_HOST=elasticsearch8 deploy_release "${environment}"
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
    *) die "usage: $0 <build|push|tag|preflight|deploy|rollback|status|stop|start|backup|restore|es8-rebuild|es8-validate|es8-cutover>" ;;
esac
