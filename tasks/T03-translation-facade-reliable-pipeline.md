# T03 — Translation facade and reliable single-segment pipeline

STATUS:
See `tasks/README.md`.

MILESTONE:
M1 — Reliable Product Core

---

## GOAL

Expose Job/import/export/read/edit/lock/start/stop/resume/retry through one product-facing Translation facade and close the remaining context-overflow and cancellation gaps without rewriting the reliable core.

## USER VALUE

The future Translation page gets one coherent, restart-safe API: each request translates exactly one Segment, progress survives failure/restart, and Stop/Resume or a Provider context overflow never corrupts Attempts or locked work.

## WHY NOW

The current UI opens several services directly and still branches between Auto and Workbench. A narrow facade and complete request lifecycle must exist before T04 can replace those callers safely.

---

## SIZE

XL — about 1–2 days

## RISK

CRITICAL — Attempt identity, lease/fencing, cancellation, overflow rebuilding, Revision locks, and crash recovery.

## RECOMMENDED MODEL

### CAPABILITY LEVEL

LEVEL 4 — Flagship Reasoning

### PREFERRED MODEL

`gpt-6-astra`

### FALLBACK MODEL

`gpt-5.6-sol` with XHIGH thinking

### THINKING

MEDIUM

### WHY

This remains an L4 concurrency/audit task, but Radar's hard-problem station pick measures Astra MEDIUM and HIGH at the same IQ with lower measured time/cost for MEDIUM. Escalate to HIGH only after a concrete acceptance failure, without weakening the fencing contract.

### MODEL RECHECK

NO — T03 follows the immediate core tasks and clearly requires flagship reasoning.

## CAN DOWNGRADE MODEL

NO

---

## DEPENDS ON

T01

## BLOCKS

T04

---

## REQUIRED READING

### Always

- This task file

### Source files to inspect

- `src/transrealm/application/translation_service.py`
- `src/transrealm/application/translation_run_service.py`
- `src/transrealm/application/import_service.py`
- `src/transrealm/application/exporter.py`
- `src/transrealm/application/project_service.py`
- `src/transrealm/ui/worker.py`
- `src/transrealm/adapters/errors.py`
- `src/transrealm/adapters/openai_adapter.py`
- `src/transrealm/infrastructure/repositories/segment_attempt_repository.py`
- `tests/test_p0_t07_m04.py`
- `tests/test_p0_t07_m05.py`
- `tests/test_p0_t08_m01.py`
- `tests/test_p1_t03_m04.py`

### Additional docs

- `docs/ARCHITECTURE.md`
- `docs/DATABASE.md`

---

## EXPECTED BASELINE

The repository already has a no-UI `TranslationService`, atomic claim/finalize, Attempt/Revision history, lease/fencing recovery, user Revision/lock operations, six-format import/export, Project active Profile, Glossary, T01 Notes, and a worker that translates pending Segments sequentially. Current gaps include multiple UI service entry points, Auto/Workbench branches, boundary-only Stop behavior, and no explicit Provider-overflow policy that terminates the old Attempt and rebuilds a reduced semantic request as a new Attempt.

## START REALITY CHECK

Verify T01 is DONE and its Notes snapshot is available. Run the focused claim/finalize/recovery/lock and existing translation-service tests. Map actual UI callers, but do not edit UI pages in this task except the worker seam required to exercise the facade. If fixing a gap requires changing published schema, Project format, or public product behavior beyond this contract, stop and report `REPLAN`.

---

## CONTRACT

- One Provider request has exactly one target Segment. Neighbor, Glossary, Notes, and future History are context only and cannot create Revisions in that call.
- Every change to target, Prompt, Context, Notes, template, or semantic parameters creates a new Attempt with a new audit snapshot. Only bounded transport retry or explicitly equivalent protocol degradation may stay in one Attempt.
- Provider context overflow may rebuild a deterministically smaller Context only after the current Attempt is finalized safely; the rebuilt request is a new Attempt with its own `prompt_hash` and context summary. Retry is bounded and target/fixed protected content is never silently truncated.
- Success atomically appends Revision, selects current, updates Segment/version, clears lease, and completes Attempt. Owner/version/expiry fencing remains mandatory for success, failure, and cancel.
- Automatic translation never replaces a locked current Revision. Manual edits append user Revisions; history is never overwritten.
- Stop must converge safely. If an in-flight call cannot be interrupted without weakening the adapter contract, finish/cancel it according to explicit tested semantics and stop before claiming another Segment; never kill a thread or abandon an untracked lease.
- Resume recovers only expired/safe work and preserves completed or locked output. Idempotency keys remain unique.
- The facade wraps existing services/repositories; it does not duplicate or rewrite the reliable core.

