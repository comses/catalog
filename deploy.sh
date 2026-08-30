#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

# Deployment and rollback unit: an immutable image reference (explicit tag
# or digest) TOGETHER WITH an explicit ES endpoint (CATALOG_ES_HOST).
# Mutable image references (:latest, or a bare reference whose implicit tag
# is :latest) are rejected so a rollback can never drift to a different
# image than the one that was recorded before the rollout. There is NO ES
# endpoint default: every release declares the endpoint it runs against,
# and the rollback restores the recorded {image, ES host} pair. See
# docs/deployment-runbook.md.
STACK_NAME=catalog
DJANGO_SERVICE=catalog_django
DEPLOY_HISTORY_FILE="${DEPLOY_HISTORY_FILE:-docker/deploy-history.log}"
# Valid per-release ES endpoints (swarm service names from base.yml).
# Every release must pick one explicitly; there is no default:
#   elasticsearch  = Elasticsearch 6.6.2
#   elasticsearch8 = Elasticsearch 8.15.5 (gated cutover, see runbook)
ES_HOSTS=(elasticsearch elasticsearch8)

die() {
    echo "ERROR: $*" >&2
    exit 1
}

validate_image_ref() {
    local ref="$1"
    [[ -n "${ref}" ]] || die "an immutable image reference is required (explicit tag or digest, e.g. comses/catalog/prod:v2026.08.27 or comses/catalog/prod@sha256:<64 hex chars>); pass it as an argument or via CATALOG_IMAGE"
    [[ "${ref}" != *":latest" ]] || die ":latest is a mutable tag and cannot be a deployment/rollback unit"
    if [[ "${ref}" == *@* ]]; then
        [[ "${ref}" =~ @sha256:[0-9a-fA-F]{64}$ ]] || die "malformed image digest (expected name@sha256:<64 hex chars>): ${ref}"
    else
        [[ "${ref}" == *":"* ]] || die "image reference has no explicit tag; a bare reference means :latest, which is not allowed: ${ref}"
    fi
}

validate_es_host() {
    local host="$1" known
    for known in "${ES_HOSTS[@]}"; do
        if [[ "${host}" == "${known}" ]]; then
            return 0
        fi
    done
    die "unknown ELASTICSEARCH host '${host}'; expected one of: ${ES_HOSTS[*]}"
}

record_previous_release() {
    # Capture the {image, ES host} of the release currently running on the
    # swarm before anything is rolled over. This recorded PAIR is the
    # rollback unit: a rollback redeploys the same image with the same ES
    # host. The pair is baked into the next release as service labels
    # (comses.catalog.previous-image / comses.catalog.previous-es-host) and
    # appended to the deploy history log.
    # The prior ES host comes from the deployed service's
    # comses.catalog.es-host label; releases deployed before that label
    # existed record "none" and the operator must supply the host.
    local environment="$1" spec="" previous_image="none" previous_es_host="none"
    if docker service inspect "${DJANGO_SERVICE}" >/dev/null 2>&1; then
        spec=$(docker service inspect "${DJANGO_SERVICE}" \
            --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}|{{index .Spec.Labels "comses.catalog.es-host"}}') || spec=""
    fi
    previous_image="${spec%%|*}"
    previous_es_host="${spec#*|}"
    [[ -n "${previous_image}" ]] || previous_image="none"
    [[ -n "${previous_es_host}" ]] || previous_es_host="none"
    export CATALOG_PREVIOUS_IMAGE="${previous_image}"
    export CATALOG_PREVIOUS_ES_HOST="${previous_es_host}"
    mkdir -p "$(dirname "${DEPLOY_HISTORY_FILE}")"
    printf '%s env=%s previous_image=%s previous_es_host=%s next_image=%s next_es_host=%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "${environment}" "${previous_image}" "${previous_es_host}" "${CATALOG_IMAGE}" "${CATALOG_ES_HOST}" \
        >> "${DEPLOY_HISTORY_FILE}"
    echo "Previous release recorded: image=${previous_image} es_host=${previous_es_host} (labels comses.catalog.previous-image/-es-host, ${DEPLOY_HISTORY_FILE})"
}

restore_db() {
echo "Restore from catalog.sql (y/N)"
read restore_confirm

if [[ "$restore_confirm" == [yY] || "$restore_confirm" == [yY][eE][sS] ]]; then
django_service_id=$(docker service ps catalog_django -q)
django_container_id=$(docker ps --filter label=com.docker.swarm.service.name=catalog_django -q)
echo "Copying catalog.sql to container"
docker cp catalog.sql ${django_container_id}:/code

echo "Restoring database and reindexing"
docker exec -i ${django_container_id} bash <<-EOF
inv restore-from-dump
EOF
fi
}

tag_app() {
git describe --tags --always >| release-version.txt
}

down_app() {
# Ensure catalog stack is down before deploying again
if [[ $(docker service ls -q --filter label="com.docker.stack.namespace=${STACK_NAME}" | wc -l) == 0 ]]; then
echo "Catalog already torn down"
else
echo "Catalog is being torn down"
docker stack rm "${STACK_NAME}"
sleep 12
echo "Catalog successfully torn down"
fi
}

