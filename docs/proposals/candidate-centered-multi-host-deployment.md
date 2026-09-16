# Proposal: candidate-centered multi-host deployment

**Status:** Proposed; future architecture, not a description of the current
implementation. **Scope:** the catalog application, its Docker Compose
operational files, release state, schema workflow, and operator Make UX on
independent staging and production hosts.

## Goals and non-goals

The target is two independent servers:

1. CI builds one application image and publishes it immutably.
2. Human QA deploys that exact image digest to staging.
3. Production deploys the same digest independently, after QA approval.

Production has no staging configuration, promotion lookup, or staging runtime
dependency. This proposal does not specify orchestration beyond Docker
Compose, application feature flags, database migration policy beyond the
requirements below, or an ES8 index design. It does not promise zero downtime.

## Current problem

The current single-host workflow mixes staging and production release metadata,
uses promotion defaults, and has a shared root operational file. That makes
environment identity and rollback history easy to confuse and permits a
staging state to become coupled to production operations. The future workflow
must make the candidate, host, digest, and release state explicit at every
boundary.

## Topology and trust boundaries

- **CI/build boundary:** CI checks out source, builds the image, verifies it,
  and pushes it to the registry. CI does not receive production credentials or
  operate production Compose.
- **Staging host:** owns staging `host.env`, credentials, database, volumes,
  Compose project, and release state. It may run QA and candidate operations.
- **Production host:** owns a separate production `host.env`, credentials,
  database, volumes, Compose project, and release state. It accepts only an
  explicitly supplied approved digest and has no access to staging state or
  configuration.
- **Registry:** is the artifact handoff. Hosts pull the exact digest using
  host-local credentials. A tag may identify a build in CI, but deployment
  input is a digest.
- **Operator boundary:** a human approves the staging result and explicitly
  invokes the production command. No host infers production input from another
  host.

The root `docker-compose.yml` is host-local, generated, last-known-good active
configuration. It is never transferred between hosts. Compose project identity
and all paths must be resolved from the local checkout and protected host
configuration.

## CI build, publish, and QA handoff

CI should:

1. Build from the reviewed commit with the production Dockerfile and required
   build checks.
2. Push the image, resolve its immutable content digest, and verify the
   registry returns that digest.
3. Publish a handoff containing the image name and digest, the deployment-bundle
   Git revision, build result, and migration notes. The handoff is initially a
   procedural release/change record. A future signed manifest may strengthen
   it, but signatures are not required by this proposal.

The human QA sequence is:

```sh
# on staging, after CI has published the digest and bundle revision
make candidate IMAGE=registry/catalog@sha256:<digest> BUNDLE_REVISION=<git-sha>
make backup
CONFIRM_SCHEMA_MIGRATION=1 make schema-migrate
make deploy
make status
make release-report
# Human QA tests the staging host and records approval for this digest.
```

The production operator checks out the same clean bundle revision, verifies the
handoff/change record, and repeats `make candidate IMAGE=... BUNDLE_REVISION=...`
with the same digest on production. No staging file, state directory, or
promotion command is copied to production.

## Image policy

Deploy, candidate, migration, and rollback inputs must be a complete
`name@sha256:<64-hex-digit-digest>` reference. Reject tags, bare references,
`:latest`, malformed digests, and digest changes hidden behind a tag. The host
must inspect or pull that exact digest before changing containers. Optional
Cosign verification is recommended: if adopted, require a pinned trusted
identity and signature/attestation policy before accepting the digest, and
record verification results in the release report.

## Host identity and Make UX

Each host has a protected, non-generated `deploy/host.env` (or equivalent
host-local path), readable only by the deployment operator, containing the
fixed environment and currently allowed ES endpoint:

```sh
CATALOG_HOST_ID=staging   # or prod; fixed after provisioning
COMPOSE_PROJECT_NAME=catalog-staging   # or catalog-prod
CATALOG_ENV=staging       # or prod
INITIAL_CATALOG_ES_HOST=elasticsearch
```

The script must reject a missing, malformed, writable-by-group/other, or
identity-inconsistent file. `host.env` is never replaced by a candidate and is
never copied between hosts. The exact project-name choice is an open decision,
but it must be fixed per host and used consistently for volumes, networks, and
inspection. `host.env` contains only immutable host identity and the initial
bootstrap ES endpoint. Commands never receive `ENV` or an ES endpoint: they
load and validate this file. After bootstrap, active and rollback state are
the sole ES endpoint authorities; cutover and rollback update those state
records, never `host.env`.

