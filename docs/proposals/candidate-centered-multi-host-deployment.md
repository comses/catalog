# Candidate-centered multi-host deployment

**Status:** Catalog's application-side release controller and artifact pipeline are implemented; the pilot was rehearsed on staging, including the production cutover, on 2026-10-27.
The infrastructure adapter and reusable integration design are deferred pending alignment with the infrastructure maintainer and are not part of this delivery.
Catalog provides a pilot for evaluating the approach; adoption by other applications remains a separate decision.

This document records the design and is not an operator procedure.
Use [the release and deployment runbook](../deployment-runbook.md) for real releases and [the deployment acceptance guide](../deployment-acceptance-testing.md) to validate the machinery.

## Contract

Build once, test in isolated staging, promote the same artifacts, and deploy against production's own data and configuration.

- CI tests the checkout in the development image, builds one production image per `main` commit, labels it with its source commits, checks that its gunicorn runs and that the labels name the commits, publishes it once, and records a release manifest.
- Staging and production are independent installations with their own databases, credentials, backups, and release state; each runs its own migrations.
- Production deploys the staging-approved manifest and digests; a rebuilt image is a new release.
- Hosts accept only digest-pinned images.
- Database and search-engine upgrades are separate, reviewed transitions, never side effects of a routine release.
- Downtime between writer drain and activation is accepted; maintenance mode is not part of the first version.

## Ownership

| Catalog repository | comses/infrastructure |
| --- | --- |
| application images and the release manifest | environment-to-host mapping and operator access |
| Compose definitions and configuration validation | servers, storage mounts, Docker, networking |
| application backups and their verification | enforcing backup readiness before production changes |
| writer drain, migrations, startup | maintenance entry and exit (later) |
| application readiness and compatible rollback | promotion checks, orchestration, deployment receipts |

The table separates application responsibilities from infrastructure responsibilities; it does not imply that automated infrastructure deployment is delivered here.
For this delivery, the operator follows the runbook to select the manifest, run the phases, confirm the staging-approved artifact and retain validation evidence.
The JSON phase results and inherited backup-lock protocol provide integration points for a future adapter; its design and rollout belong to the infrastructure repository.

## Release manifest

`scripts/release_manifest.py` writes `release-manifest.json` (schema 2, kind `catalog-release`) in CI after the image is published or found already published:
the Catalog and Citation commits, the application image digest, the support image digests rendered for staging and production, the search backend, the base image, Python and key package versions read from the image, the `uv.lock` hash, and the CI run and build time.
The release-tag workflow attaches the same file to the GitHub Release, so tagged releases and urgent fixes share one format.
The controller validates the schema, requires the checkout's `HEAD` to equal the manifest's commit, the image labels to match both commits, and the rendered support images to equal the manifest's.

## Phases

The controller (the `scripts/catalogctl` package, run as `python3 -m catalogctl`) is the machine interface; Make targets wrap it for people.
Every phase prints exactly one JSON object on stdout, writes progress to stderr, and exits non-zero when a check fails.
The release phases (`prepare`, `restore`, `drain`, `migrate`, `rebuild`, `activate`, `rollback`, `recover`, `candidate-retry`, `backup`, `validate`, `release-report`, `start`, `stop`) hold the host lock; `prepare`, `drain`, `migrate`, `rebuild`, and `activate` return `already: true` when repeated after success, `restore` refuses a second run instead, `backup` takes a new dump each time, and `rollback` toggles between the two releases.
The setup commands (`storage-prepare`, `configure`) and the read-only ones (`storage-preflight`, `host-check`, `status`) take no lock; the setup commands are idempotent without reporting it.