build_app() {
    # Build the application image locally under the requested immutable
    # reference. The deploy host must be able to resolve that exact
    # reference at deploy time (local build, registry pull, or load).
    local image_ref="${1:-${CATALOG_IMAGE:-}}"
    validate_image_ref "${image_ref}"
    export CATALOG_IMAGE="${image_ref}"

    tag_app

    # Setup shared folders
    mkdir -p docker/shared/catalog/logs
    mkdir -p docker/shared/nginx/logs

    ./compose staging
    docker compose build --pull django
    echo "Built ${CATALOG_IMAGE}"
    echo "If the swarm manager cannot see this local build, push it first: docker push ${CATALOG_IMAGE}"
}

ensure_image_resolvable() {
    # Pre-flight check, run BEFORE the running release is torn down: the
    # exact requested reference must resolve on this host. Swarm nodes
    # pull the image themselves at task scheduling; a pull failure here
    # means the reference does not exist in a reachable registry, so the
    # deploy is refused instead of substituting a different image.
    if docker image inspect "${CATALOG_IMAGE}" >/dev/null 2>&1; then
        echo "Image ${CATALOG_IMAGE} present on this host"
        return 0
    fi
    echo "Image ${CATALOG_IMAGE} not present locally; attempting docker pull"
    docker pull "${CATALOG_IMAGE}" || die "cannot resolve ${CATALOG_IMAGE} on this host; build/push or load the exact image first (refusing to deploy a different image than requested)"
}

deploy_app() {
    local environment="${1}"
    local image_ref="${2:-${CATALOG_IMAGE:-}}"
    local es_host="${CATALOG_ES_HOST:-}"
    [[ -n "${image_ref}" ]] || die "usage: CATALOG_ES_HOST=elasticsearch|elasticsearch8 ./deploy.sh deploy <staging|prod> <image-ref>  (image also via CATALOG_IMAGE; both the immutable image and the ES host are required)"
    validate_image_ref "${image_ref}"
    export CATALOG_IMAGE="${image_ref}"

    # Explicit per-release ES endpoint: there is NO default. The
    # application must never silently run against an endpoint the release
    # was not declared (and validated) for. Switching a release to ES8
    # (CATALOG_ES_HOST=elasticsearch8) is gated: rebuild_es_index against
    # ES8 + validation BEFORE deploying with the ES8 endpoint (runbook).
    # Rollback restores the recorded {image, ES host} pair.
    [[ -n "${es_host}" ]] || die "CATALOG_ES_HOST must be set explicitly for every release (elasticsearch = ES6, elasticsearch8 = ES8); there is no default"
    validate_es_host "${es_host}"
    export CATALOG_ES_HOST="${es_host}"

    record_previous_release "${environment}"

    # Setup shared folders
    mkdir -p docker/shared/catalog/logs
    mkdir -p docker/shared/nginx/logs

    # Fail fast while the old release is still up.
    ensure_image_resolvable

    # Bakes CATALOG_IMAGE, CATALOG_PREVIOUS_IMAGE, CATALOG_PREVIOUS_ES_HOST
    # and CATALOG_ES_HOST into the generated docker-compose.yml
    # (image + service labels + env).
    ./compose "${environment}"
    docker compose pull db nginx redis
    down_app

    echo "Deploying catalog ${CATALOG_IMAGE} (env=${environment}, es_host=${CATALOG_ES_HOST}, previous image=${CATALOG_PREVIOUS_IMAGE} es_host=${CATALOG_PREVIOUS_ES_HOST})"
    docker stack deploy -c docker-compose.yml "${STACK_NAME}"

    local rollback_example
    if [[ "${CATALOG_PREVIOUS_ES_HOST}" != "none" ]]; then
        rollback_example="CATALOG_IMAGE=${CATALOG_PREVIOUS_IMAGE} CATALOG_ES_HOST=${CATALOG_PREVIOUS_ES_HOST} ./deploy.sh deploy ${environment}"
    else
        rollback_example="CATALOG_IMAGE=${CATALOG_PREVIOUS_IMAGE} CATALOG_ES_HOST=<ES host the previous release used> ./deploy.sh deploy ${environment}"
    fi

    cat <<EOF

Deployed ${CATALOG_IMAGE} on ${environment} with ELASTICSEARCH_HOST=${CATALOG_ES_HOST}.
Previous release (rollback unit): image=${CATALOG_PREVIOUS_IMAGE} es_host=${CATALOG_PREVIOUS_ES_HOST}
Rollback = redeploy that recorded {image, ES host} pair, e.g.:
    ${rollback_example}
Full procedure (ES8 cutover, validation, rollback): docs/deployment-runbook.md
EOF
}

case "${1:-deploy}" in
    'deploy') deploy_app "${2:-prod}" "${3:-}";;
    'build') build_app "${2:-}";;
    'down') down_app;;
    'restore') restore_db;;
    'tag') tag_app;;
    *) echo "Invalid option choose on of deploy, build, down, restore, tag" 1>&2; exit 1;;
esac
