#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

die() {
    echo "ERROR: $*" >&2
    exit 1
}

dump="$(realpath "${DUMP:?set DUMP to a .dump, .sql, or .sql.xz file}")"
[[ -s "${dump}" ]] || die "dump is missing or empty: ${dump}"
[[ "${CONFIRM:-}" == comses_catalog ]] \
    || die "set CONFIRM=comses_catalog to replace the local development database"

case "${dump}" in
    *.dump) format=custom ;;
    *.sql) format=sql ;;
    *.sql.xz)
        format=sql-xz
        xz --test "${dump}"
        ;;
    *) die "DUMP must end in .dump, .sql, or .sql.xz" ;;
esac

python3 - "${dump}" "${format}" <<'PY'
import lzma
import re
import sys

path, kind = sys.argv[1:]
if kind == "custom":
    raise SystemExit(0)
opener = lzma.open if kind == "sql-xz" else open
pattern = re.compile(r"^(?:CREATE|DROP|ALTER)\s+DATABASE\b|^\\connect\b", re.I)
with opener(path, "rt", encoding="utf-8", errors="replace") as source:
    for line in source:
        if pattern.search(line.strip()):
            raise SystemExit("ERROR: plain SQL dump contains database-level commands")
PY

bash scripts/deploy.sh dev-compose
bash scripts/config.sh validate
compose=(docker compose --project-directory . -p catalog -f docker-compose.yml)
"${compose[@]}" up -d --wait db redis elasticsearch
"${compose[@]}" stop django >/dev/null 2>&1 || true
"${compose[@]}" exec -T db dropdb --force --if-exists --username catalog comses_catalog
"${compose[@]}" exec -T db createdb --username catalog --owner catalog comses_catalog

if [[ "${format}" == custom ]]; then
    "${compose[@]}" exec -T db pg_restore --list < "${dump}" >/dev/null
    "${compose[@]}" exec -T db pg_restore --username catalog --dbname comses_catalog \
        --exit-on-error --no-owner --no-privileges < "${dump}"
elif [[ "${format}" == sql-xz ]]; then
    xz --decompress --stdout "${dump}" \
        | "${compose[@]}" exec -T db psql --username catalog --dbname comses_catalog \
            --set ON_ERROR_STOP=1 --quiet
else
    "${compose[@]}" exec -T db psql --username catalog --dbname comses_catalog \
        --set ON_ERROR_STOP=1 --quiet < "${dump}"
fi

"${compose[@]}" run --rm --no-deps django python3 manage.py migrate --noinput
"${compose[@]}" run --rm --no-deps django python3 manage.py check
"${compose[@]}" run --rm --no-deps django python3 manage.py rebuild_es_index
"${compose[@]}" run --rm --no-deps django python3 manage.py validate_search_indexes
"${compose[@]}" run --rm --no-deps django python3 manage.py populate_visualization_cache --clear
"${compose[@]}" up -d --wait django
echo "Local development database restored from ${dump}"