| Phase | Effect |
| --- | --- |
| `storage-prepare`, `storage-preflight` | the operator-owned directories under `docker/`; verification of the `/srv` mount, canonical checkout, the infrastructure's backups directory, and the kernel setting, changing nothing |
| `configure` | fixed host identity, HTTP bind, secrets generated once (optionally importing an existing installation's settings); as the operator |
| `host-check` | the storage preflight plus identity, secrets, Docker, disk, and Python |
| `prepare --manifest` | validates the manifest, pulls, renders the candidate; the current release keeps serving |
| `backup`, `backup-status` | runs the application's `backup_database` command and verifies its receipt from the host, or re-verifies the latest receipt and marker and reports their age |
| `restore` | fresh host only: restores a dump into a temporary database and swaps it in |
| `drain` | stops the scheduler, then Django |
| `migrate` | requires drained writers or a fresh restore and a recent backup; records the plan; reports whether a failure changed the database |
| `rebuild` | new search generations, count validation, atomic alias switch, visualization cache |
| `activate` | refuses while another stack publishes the HTTP port, switches search to the validated generations, starts the candidate, waits for the healthchecks and requests a page through nginx, publishes state through a journal |
| `validate` | service health, running images and commit against the manifest, pending migrations, search, HTTP |
| `rollback` | stops the writers, rebuilds search with the previous release, starts it, and swaps the active and rollback records |
| `start`, `stop`, `recover`, `candidate-retry`, `status`, `release-report` | operations and recovery |

## Host contract

Host state lives on the persistent `/srv` volume, inside the Git-ignored `docker/` tree of the canonical checkout `/srv/apps/comses-catalog`, following the CoMSES infrastructure convention; it survives replacement of the VM instance with the Docker volumes.
`docker/deploy/host.env` holds the fixed identity:

```text
CATALOG_HOST_ID=staging|prod
CATALOG_ENV=staging|prod
COMPOSE_PROJECT_NAME=comses-catalog
CATALOG_DOMAIN=<fixed domain for that identity>
CATALOG_HTTP_BIND=<address>:<port>, 127.0.0.1:80 unless HTTP_BIND is given
```

Secrets are owner-only under `docker/secrets`; state, release bundles, the runtime directory, shared files, receipts, and reports live under `docker/deploy`.
Backups live in `/srv/backups/comses_model_catalog`, the infrastructure's collaborative root for this workload (`debian:operators 2775`), which Compose mounts directly into Django and the scheduler at `/shared/backups`; the application writes its verified dumps, receipts, and the `last-successful-backup` marker there under the `.backup.lock` that every changing phase also holds.
No host command runs as root (processes inside the containers do, as the images define): the infrastructure owns the `/srv` mount, the backups directory, and the `vm.max_map_count` setting, and `storage-preflight` only verifies them.
Containers log to stdout and stderr under the infrastructure's bounded Docker logging policy; no file logs, so no log binding or rotation rule.
Hosts use Compose project `comses-catalog`, as the infrastructure declares; local development keeps `catalog`.

## State model

```text
candidate.json  manifest and its SHA-256, image, revisions, artifact hashes,
                restore, drain, migration (with migration_applied), and rebuild status
active.json     activated release, its manifest SHA-256, and search aliases
rollback.json   the release before it
journal.json    in-progress activation or rollback checkpoints
history.jsonl   append-only outcomes and retry records
```

Release bundles are `git archive` copies hashed separately from their rendered Compose files; every use re-verifies both.
Activation, rollback, and recovery publish the release's Compose file into `docker/deploy/runtime/` for the operations that act on the active release.
The nightly backup runs inside the scheduler container from `cron`, as comses.net's does, so the host carries no service, timer, or copied controller; the pre-release `backup` phase runs the same command.
A failed activation keeps the candidate's container logs in `docker/deploy/reports/` before recovery recreates the containers.
A candidate with a restore, migration, or rebuild in progress or failed stays locked until an explicit retry is recorded; a finished stage does not lock it.
One writer policy serves every phase: on a host with an active release, `migrate`, `rebuild`, and `activate` require the current drain; `drain` removes the writer containers so a reboot cannot revive them; `start` and `rollback` refuse while a candidate applied migrations or has a database operation in progress; and every path that resumes the active release's writers (`start`, `rollback`, a recovered activation) resets the candidate's drain and discards its rebuilt generations, because edits made since are not in them.
`rollback` stops the writers, rebuilds the previous release's generations with that release's own code from the current database, and only then starts it, so a rolled-back release never serves a search snapshot of an older database; it costs a rebuild rather than an alias switch.
A candidate prepared to replace an unlocked one inherits its restore, drain, and migration records, because they describe the host's database and writers rather than the release, and runs its own `migrate` and `rebuild`; that is how a release is fixed forward after a failed rebuild or activation.
A candidate for the active release is a no-op, and one for the rollback release is refused in favour of `rollback`.

## Recovery

If activation fails before the new runtime is verified and the release applied migrations, the candidate's writers are stopped and the site stays down, because the previous release may not match the schema and `start` refuses it for the same reason.
Otherwise the previous runtime is restarted and checked before recovery is reported.
Once the new runtime is verified, the journal carries the new release and nothing reverts it: an interruption while the state files are published is finished by `recover`, not undone.
A failure that cannot be settled keeps the journal and blocks further changes.
Rollback rebuilds the previous release's search before restarting it and toggles when repeated.
Every rebuild on an active installation first restores the active release's recorded alias targets, so generation pruning retains them for failure recovery even after repeated candidate rebuilds.
Attempts to resume the active writers invalidate candidate drain and rebuild state before startup, including rollback finalization and partially failed startup.
Migrations are never reversed, so application rollback requires expand-then-contract migrations; otherwise recovery means restoring a selected verified backup under separate approval.
Database recovery uses the existing first-installation phases on an isolated target, preserving the damaged installation and keeping activation separate, following infrastructure ADR 0043.
The controller does not restore over an active installation or reconcile its records after a manual database replacement.
Catalog's off-host backup delivery and infrastructure recovery orchestration remain follow-up work; the runbook states these limits explicitly.

## Production cutover

Production first runs the single-host stack that `main` deployed before this process, so it moves over once, following the CoMSES legacy migration runbook: a staging rehearsal until it is repeatable, a written go/no-go, a write freeze, a final verified dump restored into the new stack, and the old stack kept stopped and intact for the rollback period.
The new stack runs beside the old one under its own Compose project, so the fallback only stops the new stack, checks the old commit out, and starts the old containers again.
The procedure is Section 8 of the runbook.

## Reuse by another application

The controller is written for Catalog and is not a shared deployment library.
Any future reuse must account for at least these application-specific areas:

- `scripts/catalogctl/constants.py`: the host identities and domains, the Compose project and canonical checkout, the backups root, the service names (writers, dependencies, required services), the managed search aliases.
- `scripts/catalogctl/database.py` (the publication counts that restore and the reports check) and `scripts/catalogctl/host.py` (the database role in the generated configuration).
- `scripts/catalogctl/search.py` and the `rebuild_es_index`, `validate_search_indexes`, and `populate_visualization_cache` commands: the derived data a release rebuilds; an application without derived data drops the `rebuild` phase, the rebuild inside `rollback`, and the search checks in `scripts/catalogctl/operations.py`.
- `catalog/core/backups.py` and `deploy/cron/catalog-backup.crontab`: the application-owned backup; the dump, receipt, marker, lock and prune carry over, the publication counts in the receipt are Catalog's.
- `scripts/release_manifest.py`: the dependency list, the submodule, and the version probes the manifest records.
- The Compose files' healthchecks, which `activate` and `validate` rely on, and `scripts/compose.sh`, which renders them per environment.

The phase sequence, locking, state model, journal, manifest and CI publication offer patterns for reuse, but their suitability and interfaces require validation against each application's lifecycle.

## Deferred work

- The `comses/infrastructure` adapter and reusable integration contract, pending alignment with the infrastructure maintainer.
- Edge maintenance mode.
- Off-host backup copies, scheduled restore drills, and backup monitoring.
- Image signatures and a verification policy if the registry threat model requires it.
- The pilot report comparing ease, downtime, reliability, rollback, reproducibility, and cost with the comses.net flow.