The proposed candidate-centered commands are:

```sh
make candidate IMAGE=registry/catalog@sha256:<digest> BUNDLE_REVISION=<git-sha>
make backup
CONFIRM_SCHEMA_MIGRATION=1 make schema-migrate
make deploy
make status
make release-report
make rollback
CONFIRM_ES8_CUTOVER=1 make es8-cutover
```

Every release mutation requires the local fixed host identity and a clean
checkout at the candidate's bundle revision. `candidate` is the sole
candidate-input command: after validation it atomically replaces any older
unconsumed candidate. It inherits the active ES endpoint and cannot request an
endpoint transition. `schema-migrate` and `deploy` consume only candidate
state; migration requires `CONFIRM_SCHEMA_MIGRATION=1`, while deploy never
applies migrations. `release-report` is read-only and includes both digest and
bundle revision. `es8-cutover` requires the confirmation shown; `rollback`
uses only the host-local rollback tuple.

Ordinary root `docker compose ps`, `logs`, and `config` are inspection only.
They must not be documented as a safe deployment, promotion, `up`, or `down`
interface.

## State model and history

State is host-local, non-secret metadata. Active and rollback publication
records are written atomically only after successful activation; candidate,
transaction-journal, failure, and informational-history records may be written
throughout an attempt:

```text
active:
  env, image_digest, es_host, deployed_at, commit, operator
rollback:
  env, image_digest, es_host, deployed_at, commit
candidate:
  image_digest, bundle_revision, inherited_es_host, rendered_at, validated_at
  migration_status: unmigrated | in_progress | succeeded | failed
  applied_release, applied_bundle
history:
  append-only successful deploy, rollback, migration, cutover, and failure
  records with operation, host, digest, old/new state, timestamp, and result
```

`active` is what the host is running. `rollback` is the immediately prior
successful release on that same host, never a release from another host.
`candidate` has the state machine **replace → validate → migrate (if needed) →
deploy**. Replacement is atomic only while `migration_status=unmigrated`, after
the new digest and clean checkout validate; it supersedes any unconsumed
candidate. Starting migration changes the status to `in_progress` and locks
the candidate, so normal commands cannot replace or clear it. Completion
records `succeeded` plus the applied release and bundle. A successful deployment
may clear a candidate in `unmigrated` (no migration was needed) or `succeeded`
state. A failed migration
records `failed` and likewise locks the candidate. A successful deployment
of a locked candidate is forbidden. A failed deployment retains the candidate, its
render, and failure details for retry/inspection. After successful migration,
`make deploy` is required; after failed migration, only an explicit
incident-recovery command/procedure may resolve the locked candidate. Rollback
does not consume candidate state. Candidates have no expiry; operators clear
them only through successful deployment or the explicit incident procedure.
History must
distinguish attempted, failed, and successful operations and must not be
presented as proof that a failed operation ran.

### Activation journal and recovery

Because container runtime, root Compose, state, and history cannot be committed
atomically, use a host-local transaction journal. The journal records the
operation ID, prior active state/configuration, candidate digest and bundle
revision, intended new state, and checkpoints:
`candidate-started`, `runtime-ready`, `root-published`, `state-published`, and
`committed`.

Authoritative truth after `committed` is the active metadata plus the matching
root Compose file; the runtime must be reconciled to them. Before `committed`,
the journal is authoritative for recovery intent: on restart, verify the
candidate runtime and files. If candidate `up` fails after starting any
services, first reconcile the retained prior canonical/legacy Compose
configuration with `up -d --wait` and verify its health before reporting the
candidate failure. Only a fresh host with no prior active state may instead
remove candidate services without volumes. If prior-runtime reconciliation
fails, mark the journal unrecovered and report that failure rather than claiming
the old release was restored. If runtime is ready but root/state activation is
incomplete, restore the prior runtime, restore the prior root/state, and leave
candidate state for retry. If root and state are committed but history append
failed, leave the successful activation in place and append/repair history
later; history is informational and must never undo a committed deployment.
Journal transitions and file replacements must be durable and atomic where the
filesystem permits.

## Operational invariants

- Staging and production have independent state, credentials, volumes, host
  identity, and Compose files.
