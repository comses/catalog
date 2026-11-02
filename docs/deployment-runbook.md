# Release and deployment runbook

This is the canonical operator guide for preparing and deploying Catalog releases.
It assumes the maintainer works directly in `comses/catalog` and `comses/citation` through topic branches and pull requests.
Use [deployment-acceptance-testing.md](deployment-acceptance-testing.md) only when validating the release machinery on personal forks and disposable hosts.

Staging and production are independent installations.
Each has its own database, credentials, backups, and release state, and each runs its own migrations.
They never share databases, volumes, Compose files, or release state.
Both deploy the same release manifest, so they run the same image digests.

The host interface is a set of explicit phases.
Each phase prints exactly one JSON result on stdout, writes progress to stderr, exits non-zero when a check fails, and can be repeated safely.
Operators run the commands below directly, including release selection, staging approval and recovery after a failed or interrupted phase.
The infrastructure deployment adapter is deferred pending agreement with the infrastructure maintainer and is not part of this delivery.
This runbook does not require `make catalog-deploy`.
The JSON phase interface remains available for future automation.
An orchestration caller can hold `.backup.lock` across consecutive phases and pass its open descriptor through `CATALOG_LOCK_FD`.
The controller verifies that the descriptor names the host's backup lock and leaves its ownership with the caller; `status` advertises `lock_protocol=inherited-fd-v1`.
Run `backup` before taking that outer lock, because backup capture takes the same lock inside its application container.
An interrupted SSH client does not prove that the remote deployment stopped; reconnect, check for a running controller and inspect `make status` before recovery, following [Failures and recovery](#failures-and-recovery).
Maintenance mode is not part of this first version, so the site is unavailable between `drain` and `activate`.

Use `make help` as the command index.
Stop at the first unexplained failure.

## Release lifecycle

1. Merge to `main`; CI tests the checkout in the development image, builds the production image, checks that its gunicorn runs and that its labels name the commits, publishes it once as `ghcr.io/comses/catalog:sha-<commit>`, and uploads its release manifest.
2. Deploy that manifest to staging and complete QA.
3. Push an annotated `vYYYY.MM` or `vYYYY.MM.N` tag; CI aliases the same digest and attaches the same manifest to a GitHub Release.
4. Deploy the staging-approved manifest to production.

A release is identified by its manifest's SHA-256 and image digest.
A rebuilt or republished image is a new release and needs its own QA.

## Choose the procedure

| Situation | Procedure |
| --- | --- |
| Host has an active release | [Release on an existing host](#4-release-on-an-existing-host) |
| New or replacement host with no active release | [First deployment from a dump](#7-first-deployment-from-a-dump) |
| Host still runs the single-host stack (Compose project `catalog`) | [Cut production over from the single-host stack](#8-cut-production-over-from-the-single-host-stack) |
| A phase failed or was interrupted | [Failures and recovery](#failures-and-recovery) |

`make status` shows the active release, the rollback release, the candidate's stages, and any open journal.
`make restore` is refused once a host has an active release.

## Release manifest

CI writes `release-manifest.json` (schema 2) for every published `main` build:

| Field | Meaning |
| --- | --- |
| `catalog_revision` | Catalog commit; also the configuration revision of the Compose and nginx files |
| `citation_revision` | Citation commit pinned by the Catalog gitlink |
| `image` | application image as `name@sha256:<digest>` |
| `support_images` | digest-pinned PostgreSQL, Redis, Elasticsearch, and nginx images |
| `search_backend` | the Elasticsearch image in use |
| `base_image` | Python base image of the application image |
| `dependencies` | Python and key package versions read from the image, plus the `uv.lock` hash |
| `build` | the CI run that built the image and the image's creation time, read from the image itself |

`make prepare` refuses a manifest whose commit is not the checkout's `HEAD`, whose image labels name other commits, or whose support images differ from what the commit renders.

## 1. Verify the changes locally

Run these commands from the Catalog topic branch on the workstation:

```sh
make bootstrap
make cite-config
docker compose build --pull django
make up
make check
make migrations-check
make cite-check
make cite-migrations-check
make test-all
make deploy-controller-test
```

When the release changes migrations, database access, search, exports, or visualization data, restore a representative dump and record a baseline:

```sh
make dev-restore DUMP=/absolute/path/catalog.sql.xz CONFIRM=comses_catalog
docker compose exec -T django python3 manage.py shell -c \
"from citation.models import Publication; print('all=', Publication.objects.count()); print('primary=', Publication.api.primary().count()); print('public=', Publication.api.primary().reviewed().count())" </dev/null
```

Create or update the local-only curator account, then sign in at <http://localhost:8000/accounts/login/>:

```sh
docker compose exec -T django python3 manage.py shell -c \
"from django.contrib.auth import get_user_model; User = get_user_model(); user, _ = User.objects.get_or_create(username='local-curator', defaults={'email': 'local-curator@example.invalid'}); user.is_active = True; user.is_staff = True; user.is_superuser = True; user.save(); print('local-curator is ready')" </dev/null
docker compose exec django python3 manage.py changepassword local-curator
```

Verify in the browser:

1. The home page, one publication page, `/publications/?search=CORMAS`, a zero-result search, and `/visualization/?search=CORMAS` render with the footer.
2. `/curator/export/` has one row per primary publication, keeps multiple authors in one CSV cell, and leaves later columns aligned.
3. `/merges/` and `/merges/create/` load.
4. A reviewed publication changed to `UNREVIEWED` disappears from public search but stays in curator search.
5. Restored to `REVIEWED`, it returns to public search.

## 2. Merge Citation and Catalog

Pull requests build and test but publish nothing.
Never push release work directly to either `main` branch.

When Citation changed, merge its pull request first, then pin the merge commit in Catalog:

```sh
CITATION_UPSTREAM_SHA="$(gh pr view "$CITATION_PR_URL" --repo comses/citation --json mergeCommit --jq .mergeCommit.oid)"
git -C citation fetch origin main
git -C citation checkout "$CITATION_UPSTREAM_SHA"
git add citation
git commit -m 'chore: update Citation revision'
```

When Citation did not change, confirm the pinned commit is on upstream `main`:

```sh
git -C citation fetch origin main
git -C citation merge-base --is-ancestor "$(git rev-parse HEAD:citation)" origin/main
```

Run all gates again, push the Catalog topic branch, open or reuse its pull request, wait for its checks, and merge after review.
Record the merge commit:

```sh
RELEASE_COMMIT="$(gh pr view "$CATALOG_PR_URL" --repo comses/catalog --json mergeCommit --jq .mergeCommit.oid)"
```

## 3. Get the release manifest

Wait for the `CoMSES Docker CI` run of that commit, then download and check its manifest:

```sh
MAIN_RUN_ID="$(gh run list --repo comses/catalog --workflow docker-build.yml --branch main \
  --commit "$RELEASE_COMMIT" --event push --status success --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$MAIN_RUN_ID" --repo comses/catalog --exit-status
mkdir -p "$PWD/private/release-manifests"
MANIFEST_DIR="$(mktemp -d "$PWD/private/release-manifests/${RELEASE_COMMIT}.XXXXXX")"
gh run download "$MAIN_RUN_ID" --repo comses/catalog \
  --name "catalog-release-manifest-${RELEASE_COMMIT}" --dir "$MANIFEST_DIR"
MANIFEST="${MANIFEST_DIR}/release-manifest.json"
python3 scripts/release_manifest.py check "$MANIFEST" --revision "$RELEASE_COMMIT"
sha256sum "$MANIFEST"
```

The workflow keeps the manifest for 90 days; a tagged release keeps it as a GitHub Release asset.
After the first official publication an organization owner makes the `ghcr.io/comses/catalog` package public, so hosts pull without credentials.

## 4. Release on an existing host

From the workstation, copy the manifest and connect:

```sh
scp "$MANIFEST" "${STAGING_SSH}:release-manifest.json"
ssh "$STAGING_SSH"
```

On the host, check out the manifest's commit in the canonical checkout and run the phases in order:

```sh
cd /srv/apps/comses-catalog || exit 1
MANIFEST="$HOME/release-manifest.json"
RELEASE_COMMIT="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["catalog_revision"])' "$MANIFEST")"
git fetch origin main
git checkout --detach "$RELEASE_COMMIT"
make host-check
make prepare MANIFEST="$MANIFEST"
make backup
make drain
CONFIRM_SCHEMA_MIGRATION=1 make migrate
make rebuild
make activate
make validate
make release-report
```

`prepare` checks out the pinned Citation commit, pulls and verifies the image, and renders the candidate while the current release keeps serving.
`backup` takes a fresh dump of the running release and verifies it; `migrate` refuses unless such a backup exists from the last 24 hours, taken before any earlier migration attempt.
`drain` stops the scheduler, then Django, and removes their containers, so a daemon restart or reboot cannot bring them back; the site is unavailable from here until `activate` succeeds.
`migrate` prints and records the migration plan, then applies it explicitly and records whether anything was applied.
`rebuild` builds new search generations, validates their counts, switches all aliases at once, and refreshes the visualization cache.
`activate` switches search to the generation `rebuild` validated, starts the new release, waits for every service's healthcheck, requests a page through nginx, then records it as active and keeps the previous release for rollback.
`validate` confirms that every required service is healthy, that the running containers use the manifest's images and commit, that no migrations are pending, that search validates, and that nginx answers.

Complete staging QA:

1. Compare database and search counts with the previous release report.
2. Repeat the browser checks from Section 1 through `https://staging-catalog.comses.net`.
3. Confirm the release report uses `django.core.mail.backends.filebased.EmailBackend`; mail lands in `/srv/apps/comses-catalog/docker/deploy/shared/mail`.
4. Record the approved manifest SHA-256 from `make status` or the release report.

Staging must never hold working SMTP credentials.
Staging serves a `robots.txt` that disallows all crawlers.

## 5. Publish the final release

After staging approval, tag the approved commit:

```sh
FINAL_TAG="v$(date -u +%Y.%m)"
git fetch origin main
git merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git tag -a "$FINAL_TAG" "$RELEASE_COMMIT" -m "Catalog ${FINAL_TAG#v}"
git push origin "refs/tags/${FINAL_TAG}"
```

Choose an unused `vYYYY.MM` or `vYYYY.MM.N` tag.
The `Publish final release` workflow fetches the tested build's manifest, aliases its digest without rebuilding, and attaches the same `release-manifest.json` to the GitHub Release.
Confirm that the release asset has the SHA-256 approved on staging:

```sh
gh release download "$FINAL_TAG" --repo comses/catalog --pattern release-manifest.json --dir "$MANIFEST_DIR/release"
sha256sum "$MANIFEST_DIR/release/release-manifest.json"
```

## 6. Release to production

While production still runs the single-host stack, cut it over with Section 8 instead; every later release follows this section.
Use the staging-approved manifest and nothing else.
Do not rebuild, download a newer manifest, or transfer staging data.
Copy the manifest to the production host, confirm its SHA-256 equals the approved value, and run the same phases as Section 4.

Production additionally requires complete SMTP settings in `config.ini`.
Confirm that its release report shows the approved manifest, the SMTP email backend, plausible counts, and, as `latest_backup`, the verified backup taken before the drain, then repeat the browser checks through `https://catalog.comses.net`.

## 7. First deployment from a dump

Use this only for a new or replacement host with no active release.
`make prepare` refuses such a host while Docker has any containers or volumes in the `comses-catalog` Compose project.
A host that still runs the single-host stack (Compose project `catalog`) follows Section 8 instead.
A first production deployment requires the final release from Section 5.

The host needs Git, GNU Make, Python 3.12 or newer (3.10.12+ and 3.11.4+ also work), `xz`, Docker Engine, Docker Compose v2 or newer, and an operator in the `docker` group.
The CoMSES infrastructure creates the operator's checkout at `/srv/apps/comses-catalog`, binds the workload's backups root `/srv/backups/comses_model_catalog` onto its `docker/deploy/shared/backups`, and sets `vm.max_map_count`; nothing on the application side needs root.
On any other host, see the acceptance guide for reproducing that layout.

Copy the manifest, the dump, and its checksum from the workstation:

```sh
(cd "$(dirname "$DUMP")" && sha256sum "$(basename "$DUMP")" > "$(basename "$DUMP").sha256")
scp "$MANIFEST" "${TARGET_SSH}:release-manifest.json"
scp "$DUMP" "${DUMP}.sha256" "${TARGET_SSH}:"
```

On the host, check out the commit and provision the fixed identity.
Set `HTTP_BIND` to the address the TLS proxy connects to: behind the CoMSES edge HAProxy that is the VM's private address on port 80, which `getent hosts model-catalog-01.staging.internal` (or `.production.internal`) prints.
Leave it empty only for a TLS proxy on the same host.

```sh
cd /srv/apps/comses-catalog || exit 1
MANIFEST="$HOME/release-manifest.json"
RELEASE_COMMIT="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["catalog_revision"])' "$MANIFEST")"
git fetch origin main
git checkout --detach "$RELEASE_COMMIT"
make storage-prepare
make storage-preflight
make configure HOST_ID=staging HTTP_BIND='<private-address>:80'
"${EDITOR:-vi}" /srv/apps/comses-catalog/docker/secrets/config.ini
make host-check
```

`storage-prepare` creates the owner-only directories under `docker/` as the operator and never touches the backups root.
`storage-preflight` changes nothing: it confirms the `/srv` mount, the canonical checkout, those directories, the infrastructure's backups bind, and the kernel setting, so a host the infrastructure has not converged fails here rather than later.
`configure` runs as the operator, writes the fixed identity, and generates the database and Django secrets once; it is idempotent and refuses to change a host from staging to production or back.
A later run keeps the recorded HTTP bind unless `HTTP_BIND` names a different one.
Leave staging SMTP settings empty; production needs host, port, user, and password.

Restore and activate:

```sh
make prepare MANIFEST="$MANIFEST"
make restore DUMP="$HOME/catalog.sql.xz" CONFIRM=comses_catalog
CONFIRM_SCHEMA_MIGRATION=1 make migrate
make rebuild
make activate
make validate
make backup
make release-report
```

There is nothing to drain or back up before a first deployment.
Restore accepts `.dump`, `.sql`, and `.sql.xz`, verifies an adjacent `<dump>.sha256`, rejects database-level commands in plain SQL, restores into a temporary database, checks its counts and constraints, swaps the database names, and keeps the previous empty database under a timestamped name.
It refuses a database that already contains publications.

Compare total, primary, public, and search counts with the source, then complete the browser, email, scheduler, and backup checks.

## 8. Cut production over from the single-host stack

Production still runs the stack that `main` deployed before this release process: Compose project `catalog`, started from `deploy/state/docker-compose.yml` in the same checkout, with PostgreSQL in the bind mount `docker/pgdata`, Elasticsearch 6 and 8 plus Solr, and nginx publishing port 80.
The cutover moves the host onto this release process once; every later release follows Section 6.
It follows the CoMSES legacy migration runbook (`docs/legacy-arbutus-migration.md` in `comses/infrastructure`): rehearse on staging until the procedure is repeatable, obtain a written go/no-go, freeze writes, take a final verified dump, start the new stack, and keep the old one intact and stopped for the rollback period.
The new stack has its own Compose project, secrets, and volumes, so nothing here modifies the old stack's data.

### Rehearse and approve

1. Run this whole section on staging first, with the manifest intended for production and with staging set up like production: the single-host stack at production's commit, restored from a production dump.
   Exercise the fallback as well.
   A staging failure stops the cutover; fix the procedure and rehearse again.
2. Record the measured downtime, the service owner's written go/no-go, and the window, and announce the downtime.
   The 2026-10-27 staging rehearsal measured 1150 s from the write freeze to a passing `validate` (restore 121 s, migrate 378 s, rebuild 395 s, activate 88 s, validate 83 s); the hosts' volume, not CPU or memory, sets the pace.

### Record the old stack

```sh
cd /srv/apps/comses-catalog || exit 1
printf 'OLD_COMMIT=%s\nOLD_COMPOSE=%s\n' "$(git rev-parse HEAD)" "$PWD/deploy/state/docker-compose.yml" > "$HOME/catalog-cutover.env"
cat deploy/state/release.env
docker ps -a --filter label=com.docker.compose.project=catalog --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
```

Keep this output with the cutover record.

### Prepare while the old site serves

Copy the manifest to the host as in Section 3, then:

```sh
MANIFEST="$HOME/release-manifest.json"
RELEASE_COMMIT="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["catalog_revision"])' "$MANIFEST")"
git fetch origin main
git checkout --detach "$RELEASE_COMMIT"
make storage-prepare
make storage-preflight
make configure HOST_ID=prod HTTP_BIND='<private-address>:80' IMPORT_CONFIG="$PWD/deploy/conf/config.ini"
make host-check
make prepare MANIFEST="$MANIFEST"
```

`storage-preflight` fails until the infrastructure has converged the host with Catalog's backups bind and kernel setting; that convergence belongs before the window.

`IMPORT_CONFIG` copies the old `deploy/conf/config.ini` values for every key of the new template except the database section, so email, Sentry, the audit account, and the Django secret key carry over while the new database gets a new password.
The result lists only the imported key names.
The running old containers keep the files they started with, although the new checkout no longer contains some of them; the fallback checks the old commit out again before restarting them.

### Freeze writes and take the final dump

From here the site is unavailable.
Stop every old service except the database, dump and verify it, then stop it too and keep a reboot from restarting the old stack:

```sh
OLD_DB="$(docker ps -q --filter label=com.docker.compose.project=catalog --filter label=com.docker.compose.service=db)"
docker ps -q --filter label=com.docker.compose.project=catalog | grep -vx "$OLD_DB" | xargs -r docker stop
DUMP="/srv/backups/comses_model_catalog/cutover-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec "$OLD_DB" pg_dump --username catalog --format custom --no-owner --no-privileges comses_catalog > "$DUMP"
docker exec -i "$OLD_DB" pg_restore --list < "$DUMP" > /dev/null
(cd "$(dirname "$DUMP")" && sha256sum "$(basename "$DUMP")" > "$(basename "$DUMP").sha256")
docker exec "$OLD_DB" psql --username catalog --dbname comses_catalog --tuples-only --no-align \
  --command "SELECT count(*), count(*) FILTER (WHERE is_primary) FROM citation_publication;"
docker stop "$OLD_DB"
docker ps -aq --filter label=com.docker.compose.project=catalog | xargs -r docker update --restart=no
printf 'DUMP=%s\n' "$DUMP" >> "$HOME/catalog-cutover.env"
```

### Restore, migrate, rebuild, and switch

Run the long phases in their own session, so a dropped SSH connection cannot interrupt them; after a disconnect, reconnect and follow `$HOME/cutover-<phase>.log` while `pgrep -af 'python3 -m catalogctl'` shows the phase running.

```sh
run_phase() {
  setsid -w nohup make "$@" > "$HOME/cutover-$1.log" 2>&1 < /dev/null
  status=$?
  tail -n 30 "$HOME/cutover-$1.log"
  return "$status"
}
run_phase restore DUMP="$DUMP" CONFIRM=comses_catalog
run_phase migrate CONFIRM_SCHEMA_MIGRATION=1
run_phase rebuild
run_phase activate
make validate
make backup
make release-report
```

`make activate` refuses while a container outside the `comses-catalog` project publishes the HTTP port, and names it.

### Verify and accept

1. The restored counts equal the final dump's, and `make validate` passes.
2. Through `https://catalog.comses.net`, and through the edge HAProxy directly, bypassing Cloudflare: browse, search, visualization, a publication page, login, and the curator export work, and `robots.txt` answers.
3. The release report shows the SMTP email backend, `make backup-status` reports a verified backup, and the scheduler's `/etc/cron.d/catalog-backup` names the nightly backup.
4. The service owner accepts the cutover, or the fallback below runs.

### Fallback

Before acceptance, any failure returns the host to the old stack.
Anything written to the new database after activation is lost, so curators must not work until acceptance.

```sh
cd /srv/apps/comses-catalog || exit 1
. "$HOME/catalog-cutover.env"
docker ps -q --filter label=com.docker.compose.project=comses-catalog | xargs -r docker stop
docker ps -aq --filter label=com.docker.compose.project=comses-catalog | xargs -r docker update --restart=no
git checkout --detach "$OLD_COMMIT"
docker ps -aq --filter label=com.docker.compose.project=catalog | xargs -r docker update --restart=always
docker compose -p catalog -f "$OLD_COMPOSE" start
```

The old Django takes about a minute after `start` before it answers; check the site after that, not immediately.

To try again later, discard the never-accepted new installation and start over at "Prepare while the old site serves", running `make configure` without `IMPORT_CONFIG` because the secrets already exist:

```sh
docker ps -aq --filter label=com.docker.compose.project=comses-catalog | xargs -r docker rm -f
docker volume ls -q --filter label=com.docker.compose.project=comses-catalog | xargs -r docker volume rm
mv docker/deploy/state "docker/deploy/state.failed-$(date -u +%Y%m%dT%H%M%SZ)"
```

### Rollback period and cleanup

Keep the stopped old containers, their images and volumes, `docker/pgdata`, `deploy/state`, the old `deploy/conf` secrets, and the cutover dump for the rollback period agreed with the service owner.
Remove them only afterwards and with the owner's approval; never as part of the cutover.

## Failures and recovery

| Failed phase | State | Next step |
| --- | --- | --- |
| `prepare`, `backup` | nothing changed; the release keeps serving | fix the cause and rerun |
| `restore` | the temporary and retained database names are recorded before anything is created | `candidate-retry`, then rerun `restore`: a populated copy whose swap never started is dropped, a swap that lost its second rename is finished, and a completed swap that was never recorded is recorded |
| `drain` | some writers may be stopped | `make start`, investigate, rerun from `drain` |
| `migrate`, before any change | the result says no change was applied | `make start` restores the previous release; fix, `CONFIRM_CANDIDATE_RETRY=1 make candidate-retry`, rerun from `drain` |
| `migrate`, while applying | the database may be partly migrated; the site stays down | investigate; `candidate-retry`, then rerun `migrate` or `prepare` a fixed release; or recover data as below |
| `rebuild` | previous search aliases restored when Elasticsearch answers | investigate, `candidate-retry` (starts the database, Redis, and Elasticsearch, then restores the aliases), rerun `rebuild`, or `prepare` a fixed release and run `migrate` and `rebuild` for it |
| `activate` | the candidate's logs are kept in `docker/deploy/reports/`; if the release applied migrations, its writers are stopped and the site stays down; otherwise the previous runtime and its search aliases are restored and checked; an interruption after the new runtime was verified leaves a journal that `make recover` finishes | read the error and the kept logs; `make recover` if a journal remains; fix and rerun `activate`, `prepare` a fixed release and run `migrate`, `rebuild`, and `activate` for it, or follow the recovery policy |
| `validate` | the new release is active | investigate; `make rollback` if the schema allows (it rebuilds the previous release's search, about seven minutes) |

Always read `make status` before acting.
After an SSH interruption, check `pgrep -af 'python3 -m catalogctl'` and wait for a running controller instead of starting another phase.
A failed or interrupted restore, migration, or rebuild locks its candidate until `CONFIRM_CANDIDATE_RETRY=1 make candidate-retry` records an explicit retry.
After that retry, `make prepare` may replace the candidate with a fixed release.
The first migration attempt requires a verified backup of the active release no more than 24 hours old.
Before migration starts, the controller retains that backup and records its identity together with the attempt timestamp.
Retries and replacement candidates reverify the retained backup without aging out that selection; backups taken after the attempt began cannot replace it.
Older interrupted candidates without a recorded selection require a verified backup from the 24 hours preceding their original attempt.
If no such backup survives, preserve the installation and follow the recovery policy rather than clearing migration history.

`make status` reports the selection in `candidate.migration_backup`.
Its `directory` identifies `/srv/backups/comses_model_catalog/.migration-backups/<directory>/`, containing `archive.dump`, `archive.dump.sha256` and the original `receipt.json`.
The retained archive is a hard link protected from ordinary retention deletion, not an independent copy or protection against corruption or volume loss.
It remains protected until deployment commits, or until the unchanged previous application resumes and the next migration must select a fresh backup.
Cleanup removes only retained files, never the original backup.
An interruption before recording a selection can leave an unreferenced directory; retain it for investigation and remove it only after confirming no candidate or journal references it.
The replacement keeps the host's restore, drain, and migration records, so a restored host is not restored again and `make start` stays refused once migrations were applied.

### Recovery policy

The previous release and its generated configuration are always kept.
`make rollback` stops the active release's writers, rebuilds the search generations and the visualization cache with the previous release's own code from the current database, then starts that release; running it again returns to the newer one the same way.
The previous generations are snapshots of an older database, so rebuilding them is what makes search correct after a rollback; the site is unavailable for the rebuild, about seven minutes on the CoMSES hosts.
It is refused while a candidate has applied migrations or has a restore or migration in progress, for the same reason `make start` is.
Before any attempt to resume the active release's writers (`start`, `rollback`, or recovery), the controller invalidates the prepared candidate's drain and rebuild, including when startup only partly succeeds.
Drain and rebuild that candidate again before activation.
Before rebuilding on an active installation, the controller points aliases back to the active release's recorded generations so pruning preserves the targets needed by failure recovery.
Migrations are never reversed, so application rollback is safe only when the previous release works with the new schema; write migrations as expand-then-contract changes so it does.
When it does not, or data itself is damaged, recovery means restoring the verified pre-release backup.
Use a separately approved, isolated installation for that restoration as described below; `make restore` deliberately refuses a host with an active release.

### Data recovery into an isolated installation

Use this when PostgreSQL data is damaged or lost, or a failed migration cannot be repaired by fixing forward.
An interrupted activation uses `make recover`; an ordinary application rollback keeps the current database and uses `make rollback`.
A lost VM with an intact persistent volume may need only infrastructure reconstruction, not database restoration.

Recovery reuses Section 7's first-deployment commands, following `comses/infrastructure` ADR 0043: restore a selected backup with a selected application release, validate it, then approve activation separately.
It does not overwrite or repair the damaged installation's deployment state.
The infrastructure's existing Borg recovery workflow targets comses.net, not Catalog.
Catalog's off-host backup integration and infrastructure recovery orchestration remain deferred; the application commands below can be run directly on a separately provisioned target.

1. Record the incident, exact backup archive and checksum, its receipt and counts, the selected release manifest and SHA-256, and the separate target host/storage.
   Select a backup from before the damage, not automatically the newest one.
   Start with the release that produced it when available; using another release requires checking database/client compatibility and its migrations.
   Record which later writes could be lost and obtain the service owner's data-replacement approval.
2. Preserve the original installation, its database, secrets, release records and incident logs for investigation.
   If it can still accept writes, agree on and enforce a write freeze before replacing service; remove its writer containers so a reboot cannot restart them, and keep its public ingress closed during the incident.
   Restoring an isolated copy for selective record repair does not itself authorize replacing the live database.
3. Have infrastructure provision a separate host with empty application volumes and the Section 7 host contract.
   A different checkout on the original Docker host is insufficient: Catalog uses the fixed `comses-catalog` project and would reuse that host's volumes.
   Do not copy `docker/deploy/state`, runtime Compose files, or database volumes from the damaged installation.
   Provision fresh target configuration and secrets; retain the originals separately.
4. Follow Section 7 through `prepare`, choosing the intended identity at `configure` time; identity cannot later change from staging to production.
   A drill uses `HOST_ID=staging`, `HTTP_BIND=127.0.0.1:80`, no working SMTP credentials and empty Sentry DSNs.
   A production replacement uses its own production configuration, with ingress closed and outbound integrations blocked by the infrastructure until activation approval.
   Do not import production credentials into a drill.

On the isolated target, after Section 7's host checks and `prepare`, set `DUMP` to the selected archive's absolute path:

```sh
(cd "$(dirname "$DUMP")" && sha256sum --check "$(basename "$DUMP").sha256")
make restore DUMP="$DUMP" CONFIRM=comses_catalog
CONFIRM_SCHEMA_MIGRATION=1 make migrate
make rebuild
make status
```

Stop here before `activate`.
Only data services and temporary management-command containers have been started; the web service and scheduler remain stopped.
Compare the restore receipt's counts with the backup receipt, inspect representative records, and confirm the migration plan and search validation succeeded.
A successful import or matching counts alone does not establish that the application works.
If a phase fails, use the failure table above on this target; retain the same selected backup and release when retrying.
Changing either input requires a newly reviewed attempt.

For functional checks on a drill, obtain approval to start only its web services on the loopback binding:

```sh
COMPOSE="$(python3 -c 'import json; print(json.load(open("docker/deploy/state/candidate.json"))["compose_file"])')"
docker compose -p comses-catalog -f "$COMPOSE" up -d --no-build --wait django nginx
```

Through an SSH tunnel to the drill's loopback port, run Section 1's browser checks and verify a curator edit reaches both the database and search.
Check that the scheduler is absent and mail uses the file backend.
Test edits change only the drill database; discard or explicitly reverse them before accepting a replacement as production data.
Stop the temporary web services before retrying any restore, migration, or rebuild:

```sh
docker compose -p comses-catalog -f "$COMPOSE" stop django nginx
docker compose -p comses-catalog -f "$COMPOSE" rm --force django nginx
```

For an actual replacement, the owner must approve the recovered data, accepted loss of later writes, production configuration and integration settings, and the ingress switch.
Then run `make activate`, `make validate`, `make backup`, and `make release-report` on the replacement and have infrastructure switch ingress to it.
`activate` starts the scheduler as well as the application; it is not a read-only validation command.
Keep the original installation unavailable and intact until its retention period and cleanup are approved.
A drill can finish without activation or a traffic switch.

Record backup/release identities, target, phase results, functional checks, elapsed time, and what was not tested outside the disposable host before teardown.
Catalog's current backups share the database's `/srv` volume; loss of that volume is recoverable only if an independent copy exists.
This procedure does not establish off-host backup coverage or a rehearsed production traffic switch.

## Operational reference

### Host layout

Host state lives on the persistent `/srv` volume inside the Git-ignored `docker/` tree of the operator's checkout:

| Path | Purpose |
| --- | --- |
| `/srv/apps/comses-catalog/docker/deploy/host.env` | fixed `staging` or `prod` identity and HTTP bind |
| `/srv/apps/comses-catalog/docker/secrets/` | Django configuration and PostgreSQL password |
| `/srv/apps/comses-catalog/docker/deploy/state/` | candidate, active, rollback, journal, and history |
| `/srv/apps/comses-catalog/docker/deploy/releases/` | immutable release bundles and rendered Compose files |
| `/srv/apps/comses-catalog/docker/deploy/runtime/` | the active release's Compose file |
| `/srv/apps/comses-catalog/docker/deploy/shared/` | staging mail, and the infrastructure's bind of the backups root at `shared/backups` |
| `/srv/apps/comses-catalog/docker/deploy/receipts/`, `reports/` | restore receipts, release reports, and the logs kept from failed activations |
| `/srv/backups/comses_model_catalog/` | the infrastructure's backups root for this workload: verified dumps with their checksums and receipts, the `last-successful-backup` marker, and the `.backup.lock` the backup command and every changing phase hold |

Never delete or `git clean` the `docker/` tree; it holds the secrets and records that match the database volume.
A checkout used for local development may also hold `docker/pgdata` and `docker/shared`; release phases never touch them.
Nothing on the application side lives on the root disk, and no host command runs as root (the processes inside the containers do, as the images define); after the infrastructure replaces the VM instance, its convergence restores the mount, the bind, and the kernel setting, and `make storage-preflight` confirms them.
After a reboot every container of the active release restarts on its own; nginx answers 502 until Elasticsearch and Django are up, about four minutes on the CoMSES hosts, and `make validate` confirms the result.
Hosts always use Compose project `comses-catalog`, as the CoMSES infrastructure declares; local development uses `catalog`.
Database and search volumes are named volumes under `/srv/docker` and are never deleted by release phases.

Nginx publishes on `127.0.0.1:80` by default.
To change it, rerun `make configure` with the same `HOST_ID` and an explicit `HTTP_BIND=<address>:<port>`; the new bind applies from the next release.

### Logs

Every container logs to stdout and stderr, which the infrastructure's Docker logging policy collects and bounds; nothing writes log files.
`make logs` follows the active release and `docker compose -p comses-catalog -f "$COMPOSE" logs <service>` reads one service.
A release or rollback recreates the containers and discards their logs; a failed activation first keeps a copy of the candidate's logs in `docker/deploy/reports/`.

### Backups and scheduler

The scheduler container runs the nightly backup at 02:00 UTC from `/etc/cron.d/catalog-backup`, the schedule the CoMSES infrastructure declares for this workload, and the application's daily and monthly tasks from `cron.daily` and `cron.monthly`.
`manage.py backup_database` holds `.backup.lock`, writes a PostgreSQL custom-format dump validated with `pg_restore --list`, its SHA-256 file, a JSON receipt, and the `last-successful-backup` marker into the backups root, and removes dumps older than 30 days.
`make backup` runs the same command before a release and verifies the result from the host; `make backup-status MAX_AGE=86400` fails unless the latest receipt verifies, the marker names it, and it is under a day old.
These backups share the `/srv` volume with the database; losing that volume loses both, and off-host copies are still to come.

```sh
COMPOSE=/srv/apps/comses-catalog/docker/deploy/runtime/docker-compose.yml
docker compose -p comses-catalog -f "$COMPOSE" exec -T scheduler cat /etc/cron.d/catalog-backup </dev/null
docker compose -p comses-catalog -f "$COMPOSE" exec -T scheduler run-parts --test /etc/cron.daily </dev/null
docker compose -p comses-catalog -f "$COMPOSE" logs --since 24h scheduler
cat /srv/backups/comses_model_catalog/last-successful-backup
```

### Service image transitions

Database and search-engine upgrades are separate, reviewed transitions, never side effects of a routine release.
`make prepare` refuses a release whose support image digests differ from the active release's.
Such an upgrade gets its own runbook when it is planned, with a backup, a tested procedure, and its own approval.

### Image registry, tags, and footer

Hosts accept only image digests, never tags.
The `sha-<commit>` tag is published once per commit; a re-run reuses its digest.
The application footer shows `git describe` from the build, so a later release tag does not change it.
