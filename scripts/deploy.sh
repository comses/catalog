#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

die() {
    echo "ERROR: $*" >&2
    exit 1
}

require_docker() {
    docker info >/dev/null 2>&1 || die "docker daemon is not reachable"
}

require_clean_build_context() {
    if [[ "${ALLOW_DIRTY_BUILD:-0}" == 1 ]]; then
        echo "WARNING: building from a dirty worktree for local rehearsal only" >&2
        return
    fi
    [[ -z "$(git status --porcelain --untracked-files=normal)" ]] \
        || die "worktree is dirty; commit first or set ALLOW_DIRTY_BUILD=1 for a local rehearsal"
    [[ -z "$(git -C citation status --porcelain --untracked-files=normal)" ]] \
        || die "citation submodule is dirty"
}

validate_build_ref() {
    local ref="$1"
    local final_component="${ref##*/}"
    [[ -n "${ref}" ]] || die "CATALOG_IMAGE is required"
    [[ "${ref}" != *@* ]] || die "build and push require a tag, not a digest"
    [[ "${final_component}" == *:* && -n "${final_component##*:}" ]] \
        || die "CATALOG_IMAGE needs an explicit tag"
    [[ "${ref}" != *:latest ]] || die "CATALOG_IMAGE must not use :latest"
}

release_metadata() {
    catalog_revision="$(git rev-parse HEAD)"
    citation_revision="$(git rev-parse HEAD:citation)"
    local citation_checkout
    citation_checkout="$(git -C citation rev-parse HEAD)"
    [[ "${citation_revision}" == "${citation_checkout}" ]] \
        || die "citation checkout does not match the Catalog gitlink"
    release_version="$(git describe --tags --always --dirty)"
}

tag_release() {
    release_metadata
    printf '%s\n' "${release_version}" > release-version.txt
}

dev_compose() {
    # Development targets must never run on a provisioned host.
    local host_env="${CATALOG_HOST_DIR:-/srv/apps/comses-catalog/docker}/deploy/host.env"
    if [[ -e "${host_env}" && "${DEV_OVERRIDE:-0}" != 1 ]]; then
        die "host identity exists at ${host_env}; refusing a development Compose render"
    fi
    bash scripts/compose.sh dev docker-compose.yml
}

build_image() {
    require_docker
    validate_build_ref "${CATALOG_IMAGE:-}"
    require_clean_build_context
    tag_release
    docker build --pull \
        --file deploy/images/django.Dockerfile \
        --build-arg RUN_SCRIPT=./deploy/docker/prod.sh \
        --build-arg CATALOG_REVISION="${catalog_revision}" \
        --build-arg CITATION_REVISION="${citation_revision}" \
        --build-arg CATALOG_SOURCE="${CATALOG_SOURCE:-https://github.com/comses/catalog}" \
        --build-arg CATALOG_VERSION="${release_version}" \
        --build-arg CATALOG_BUILD_RUN="${CATALOG_BUILD_RUN:-unknown}" \
        --tag "${CATALOG_IMAGE}" \
        .
    docker image inspect "${CATALOG_IMAGE}" >/dev/null
    echo "Built ${CATALOG_IMAGE} (release version ${release_version})"
}

push_image() {
    require_docker
    validate_build_ref "${CATALOG_IMAGE:-}"
    docker image inspect "${CATALOG_IMAGE}" >/dev/null \
        || die "image is not present locally: ${CATALOG_IMAGE}"
    docker push "${CATALOG_IMAGE}"
}

case "${1:-}" in
    build) build_image ;;
    push) push_image ;;
    tag) tag_release ;;
    dev-compose) dev_compose ;;
    *) die "usage: $0 <build|push|tag|dev-compose>" ;;
esac