- Production accepts only an explicit digest and the locally fixed prod host
  identity.
- No production command reads staging state or promotes from a staging host.
- The active root Compose file remains last-known-good until candidate startup
  succeeds; publication is atomic.
- A failed candidate startup reconciles and health-checks the prior active
  configuration before reporting failure; fresh hosts clean only candidate
  services and never volumes.
- Candidate failure leaves active Compose/state untouched and removes only
  candidate resources without deleting named data volumes.
- Deploy and rollback are non-destructive to named volumes and do not use
  `down` as a rollout primitive.
- No command silently changes ES endpoint, image digest, host identity, or
  project name.

## Candidate, deploy, rollback, and migration behavior

`candidate` renders the environment overlays with the explicit digest and the
active ES endpoint from active state (using the immutable bootstrap endpoint
only when no active release exists), runs Compose config validation, checks the
clean matching bundle revision, credentials, and image resolvability, and
records disposable candidate metadata. It must not publish the root file,
alter active/rollback state, or change running services.

`deploy` revalidates host identity, candidate inputs, release state, image
digest, credentials, and database readiness. It performs a non-mutating
`migrate --check`; pending migrations fail the deploy with instructions to run
the explicit migration command. It starts the candidate with `up -d --wait`,
then atomically publishes the root file and active state. If startup fails,
the old root and state remain. If post-start persistence fails, it attempts to
restore the prior Compose runtime and metadata; it must report recovery failure
separately and never claim success without verifying it.

`rollback` uses only this host's rollback tuple and its exact digest. It starts
that candidate, verifies readiness, then atomically publishes it and rotates
active/rollback. A missing or incompatible rollback tuple fails closed. A
successful rollback makes the release it replaced the next rollback tuple.

`schema-migrate` consumes the candidate and runs against that host's existing
database. It verifies readiness, then runs `makemigrations --check --dry-run`,
`migrate --plan`, `migrate --noinput`, and `migrate --check` in order. It never
publishes Compose or release state. A failed or partly applied migration is a
manual incident; there is no automatic schema rollback. Migrations must use
expand/contract-compatible changes when old and new application versions can
overlap. Production and staging databases are separate in this topology, so
each host's migration decision is explicit; a production migration is not
implied by staging QA.

## ES8 behavior

ES8 rebuild and validation remain an explicit gate. A normal deploy and
candidate must inherit the active ES endpoint and reject a direct transition.
Only `make es8-cutover` may change it: it always operates on the active image,
never a candidate, and requires explicit `CONFIRM_ES8_CUTOVER=1`. It rebuilds,
validates aliases/counts/query behavior, and deploys that active image against
ES8. A failed rebuild, validation, or cutover leaves the active release
unchanged. Rollback restores the prior active image and its recorded endpoint;
ES8 index/alias rollback remains a separate decision from application
rollback.

## Fresh-host bootstrap

Provision each host's fixed `host.env`, credentials, registry access, Docker,
and storage first. On a fresh host only, `schema-migrate` may render a
candidate, start and wait for only its database service, verify readiness, and
apply the explicit migration sequence. It must not publish root Compose or
release state. The first full deploy then requires that database to be
available and passes the non-mutating migration guard. A host with existing
catalog containers, state, or conflicting Compose artifacts is not fresh and
must fail closed until reconciled.

First release, on each host independently:

```sh
make candidate IMAGE=registry/catalog@sha256:<digest> BUNDLE_REVISION=<git-sha>
CONFIRM_SCHEMA_MIGRATION=1 make schema-migrate
make deploy
```

Subsequent release:

```sh
make backup
make candidate IMAGE=registry/catalog@sha256:<digest> BUNDLE_REVISION=<git-sha>
CONFIRM_SCHEMA_MIGRATION=1 make schema-migrate
make deploy
```

The candidate must be recreated for each digest/revision. Staging and
production databases are independent in this topology, so the explicit
migration is performed separately on each host when its release requires it.

## Backup, storage, and security

Backups are host-local and required before schema migration or destructive
maintenance for every existing database. The sole exception is a fresh host
with an explicitly empty database. Each successful backup writes a local
versioned receipt naming
the artifact, database/release context, UTC time, byte size, and checksum; the
receipt is accepted only after an age/retention policy check and a readable
checksum verification. The backend, encryption mechanism, retention period,
and restore-test schedule are implementation decisions. Named
database/search/application volumes persist across deploys and rollbacks. Do
not delete them as part of candidate cleanup. Restore is an explicit
maintenance operation and does not imply schema rollback.

