## Task

- Task / Milestone:
- Base commit:
- FIT / ADAPT / REPLAN:
- Risk: low / medium / high / release-blocking

## Scope

- Allowed paths:
- Forbidden paths:
- User-visible behavior and invariants:

## Verification

- [ ] Targeted tests:
- [ ] `py -3.12 -m pytest -q`
- [ ] `py -3.12 -m ruff check src tests`
- [ ] `py -3.12 -m mypy src tests`
- [ ] GUI / migration / recovery / HTTP E2E as applicable

## Regression protection

- Existing capabilities affected (or `none`):
- Invariants that must remain true:
- Existing regression tests run (file/nodeid + result):
- New tests added (file/nodeid + result):
- Existing tests changed or removed (reason + independent reviewer):
- [ ] Full pytest is supplementary; it does not replace the compatibility baseline above
- [ ] Every affected existing test passed before and after the change

## Risk and recovery

- [ ] No secrets, databases, backups, logs, exports, artifacts, or `.aiproject` files included
- [ ] Migration added only; no published migration changed
- [ ] Dependency / Project format / credential / public API impact reviewed
- Rollback or forward-recovery path:
- Known gaps:

## Review and documentation

- [ ] Independent review completed for high-risk paths
- [ ] `DEVELOPMENT_STATE.md` and affected contracts updated
