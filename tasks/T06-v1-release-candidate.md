# T06 — V1 regression and local Windows candidate

STATUS:
See `tasks/README.md`.

MILESTONE:
M3 — V1 Local Acceptance

---

## GOAL

Prove the V1 contract against a fixed candidate identity, build the authorized EXE/ZIP green-package candidate, and complete acceptance on the user's current Windows computer with reproducible evidence and rollback material. Compatibility on other computers is not required.

## USER VALUE

The user receives a launchable, portable TransRealm candidate whose core translation, recovery, format fidelity, credential safety, old-project compatibility, and uninstall/data-survival paths have actually been exercised.

## WHY NOW

This is the final gate after the core and product surface are complete. It is the only task that intentionally runs broad release regression and packaging checks.

---

## SIZE

L — about 0.5–1.5 days, excluding any separately requested external review or release action

## RISK

HIGH — release identity, packaging completeness, user data safety, and truthful evidence.

## RECOMMENDED MODEL

### CAPABILITY LEVEL

LEVEL 3 — Strong Coding / Reasoning

### PREFERRED MODEL

`gpt-6-astra`

### FALLBACK MODEL

`gpt-5.6-sol` with XHIGH thinking

### THINKING

MEDIUM

### WHY

Most work is verification and narrow release fixes. Radar's hard-problem pick gives Astra MEDIUM and HIGH the same measured IQ; start at MEDIUM, then escalate to HIGH if a release gate exposes a cross-domain defect.

### MODEL RECHECK

YES — this task is last in the plan; recheck current model reliability/cost and packaging environment before execution.

## CAN DOWNGRADE MODEL

NO

---

## DEPENDS ON

T05

## BLOCKS

NONE

---

## REQUIRED READING

### Always

- This task file

### Source files to inspect

- `scripts/build_release.py`
- `scripts/check_candidate_hygiene.py`
- `pyproject.toml`
- `src/transrealm/migrations/`
- `src/transrealm/ui/main_window.py`
- release-relevant tests identified by the commands below and current code

### Additional docs

- `docs/RELEASE.md`
- `docs/PRODUCT.md`

---

## EXPECTED BASELINE

T04 and T05 are DONE, so the three-page V1 journey is complete. The repository already contains a Windows onedir/ZIP build script and candidate hygiene checker, but no result is presumed for the current source, dependency lock, endpoint, or locally extracted candidate. AV scans and scan/skip records are outside acceptance; a clean Windows installation or VM is not required. Build, sign, tag, push, upload, and publish are separate permissions.

## START REALITY CHECK

Confirm dependencies are DONE and identify the exact commit, branch, worktree state, Python/Windows architecture, lockfile, and intended version. Run the full source quality gate before building. If the user has not authorized candidate construction in the current execution request, perform only read-only readiness checks and stop BLOCKED with the exact authorization needed; do not treat this planning packet as build/release permission.

---

## CONTRACT

- Candidate identity records version, commit, branch, dirty state, build time, Windows architecture, executor, artifact hashes/sizes, toolchain, and recovery ref. Evidence from another identity is not reusable.
- Commit the reviewed source and documentation before building, and retain the existing clean-source build guard. No dirty-source bypass is required or authorized by this packet.
- Full pytest, Ruff, mypy, release hygiene, migration/recovery, six-format fidelity, credentials, archive/Open Directory, and actual Windows GUI checks are mandatory; unknown/not run is not pass.
- Candidate includes every migration SQL, Qt platform plugin, `.qm` translation, and runtime resource; it excludes secrets, user databases/backups/logs/exports, `.aiproject`, stale candidates, and unredacted evidence.
- Validate with a controlled OpenAI-compatible endpoint; do not incur paid requests or contact external services without explicit authorization.
- Build authorization does not authorize commit, signing, tag, push, upload, GitHub Release, or publication. Each external action requires current explicit permission.
- Never test downgrade by modifying the only user-data copy. Preserve Projects, backups, credentials, and a verified rollback artifact/ref.

## IN SCOPE

- Run the full source and release-specific regression matrix and retain concise raw results under `D:/TransRealm/.local/verification/`.
- Fix only release-blocking defects directly exposed by this matrix, with focused regression tests; report larger design defects as blockers for a new task.
- With explicit build authorization, create a fresh onedir and ZIP using `scripts/build_release.py`, archive prior local candidates under `.local/archive/`, and verify manifest/hash/hygiene.
- On the user's current Windows computer, extract into an isolated project-local directory and exercise create/open/import/translate/Stop/Resume/reopen/edit/lock/export, old project/container, Unicode/long path, read-only/unwritable targets, network/model failure, and removal without data deletion. Use isolated settings/data or verified copies, never the sole real user-data copy.
- Record the source review and actual local acceptance required by `docs/RELEASE.md`; no additional independent reviewer or public-release sign-off is required for this local-only delivery.

