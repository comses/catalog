#!/usr/bin/env bash

# Local entry points for the Docker CI checks and publish-once release contract.
set -o errexit
set -o nounset
set -o pipefail

inspect_image() {
    local image="$1"
    local revision citation_revision
    revision="$(git rev-parse HEAD)"
    citation_revision="$(git rev-parse HEAD:citation)"
    test "$(docker image inspect "${image}" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "${revision}"
    test "$(docker image inspect "${image}" --format '{{index .Config.Labels "org.comses.catalog.citation-revision"}}')" = "${citation_revision}"
}

validate_scripts() {
    local script
    local -a scripts=(
        scripts/ci.sh
        scripts/compose.sh
        scripts/deploy.sh
        scripts/dev-restore.sh
        scripts/checkout-citation.sh
        deploy/docker/prod.sh
        deploy/docker/scheduler.sh
        deploy/cron/daily_catalog_tasks
        deploy/cron/monthly_catalog_tasks
        deploy/cron/backup_database
    )
    for script in "${scripts[@]}"; do
        bash -n "${script}"
    done
    shellcheck "${scripts[@]}"
    python3 -m py_compile scripts/catalogctl/*.py scripts/release_manifest.py scripts/tests/*.py
    make deploy-controller-test
}

validate_compose() {
    CATALOG_BUNDLE_REVISION="$(git rev-parse HEAD)"
    export CATALOG_BUNDLE_REVISION
    export CATALOG_CONFIG_DIR="${PWD}/deploy/conf"
    export CATALOG_SHARED_DIR=/srv/apps/comses-catalog/docker/deploy/shared
    export CATALOG_BACKUP_DIR=/srv/backups/comses_model_catalog
    export CATALOG_BUNDLE_DIR="${PWD}"
    export CATALOG_HTTP_BIND=127.0.0.1:80
    local environment domain rendered
    for environment in staging prod; do
        domain=catalog.comses.net
        if [[ "${environment}" == staging ]]; then
            domain=staging-catalog.comses.net
        fi
        rendered="${temporary}/${environment}.yml"
        CATALOG_ENV="${environment}" CATALOG_DOMAIN="${domain}" \
            bash scripts/compose.sh "${environment}" "${rendered}"
        docker compose -f "${rendered}" config --quiet
        grep -Fq "catalog.settings.${environment}" "${rendered}"
    done
}

publish_image() {
    local revision image_name package_path owner scope tags published digest image_digest
    revision="$(git rev-parse HEAD)"
    image_name="${CATALOG_IMAGE%:*}"
    package_path="${image_name#ghcr.io/}"
    owner="${package_path%%/*}"
    if [ "$(gh api "users/${owner}" --jq .type)" = Organization ]; then
        scope="orgs/${owner}"
    else
        scope="users/${owner}"
    fi
    # A commit's image is published once; GHCR answers a missing package with 403, the API with 404.
    if tags="$(gh api --paginate "${scope}/packages/container/${image_name##*/}/versions" \
            --jq '.[].metadata.container.tags[]' 2>"${temporary}/packages.err")"; then
        published="$(grep -Fxc "sha-${revision}" <<<"${tags}" || true)"
    elif grep -q 'HTTP 404' "${temporary}/packages.err"; then
        published=0
    else
        cat "${temporary}/packages.err" >&2
        exit 1
    fi
    if [ "${published}" -gt 0 ]; then
        echo "sha-${revision} is already published; reusing its digest"
        docker pull "${CATALOG_IMAGE}"
        digest="$(docker image inspect "${CATALOG_IMAGE}" --format '{{range .RepoDigests}}{{println .}}{{end}}' \
            | sed -n "s|^${image_name}@||p" | head -n 1)"
    else
        make image-push | tee "${temporary}/image-push.log"
        digest="$(sed -n 's/.*digest: \(sha256:[0-9a-f]\{64\}\).*/\1/p' "${temporary}/image-push.log" | tail -n 1)"
    fi
    test -n "${digest}"
    image_digest="${image_name}@${digest}"
    docker pull "${image_digest}"
    inspect_image "${image_digest}"
    python3 scripts/release_manifest.py write --image "${image_digest}" --output release-manifest.json
}

temporary="$(mktemp -d)"
trap 'rm -rf "${temporary}"' EXIT

case "${1:-}" in
    check) validate_scripts ;;
    compose-check) validate_compose ;;
    image-check)
        docker run --rm "${CATALOG_IMAGE}" gunicorn --version
        inspect_image "${CATALOG_IMAGE}"
        ;;
    publish) publish_image ;;
    *) echo "usage: $0 <check|compose-check|image-check|publish>" >&2; exit 1 ;;
esac
