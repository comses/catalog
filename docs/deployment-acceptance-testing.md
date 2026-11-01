# Deployment acceptance testing

This guide validates the release machinery on a personal fork before it is trusted for real releases.
It is not the procedure for a real release; use [deployment-runbook.md](deployment-runbook.md) for that, and for every command not repeated here.

This guide covers Catalog's application commands and release artifacts, operated directly through the runbook.
Delivery of the infrastructure adapter is deferred pending agreement with the infrastructure maintainer.
Its orchestration tests are separate from application acceptance; first installation, failure recovery and isolated restore still need the checks below.

Run it when accepting the deployment system or after material changes to CI publication, the release manifest, the phases, restore, backup, activation, or rollback.
Do not repeat it for application releases when the machinery is unchanged.

Stop at the first unexplained failure.

## Where to run it

The September 2026 disposable VMs no longer exist.
Use one of these targets:

- **Local rehearsal on the workstation:** a local registry, digest-pinned images built from two commits, a scratch host layout through `CATALOG_HOST_DIR` and `CATALOG_BACKUP_DIR`, and nginx on an unused loopback port. It exercises every phase, the Compose version installed locally, cross-process locking, and the in-container backup, but not the infrastructure's bind mount or real ingress.
- **Real staging,** before production promotion is enabled: the full path through `https://staging-catalog.comses.net`, including the failure checks below. Staging holds a copy of production data and has no users, so failure checks are allowed there; never run them on production.

## 1. Publish a fork release manifest

Set the fork values on the workstation:

```sh
export SOURCE_OWNER=asuworks
export CATALOG_SOURCE_REMOTE=fork
test "$SOURCE_OWNER" != comses
```

Push the tested branch and open a fork pull request; its run must test without publishing (the publish and upload steps are skipped).
Then fast-forward the fork's `main` to the tested commit, wait for the fork `main` run, and download its manifest exactly as in runbook Section 3, using `--repo "${SOURCE_OWNER}/catalog"` and the fork commit.

After the first fork publication, make the fork package public once:

```sh
printf 'https://github.com/users/%s/packages/container/catalog/settings\n' "$SOURCE_OWNER"
docker manifest inspect "$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["image"])' "$MANIFEST")" >/dev/null
```

Re-run the fork `main` run once and confirm its manifest names the same image digest; a commit is published only once.

## 2. First deployment

Follow runbook Section 7 with the fork manifest.
On a fork, `make prepare` checks out Citation from the fork first when called with `CITATION_OWNER="$SOURCE_OWNER"`.
A host without the CoMSES infrastructure needs the checkout and the backups bind that its convergence would create.
Ansible gives every directory it creates on the way to the bind target the same owner and mode, so create each level explicitly:

```sh
sudo install -d -o "$USER" -g "$(id -gn)" /srv/apps/comses-catalog
git clone "https://github.com/${SOURCE_OWNER}/catalog.git" /srv/apps/comses-catalog
for directory in /srv/backups/comses_model_catalog /srv/apps/comses-catalog/docker{,/deploy,/deploy/shared,/deploy/shared/backups}; do
  sudo install -d -o "$USER" -g "$(id -gn)" -m 2775 "$directory"
done
sudo mount --bind /srv/backups/comses_model_catalog /srv/apps/comses-catalog/docker/deploy/shared/backups
```

Confirm that counts match the source, `make validate` passes, staging reports the file email backend, the scheduler discovers its tasks, running `/bin/sh /code/deploy/cron/backup_database` in the scheduler container succeeds, and `make backup-status MAX_AGE=600` reports a verified backup.

## 3. Release, failures, and rollback

Publish a second commit through Section 1, then run runbook Section 4 with its manifest.
Validate each failure path in turn, and restore a clean state before the next one:

| Check | How | Expected |
| --- | --- | --- |
| Mutable input | `make prepare` with a manifest whose `image` is a tag | refused before anything is pulled |
| Wrong checkout | `make prepare` while `HEAD` is another commit | refused, naming the commit to check out |
| Migration without drain | `CONFIRM_SCHEMA_MIGRATION=1 make migrate` right after `prepare` | refused, asking for `make drain` |
| Failed migration | a migration that raises | `migrate` fails, the candidate is locked, `make status` shows whether changes were applied, `make start` is refused |
| Fix forward | `candidate-retry`, then `prepare` a release that fixes the migration | the new candidate keeps the drain and migration records; `migrate` through `validate` succeed |
| Unhealthy dependency | stop Elasticsearch during `make rebuild` | rebuild fails; `candidate-retry` starts Elasticsearch and restores the previous aliases; `rebuild` then succeeds |
| Interrupted activation before runtime verification | on an existing installation, interrupt the controller and any remaining `docker compose` child after the new Django container starts but before the journal reaches `runtime-ready`; exercise both with and without applied migrations | `make status` shows the journal; `make recover` keeps the writers stopped when the release applied migrations and restores the previous release otherwise; a repeated `recover` reports nothing to recover; after fixing the interruption's cause, `activate` and `validate` succeed |
| Interrupted activation after runtime verification | interrupt the controller after the journal reaches `runtime-ready` but before finalization completes | `make recover` verifies and finalizes the new release; `validate` passes, the candidate and journal are cleared, and a repeated `recover` reports nothing to recover |
| Wrong running artifact | start a container from another image, then `make validate` | validation fails and names the service |
| Idempotent rerun | repeat each changing phase immediately after it succeeds (`prepare`, `drain`, `migrate`, `rebuild`, `activate`), before advancing to the next phase | `ok` with `already: true`, nothing changed; preparing the already-active release instead returns `already_active: true` |
| Rollback | `make rollback` twice | toggles between the two releases, rebuilding search each time (a few minutes on the hosts); an edit made under the newer release is reflected after the rollback; browser smoke test after each |

## 4. Production cutover rehearsal

Before production is cut over, set staging up like production (the single-host stack at production's commit, restored from a production dump) and run runbook Section 8 against it with the manifest intended for production.
Run it twice: once through the fallback, which must bring the old stack back serving, and once to acceptance.
Then reboot the staging VM and confirm that only the new stack starts, the backups bind is mounted again, and `make validate` passes once the healthchecks settle (nginx answers 502 for a few minutes while Elasticsearch starts).
Record the downtime from the write freeze to a passing `make validate`.

Acceptance passes only when automated checks, fork CI behaviour, counts, independent host state, search rebuilds, backups, scheduler discovery, rollback, the cutover rehearsal, and every failure check behave as expected.

## 5. Recovery from a selected backup

Rehearse the runbook's "Data recovery into an isolated installation" procedure after changes to restoration or recovery instructions.
Use a separate empty target, an explicitly selected verified application backup and its compatible release manifest.
Record the backup receipt counts and representative publication values before restoring.
Run `prepare`, `restore`, `migrate`, and `rebuild`, and verify that web and scheduler services remain stopped.
With drill-only web startup approved, check public search, a publication page, and a curator edit reflected in both PostgreSQL and Elasticsearch while the scheduler remains absent.
Preserve the original installation and verify that it was not modified.
Export the evidence and stop the temporary web services; a drill does not require production activation or an ingress switch.
A local rehearsal establishes application behavior only: host provisioning, off-host backup delivery and production traffic switching need their own infrastructure rehearsal.