## OUT OF SCOPE

- New product features, V1-Full enhancements, broad refactors, schema cleanup, dependency upgrades without a demonstrated blocker, installers/updaters, code signing, store distribution, telemetry, or cloud services.
- Commit, push, tag, signing, upload, release creation, or publication without explicit authorization.
- AV scanning, clean-machine or cross-computer acceptance, and claiming endpoint/review evidence that was not actually produced for this candidate.

## IMPLEMENTATION TARGET

Treat this as a verification-first release task. Prefer a narrow fix plus rerun of the affected gate over architectural changes. Keep active `dist/` limited to the current candidate and bind every result to its manifest/hash. If a mandatory environment is unavailable, preserve source results and report BLOCKED/PARTIAL with an exact continuation command/checkpoint rather than inventing success.

## FILES EXPECTED

- `scripts/build_release.py` only if a proven packaging defect requires a fix
- focused source/tests only for release-blocking defects
- ignored evidence under `.local/verification/`
- ignored candidate/archive outputs under `dist/` and `.local/archive/`
- `tasks/README.md`

## MINIMUM TESTS

1. `py -3.12 -m pytest -q`, `py -3.12 -m ruff check src tests`, and `py -3.12 -m mypy src tests` pass for the exact source identity.
2. Old database migration/backup/failure recovery/FK; lease/Attempt/Revision/locked recovery; and six-format parser/exporter/fidelity round trip pass.
3. Credential resolution/redaction/redirect, `.aiproject`/Open Directory path/hash/resource/staging/secret, and candidate hygiene checks pass.
4. The locally extracted Windows package contains resources, launches, completes the controlled V1 journey, handles Unicode/long/read-only/unwritable/network/model failure, and leaves external Project data after program-directory deletion.
5. Manifest and artifact hashes match actual outputs; rollback to the known candidate/ref is rehearsed without mutating the only user-data copy; review results are recorded truthfully.

A Windows file-symlink test that cannot run under the user's current privileges is an explicitly recorded coverage limitation, not PASS and not a reason to change system privileges. Mandatory local launch/journey, data recovery, credential isolation, and fidelity checks cannot be skipped.

## VALIDATION

- Full source quality gate plus every release gate in `docs/RELEASE.md`.
- Fresh candidate build and actual Windows package checks on the user's current computer only with explicit authorization; no clean OS or VM is required.
- Source review and actual local candidate acceptance for data, credential, and compatibility risks.

## ACCEPTANCE

- All mandatory gates pass for one fixed candidate identity, or the task reports BLOCKED/PARTIAL without calling the local candidate accepted.
- The candidate launches and completes the V1 journey on the user's current Windows computer.
- Artifacts contain required resources and no forbidden data; rollback/data-survival behavior is verified.
- Review results and any separately authorized signing/external-release actions are explicit and never inferred. Local acceptance is not a claim of public release.

## REGRESSION

Must preserve all T01–T05 contracts, historical migrations, old Project/container compatibility, credential isolation, six-format fidelity, recovery, i18n, and the three-page product surface.

## ROLLBACK / RECOVERY

Stop distribution, quarantine a failed candidate, retain its identity/evidence, and return to the last known artifact/ref. Preserve user Projects and pre-upgrade backups. Any post-release database correction uses a forward fix or verified copy restoration; never downgrade-write the sole user database.

## DELIVERABLES / DEFINITION OF DONE

- Candidate-bound quality, local GUI, data-safety, old-data compatibility, hygiene, review, and rollback evidence.
- If authorized, verified onedir/ZIP plus `build_manifest.json` and hashes in project-local output paths.
- Any release-blocking fix has focused regression coverage and all affected gates rerun.
- `tasks/README.md` marks T06 DONE only when every mandatory acceptance item passes; otherwise it records BLOCKED/PARTIAL truthfully and keeps the next action explicit.

## STOP CONDITION

Stop after the candidate is accepted or a real blocker is fully documented. Do not sign, tag, push, upload, publish, add features, or create V1-Full tasks without separate authorization/evidence.
