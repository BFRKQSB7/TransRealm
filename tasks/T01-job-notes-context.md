# T01 — Job Notes persistence and context integration

STATUS:
See `tasks/README.md`.

MILESTONE:
M1 — Reliable Product Core

---

## GOAL

Add a small, append-only Job Notes data path and inject its persisted content into every applicable single-segment prompt with deterministic budgeting and audit metadata.

## USER VALUE

The user can save project/job-level translation guidance once and have it consistently applied to later segment translations without copying it into every request.

## WHY NOW

Notes is the only V1-Release context source with no persisted implementation. T03 needs a real Notes contract before it can expose one coherent translation facade.

---

## SIZE

L — about 0.5–1.5 days

## RISK

HIGH — additive migration plus prompt/context semantics; no destructive migration is allowed.

## RECOMMENDED MODEL

### CAPABILITY LEVEL

LEVEL 3 — Strong Coding / Reasoning

### PREFERRED MODEL

`gpt-5.6-sol`

### FALLBACK MODEL

`gpt-6-astra`

### THINKING

MEDIUM

### WHY

Radar's current Sol MEDIUM community score is stronger than Sol HIGH while this task remains a compact L3 slice. Keep the migration/context contract strict; escalate to HIGH only if the first implementation fails an acceptance test.

### MODEL RECHECK

NO — this is the immediate recommended task and the capability fit is clear.

## CAN DOWNGRADE MODEL

NO

---

## DEPENDS ON

NONE

## BLOCKS

T03, T04

---

## REQUIRED READING

### Always

- This task file

### Source files to inspect

- `src/transrealm/migrations/`
- `src/transrealm/application/context.py`
- `src/transrealm/application/context_composer.py`
- `src/transrealm/application/prompt_renderer.py`
- `src/transrealm/application/translation_service.py`
- `src/transrealm/infrastructure/repositories/glossary_entry_repository.py`
- `tests/test_migrations.py`
- `tests/test_p0_t05_m02.py`
- `tests/test_p1_t04_m03.py`

### Additional docs

- `docs/DATABASE.md`
- `docs/ARCHITECTURE.md`

---

## EXPECTED BASELINE

Migrations `001`–`012` exist and are immutable. Glossary is project-scoped and only locked entries enter context. `ContextComposer` currently handles target plus Glossary and Neighbor candidates; `PromptRenderer` already exposes a `notes` placeholder, but there is no persisted Job Notes table/service path. In this V1, the existing Project row is the persisted Job envelope; do not introduce a second top-level Job aggregate merely for naming purity.

## START REALITY CHECK

Before editing, confirm the migration sequence still ends at `012`, Notes still lacks a real persistence path, and T01 is claimable in `tasks/README.md`. Run the closest existing migration/context/prompt tests once. If another Notes migration or incompatible contract already exists, stop and report `REPLAN`; otherwise adapt internal names without changing the contract below.

---

## CONTRACT

- Never edit, reorder, delete, or reuse an existing migration. Use the next free migration number discovered at task start.
- Persist one Notes text value per Project/Job, with clear update semantics and project-delete cascade. Blank content means no Notes context; do not create a second source of truth in settings or files.
- Notes is user-authored Project data. It must survive restart, SQLite backup, `.aiproject`, and Open Directory naturally through the project database.
- Context selection order remains deterministic. Target and fixed prompt overhead are mandatory; locked Glossary and non-empty Notes are protected ahead of optional/far Neighbor content.
- A Notes change changes semantic input. A later call must produce a new Attempt and corresponding `prompt_hash`/context audit; never mutate historical Attempt snapshots.
- Notes must not be logged as an error payload or mixed with credentials. No secrets, attachments, rich text, per-segment notes, or version-history subsystem.

## IN SCOPE

- Add the append-only Notes migration, domain/repository/application access, and focused tests.
- Load Notes for translation, represent it in the context manifest or equivalent deterministic input, render it through the existing `notes` placeholder, and include a safe presence/size/hash-style audit summary rather than raw text where appropriate.
- Define stable behavior for create, read, update, clear, restart, project deletion, and empty/oversized Notes.
- Preserve migration backup, rollback, foreign-key, and reopen behavior.

## OUT OF SCOPE

- Translation-page controls; T04 owns the user interface.
- History Retrieval, embeddings, vector stores, attachments, Markdown rendering, collaboration, or cloud sync.
- Editing existing migrations or changing Project/archive formats outside the normal SQLite snapshot.
- Refactoring Glossary, Provider, Profile, PromptOverride, or the reliable core.

## IMPLEMENTATION TARGET

Use the smallest repository/service shape consistent with existing code. A one-row-per-project table such as `project_notes` is expected, but exact class names are not contractual. Translation must read a stable Notes snapshot before claiming the Attempt, include it in deterministic budget/rendering, and leave historical Attempts explainable when Notes changes later.

## FILES EXPECTED

- `src/transrealm/migrations/<next>_add_project_notes.sql`
- `src/transrealm/domain/` and/or a small Notes value type
- `src/transrealm/infrastructure/repositories/`
- `src/transrealm/application/context.py`
- `src/transrealm/application/context_composer.py`
- `src/transrealm/application/prompt_renderer.py`
- `src/transrealm/application/translation_service.py`
- focused tests under `tests/`

These are expected areas, not permission to clean adjacent modules.

## MINIMUM TESTS

1. A real `001`–`012` database upgrades through the new migration, creates a verified pre-upgrade backup, preserves existing rows, enables foreign keys, reopens, and rolls back cleanly on injected migration failure.
2. Notes create/update/clear/reopen is project-scoped; deleting a Project removes its Notes without affecting another Project.
3. Non-empty Notes appears in the rendered prompt and audit summary; empty Notes does not add phantom content.
4. Under a tight budget, protected target/Glossary/Notes behavior is deterministic and farther Neighbor content is pruned first; impossible protected input fails before a Provider request or Attempt claim.
5. Changing Notes changes the next semantic request/Attempt but does not rewrite prior Attempt snapshots or Revisions.

## VALIDATION

- Targeted migration, Notes repository/service, context composer, prompt renderer, and translation service tests.
- Existing migration, Glossary/context, prompt, Attempt/Revision, archive, and Open Directory milestone regressions affected by the new table.
- Full pytest because migration discovery is shared infrastructure; Ruff and mypy for changed Python/tests.

## ACCEPTANCE

- The persisted Notes lifecycle and project scope work after restart.
- Translation uses Notes deterministically without violating single-target or Attempt audit rules.
- Existing databases upgrade safely and archives/open directories retain Notes through their existing SQLite path.
- No historical migration changed, no raw secret or unnecessary raw Notes is introduced into logs/errors, and all required validation passes.

## REGRESSION

Must preserve six-format fidelity, locked Glossary ordering, PromptOverride stale fail-closed behavior, single-target requests, migration backup/checksum behavior, and Project/archive compatibility.

## ROLLBACK / RECOVERY

Do not down-migrate user data. If implementation fails before release, revert the new code and use a forward corrective migration if a test or development database has already applied the new schema. Preserve the pre-upgrade backup and document any partially applied local fixture; migration transactions must prevent a half-created schema.

## DELIVERABLES / DEFINITION OF DONE

- Additive migration and minimal Notes domain/repository/application path.
- Translation/context integration with audit-safe behavior.
- Focused tests plus required regression results.
- `tasks/README.md` updated to mark T01 DONE and identify the next task; no handoff file or completion log added to this packet.

## STOP CONDITION

Stop immediately when ACCEPTANCE is satisfied. Do not add the Notes UI, History Retrieval, rich text, general context-source abstractions, or begin T03/T04.
