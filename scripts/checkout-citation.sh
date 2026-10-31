#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

owner="${1:?usage: $0 <preferred-github-owner>}"
revision="$(git rev-parse HEAD:citation)"

if [[ -e citation/.git ]] \
    && [[ "$(git -C citation rev-parse HEAD 2>/dev/null || true)" == "${revision}" ]]; then
    exit 0
fi

git submodule init
for repository in "${owner}/citation" comses/citation; do
    url="https://github.com/${repository}.git"
    git config submodule.citation.url "${url}"
    if git submodule update --init --depth 1 citation; then
        [[ "$(git -C citation rev-parse HEAD)" == "${revision}" ]] \
            || { echo "ERROR: Citation checkout has the wrong revision" >&2; exit 1; }
        exit 0
    fi
    if [[ -e citation/.git ]]; then
        git -C citation remote set-url origin "${url}"
        if git -C citation fetch --depth 1 origin "${revision}" \
            && git -C citation checkout --detach "${revision}"; then
            exit 0
        fi
    fi
done

echo "ERROR: Citation revision ${revision} is unavailable from ${owner}/citation and comses/citation" >&2
exit 1