## IN SCOPE

- Add a narrow Translation facade/read model API for current Job/Project, SourceDocuments, Segments/progress, active Provider/model/template, Glossary/Notes, import/export, start/stop/resume, failed-segment retry, manual edit, revision selection, lock/unlock, and safe errors.
- Route the translation worker through the facade or an equally narrow application boundary and remove its need to assemble unrelated services.
- Classify Provider context overflow sufficiently to drive bounded context reduction and a new Attempt.
- Make Stop/Resume behavior explicit, persisted, and covered at request, segment, run, restart, and locked-current boundaries.
- Preserve fixed builtin Workflow as internal Run compatibility metadata without exposing Workflow as a product concept.

## OUT OF SCOPE

- New Translation/Providers/Prompts widgets or navigation; T04/T05 own UI.
- Deleting legacy service classes, Workflow/Profile tables, `projects.mode`, migrations, or compatibility imports.
- Multi-segment requests, automatic model routing, parallel translation, History Retrieval, plugins, model runtime/download management, or a general command bus.
- Broad repository or async-framework rewrites.

## IMPLEMENTATION TARGET

Prefer a thin facade composed from existing services and immutable/plain read models. Keep SQLite and Provider work off the Qt main thread. The facade should be usable by tests without Qt and should make invalid state transitions fail closed with safe actionable messages. Add only the adapter error detail needed to distinguish overflow; never expose raw response bodies, Authorization, credentials, or unrelated Provider text.

## FILES EXPECTED

- a focused facade/read-model module under `src/transrealm/application/`
- `src/transrealm/application/translation_service.py`
- `src/transrealm/application/translation_run_service.py`
- `src/transrealm/adapters/errors.py` and minimal adapter classification code
- `src/transrealm/ui/worker.py`
- focused tests under `tests/`

## MINIMUM TESTS

1. Facade journey: open/create Job, import multiple SourceDocuments, expose progress/read models, translate one Segment per request, edit/select/lock Revision, export, close/reopen, and resume pending work.
2. Context overflow finalizes the old Attempt, deterministically prunes optional/far context, creates a new Attempt with different semantic audit/hash, remains bounded, and never truncates the target or protected fixed input.
3. Stop before claim, during an in-flight call, and between Segments leaves explicit Run/Attempt/Segment states; restart/recovery is idempotent and does not duplicate a Revision.
4. Stale/late worker, wrong owner/version, expired lease, locked current Revision, and concurrent current change are fenced exactly as before.
5. Adapter/credential errors remain redacted and actionable; transport retry retains the same Attempt only when the semantic request is unchanged.

## VALIDATION

- Targeted facade, adapter error, worker, translation service, Attempt/Revision, lease/fencing, lock, cancellation, and recovery tests.
- Milestone regression covering import → translate → stop/restart/resume → manual edit/lock → export with a controlled compatible endpoint.
- Full pytest because the facade touches shared application flow; Ruff and mypy.

## ACCEPTANCE

- A Qt-free integration test completes the full facade journey and proves one-request/one-target behavior.
- Overflow, Stop/Resume, crash recovery, and locked Revision paths have explicit passing evidence.
- Worker/application callers can use the new boundary without an Auto/Workbench semantic fork.
- Reliable core, credentials, Workflow compatibility, archives, and format fidelity remain intact.

## REGRESSION

Must preserve Profile capability filtering, PromptOverride stale fail-closed, glossary/Notes context order, transport retry bounds, migration behavior, archive/open-directory compatibility, and all existing recovery/fidelity matrices.

## ROLLBACK / RECOVERY

The facade is additive until T04 replaces UI callers, so rollback should remove the new caller path without deleting core data. Do not add a schema migration unless an unavoidable missing audit field is proven and separately reconciled with T01/current schema; never weaken fencing to simplify rollback.

## DELIVERABLES / DEFINITION OF DONE

- Product-facing Translation facade/read models and worker integration.
- Bounded overflow rebuild plus tested Stop/Resume/recovery semantics.
- Focused and milestone regression evidence.
- `tasks/README.md` marks T03 DONE and recommends the next remaining core task or T04; no separate handoff artifact.

## STOP CONDITION

Stop when the facade and pipeline acceptance pass. Do not redesign the UI, delete legacy callers, add parallelism, or begin T04.
