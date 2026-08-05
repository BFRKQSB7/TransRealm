# Contributing to TransRealm

## Start here

Give any development Agent `DEVELOPMENT_STATE.md`. It is the only handoff entrypoint. Follow its current Task, required documents, allowed scope, FIT/ADAPT/REPLAN decision, and evidence requirements.

## Required checks

Run from the repository root before requesting review:

```bash
py -3.12 -m pytest -q
py -3.12 -m ruff check src tests
py -3.12 -m mypy src tests
```

GUI changes also require a local GUI interaction test. Migration, import/export, recovery, credential, or HTTP changes require the relevant end-to-end or fault-injection tests.

## Change boundaries

- Keep each change inside the active Task's `allowed_paths`.
- Do not rewrite published SQL migrations; add a new numbered migration.
- Do not commit API keys, credentials, user databases, backups, exports, logs, `.aiproject` files, or build output.
- New dependencies require a Task-approved reason, version, license, security, lockfile, and packaging review.
- Do not stage, commit, push, create releases, or make paid requests without explicit task/user authorization.

## Review

Every pull request identifies its Task/Milestone, base commit, FIT/ADAPT/REPLAN decision, risk, tests, rollback path, and documentation changes. Credential, HTTP, migration, Project format, dependency, CI, and release changes require independent review.
