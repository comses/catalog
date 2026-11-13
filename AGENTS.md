# Agent instructions

## Repository workflow

- Run Django commands and application tests through Docker using the root Makefile. Deployment-controller tooling and checks run on the host.
- `citation/` is a Git submodule with its own `AGENTS.md`. Preserve its pinned revision unless the task requires changing it.
- `docker-compose.yml` is generated. Edit `base.yml`, the environment overrides (`dev.yml`, `staging.yml`, `prod.yml`), or `scripts/compose.sh`, then regenerate with `make compose-dev` for local development.
- For application changes, use `make check`, `make migrations-check`, and `make test`; include Citation checks when affected. For deployment tooling, use `make ci-check`, plus `make ci-compose-check` when Compose configuration changes.
- Follow `docs/deployment-runbook.md` for host operations. Releases use manifest-pinned image digests; staging and production are separate installations.

## Commits

- Use Conventional Commit messages and keep commits logically scoped. Treat the diff as the record of what changed; commit bodies should capture why and any non-obvious decisions.
- Do not create commits unless the user explicitly asks.
- Use scopes only for established repository areas.
- For non-trivial changes, use concise lowercase `-` bullets for rationale, tradeoffs, or operationally relevant details that are not evident from the diff.
- Omit a body when it would only restate the subject or diff.
- Prefer branch-wide issue references in the pull request description. Do not repeat the same issue footer across every commit in a branch. Add a lowercase commit footer only when standalone traceability matters, such as for a direct fix, backport, or independently cherry-picked change.
