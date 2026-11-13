#!/usr/bin/env bash

# Promote a validated CI manifest; never replace an existing release identity.
set -o errexit
set -o nounset
set -o pipefail

die() {
    echo "ERROR: $*" >&2
    exit 1
}

temporary="$(mktemp -d)"
trap 'rm -rf "${temporary}"' EXIT

image_name="ghcr.io/${GITHUB_REPOSITORY,,}"
source_image="$(python3 -c 'import json; print(json.load(open("release-manifest.json"))["image"])')"
[[ "${source_image%@*}" == "${image_name}" ]] || die "manifest image belongs to a different repository"
source_digest="${source_image##*@}"
release_image="${image_name}:${TAG}"

# Inspect the release once, before changing either GitHub or GHCR. Only a 404
# means it is absent; authentication and service errors must stop publication.
release_exists=false
release_draft=false
asset_count=0
if metadata="$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/${TAG}" \
        --jq '[
            .draft,
            .prerelease,
            ([.assets[] | select(.name == "release-manifest.json")] | length),
            (.immutable // false)
        ] | @tsv' \
        2>"${temporary}/release.err")"; then
    release_exists=true
    read -r release_draft prerelease asset_count release_immutable <<<"${metadata}"
    [[ "${prerelease}" == false ]] || die "release ${TAG} is a prerelease"
    case "${asset_count}" in
        0)
            [[ "${release_immutable}" == false ]] \
                || die "immutable release ${TAG} is missing its manifest"
            ;;
        1)
            gh release download "${TAG}" --repo "${GITHUB_REPOSITORY}" \
                --pattern release-manifest.json --dir "${temporary}"
            cmp release-manifest.json "${temporary}/release-manifest.json" \
                || die "release ${TAG} has a different manifest"
            ;;
        *) die "release ${TAG} has duplicate release-manifest.json assets" ;;
    esac
elif ! grep -q 'HTTP 404' "${temporary}/release.err"; then
    cat "${temporary}/release.err" >&2
    exit 1
fi

# Registry errors other than a missing manifest are fatal. A retry may reuse
# the same alias, but must never overwrite an alias pointing at another digest.
if release_digest="$(docker buildx imagetools inspect "${release_image}" \
        --format '{{.Manifest.Digest}}' 2>"${temporary}/image.err")"; then
    [[ "${release_digest}" == "${source_digest}" ]] \
        || die "image ${release_image} already points at a different digest"
else
    if ! grep -Fq "${release_image}: not found" "${temporary}/image.err"; then
        cat "${temporary}/image.err" >&2
        exit 1
    fi
    # Copy the registry manifest directly, preserving single-platform images
    # and image indexes without downloading layers or parsing push logs.
    docker buildx imagetools create --prefer-index=false --tag "${release_image}" "${source_image}"
    release_digest="$(docker buildx imagetools inspect "${release_image}" --format '{{.Manifest.Digest}}')"
    [[ "${release_digest}" == "${source_digest}" ]] || die "published image digest differs from the tested image"
fi

if [[ "${release_exists}" == false ]]; then
    gh release create "${TAG}" 'release-manifest.json#Release manifest' \
        --repo "${GITHUB_REPOSITORY}" --verify-tag \
        --title "Catalog ${TAG#v}" --generate-notes
else
    if [[ "${asset_count}" == 0 ]]; then
        gh release upload "${TAG}" 'release-manifest.json#Release manifest' --repo "${GITHUB_REPOSITORY}"
    fi
    if [[ "${release_draft}" == true ]]; then
        gh release edit "${TAG}" --repo "${GITHUB_REPOSITORY}" --draft=false
    fi
fi