Registry credentials belong only on the host or CI secret store, must not be
written into Compose candidates, release reports, or history, and should be
least-privilege read-only on deployment hosts. Protect `host.env`, credentials,
state files, and backups with restrictive ownership and permissions. Reports
should redact secrets while retaining digest and verification evidence.

## Removal and migration list

The implementation must remove or reject:

- a shared host workflow that treats staging and production as one Compose
  deployment;
- command-level `ENV` inputs and promotion defaults; environment comes only
  from fixed host identity;
- cross-host copying of root Compose files, `deploy/state`, or credentials;
- generic previous-release fields presented as a production rollback anchor;
- production commands that infer image, ES host, or environment from staging;
- mutable image tags and tag-based rollback;
- automatic migrations during deploy or promotion;
- legacy root `deploy.sh` command forwarding and any `-f deploy/state` command
  surface.

Existing hosts require an operator-led migration: record the actually running
tuple, provision and verify fixed host identity, create independent state,
validate local volumes/backups, and perform a candidate-based deployment before
retiring the old promotion/anchor mechanism. Do not delete legacy artifacts
until the local active state and rollback tuple have been independently
verified.

## Implementation phases and acceptance criteria

1. **Host contract:** add protected host identity loading, validation, stable
   project naming, and secret/permission checks. Test mismatch and missing-file
   failures.
2. **Candidate engine:** separate render/validate from publish/start; add
   disposable candidate state and atomic root publication. Test render,
   Compose failure, startup failure, and cleanup.
3. **Independent release state:** implement active/rollback/candidate schemas,
   atomic writes, history, reports, and digest verification. Test repeated
   deploy, rollback toggle, and failed persistence recovery independently on
   both hosts.
4. **Explicit schema workflow:** implement fresh DB bootstrap, existing-host
   migration, backup gates, and pending-migration deploy guard. Test command
   order, confirmation, partial-failure handling, and no state publication.
5. **ES8 and migration:** implement same-digest cutover validation and remove
   promotion/legacy command paths. Test ES6 rejection, ES8 gate, and rollback.
6. **Operational migration:** migrate staging and production separately, verify
   reports/backups/rollback, then remove the old shared mechanism.

Acceptance requires that a digest deployed and QA-approved on staging can be
deployed independently on production; no staging state or configuration is
read by production; all failure paths preserve last-known-good state or report
verified recovery failure; and all commands in this proposal pass shell/static,
Compose-render, mocked Docker, and end-to-end disposable-host tests.

## Testing matrix

| Area | Required cases |
| --- | --- |
| Identity | missing, wrong host, permission failure, environment/project drift |
| Digest | tag/bare/malformed rejection, exact pull, optional Cosign failure |
| Candidate | replacement only when unmigrated, clean revision/digest match, inherited ES, cleanup, retained failure |
| Deploy | first release, repeat release, pending migration, failed-up prior-runtime reconciliation |
| Rollback | absent tuple, repeated toggle, digest/config mismatch, failed recovery, candidate retained |
| State | journal crash points, atomic publication, migration locks/status, history repair, report accuracy |
| Migration | empty fresh DB exception, backup receipt, confirmation, ordered commands, partial apply lock |
| ES8 | ES6 rejection, active-image-only cutover, validation failure, endpoint state update, alias checks |
| Separation | staging/prod state, host.env, and credentials cannot cross host boundary |
| Inspection | root `ps`, `logs`, and `config` use only local host config |

## Open decisions

- Exact host-local path and permission enforcement for `host.env`.
- Whether Compose project names remain `catalog` per host or become distinct
  names such as `catalog-staging` and `catalog-prod`.
- Registry, digest retention, garbage collection, and Cosign identity/policy.
- Backup backend, encryption, retention, restore drills, and RPO/RTO.
- Whether production schema migration requires a separate approval token or
  maintenance window in addition to `CONFIRM_SCHEMA_MIGRATION=1`.
- Health/readiness criteria and the operator approval record for QA handoff.
- Exact state format/versioning and release-report output schema.
- Whether ES8 cutover remains a host-local command or requires a second human
  approval artifact.
