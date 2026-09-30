# T04 — Unified Translation workspace

STATUS:
See `tasks/README.md`.

MILESTONE:
M2 — Product Surface

---

## GOAL

Replace the Project plus Auto/Workbench translation journey with one user-facing Translation workspace backed only by the T03 facade.

## USER VALUE

The user can drag/import files, choose Provider/model/Prompt, translate, inspect context and errors, stop/resume, retry, edit/lock, manage Glossary/Notes, and export from one understandable page without learning internal Workflow/Attempt/Revision concepts.

## WHY NOW

The reliable core and facade must be complete first. This task creates the main V1 user journey and the replacement caller required before legacy upper-layer code can be removed safely.

---

## SIZE

XL — about 1–2 days

## RISK

HIGH — cross-module GUI integration and state transitions, but no new database contract.

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

Radar's Daily development pick is Astra MEDIUM at IQ 116, making it the current baseline for this broad but coherent UI/application slice. Escalate to HIGH only if the first run fails a user-journey or compatibility acceptance gate.

### MODEL RECHECK

YES — several high-risk core tasks precede it; quickly recheck current model reliability/cost before execution without changing scope.

## CAN DOWNGRADE MODEL

NO

---

## DEPENDS ON

T01, T02, T03

## BLOCKS

T05

---

## REQUIRED READING

### Always

- This task file

### Source files to inspect

- `src/transrealm/application/translation_facade.py` (expected T03 path; if T03 chose another focused name, inspect that actual facade module instead)
- `src/transrealm/ui/translation_page.py`
- `src/transrealm/ui/project_page.py`
- `src/transrealm/ui/worker.py`
- `src/transrealm/ui/page_base.py`
- `src/transrealm/ui/main_window.py`
- `src/transrealm/ui/i18n.py`
- `tests/test_v02_t04_m02.py`
- `tests/test_v02_t04_m03.py`
- `tests/test_v02_t04_m04.py`
- `tests/test_v02_t05_m02.py`

### Additional docs

- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`

---

## EXPECTED BASELINE

T01 provides persisted Notes, T02 provides versioned TXT segmentation, and T03 provides one facade for the complete reliable journey. Current UI still separates Project and Translation, displays Auto/Workbench modes, calls several services directly, and exposes Profile/Attempt/Revision-oriented concepts. Existing controls for import, progress, retry, history, manual revision, lock, Glossary, and export are working material to reuse rather than rewrite blindly.

## START REALITY CHECK

Confirm T01–T03 are DONE, facade tests pass, and the actual page/widget callers match the expected baseline. Run the closest current GUI journey tests before editing. Record FIT or ADAPT based on real widget structure; use REPLAN if the facade lacks an acceptance-critical operation rather than bypassing it with direct SQL/service access.

---

## CONTRACT

- Translation is one product page and the sole high-frequency workspace. Glossary and Notes live inside it, not in new top-level pages.
- Remove Auto/Workbench choices and product wording. Keep `projects.mode` readable for old databases but do not write it from the new UI or branch user behavior on it.
- The normal path is file import/drop → Provider/model selection → Prompt selection → Translate. A Job may contain multiple SourceDocuments.
- UI uses the T03 facade/read models; it does not access SQLite, Repository, or Provider directly.
- Show user concepts: files/segments, source, current translation, necessary Context, progress, and actionable errors. Hide Workflow, Attempt, Revision object jargon, lease/fencing, and internal Profile envelope terminology.
- Preserve one-target requests, locked output, safe Stop/Resume, failed-segment retry, manual edit/history selection, and fidelity export.
- GUI work and Provider/database calls stay off the main thread. Error text remains redacted.
- Main navigation restructuring to exactly Translation / Providers / Prompts is completed in T05; during T04 keep the shell minimally operable without inventing a fourth destination.

## IN SCOPE

- Build one Translation workspace containing Job/file controls, multi-document selection, segment list/status/filter, source/current translation, necessary context preview, progress/errors, translate/stop/resume/retry, manual edit/history/lock, Glossary, Notes, and export.
- Reuse/adapt current ProjectPage and TranslationPage code behind one facade-driven page; remove the visible mode switch and active mode branches.
- Make Provider/model/Prompt selectors usable on the workspace while T05 owns their management pages.
- Support drag/drop and normal file chooser for the six formats, plus empty/loading/running/stopped/failed/completed states.
- Update translations/resources and focused GUI tests for English and Simplified Chinese.

## OUT OF SCOPE

- Provider connection CRUD and Prompt template management page redesign; T05 owns them.
- Deleting compatibility schema/services, Workflow/Profile persistence, `.aiproject`, Open Directory, parsers, or exporter internals.
- History Retrieval, full-text search, batch multi-select retranslation, terminology suggestions, layout persistence, plugin APIs, or visual redesign beyond usability.
- Candidate packaging or release signoff.

## IMPLEMENTATION TARGET

Prefer composing existing proven widgets/behaviors into one page over a ground-up GUI framework. It is acceptable to split the 1,200-line current page into responsibility-focused UI modules when that directly reduces risk, but do not create a generic component system. Preserve stable object names only where they protect real tests/integrations; update stale tests that assert retired product concepts and retain equivalent behavioral coverage.

## FILES EXPECTED

- `src/transrealm/ui/translation_page.py` and small focused UI modules if needed
- `src/transrealm/ui/project_page.py` or its retired/absorbed replacement path
- `src/transrealm/ui/worker.py`
- `src/transrealm/ui/main_window.py`
- `src/transrealm/ui/i18n/`
- focused Qt/integration tests under `tests/`

## MINIMUM TESTS

1. New-user journey with a controlled endpoint: create/open Job, import at least two files, select Provider/model/Prompt, translate, stop, close/reopen, resume, edit/lock, and fidelity-export.
2. Locked Segment is not auto-overwritten; failed Segment can be retried; missing Provider/model/Prompt and Provider/format errors are actionable and redacted.
3. Glossary and Notes persist, enter later requests, and do not create extra target Revisions.
4. Old Project with `auto` or `workbench` mode opens into the same workspace with no mode selector or data loss.
5. English and Simplified Chinese at representative Windows 11 scale/DPI show no clipped controls, overlap, dead focus path, or unusable empty/error/disabled state; evidence stays under `D:/TransRealm/.local/verification/`.

## VALIDATION

- Targeted facade/UI tests and controlled-endpoint smoke journey.
- Milestone regression for Project/import, six-format export, Stop/Resume/recovery, manual Revision/lock, Glossary/Notes, i18n, and safe errors.
- Actual GUI launch and operation; full pytest, Ruff, and mypy because this replaces broad callers.

## ACCEPTANCE

- The complete high-frequency journey works from one Translation page without Auto/Workbench or internal data-model jargon.
- All Translation operations pass through the facade and remain responsive/recoverable.
- Old Project modes open safely, six-format behavior is preserved, and GUI evidence covers both supported languages.
- No V1-Full or out-of-scope architecture was added.

## REGRESSION

Must preserve all reliable-core, Provider capability, credential, PromptOverride, parser/exporter, archive/open-directory, i18n, and worker-shutdown protections.

## ROLLBACK / RECOVERY

Keep replacement changes reversible at the upper layer and do not delete compatibility storage. If the new page cannot complete an operation, retain the last working facade-based widget path while reporting the blocker; do not fall back to direct SQLite or expose the old mode switch as a shortcut.

## DELIVERABLES / DEFINITION OF DONE

- One facade-driven Translation workspace and updated i18n resources.
- Focused GUI/integration tests plus project-local visual/smoke evidence.
- Old mode values remain readable without an active mode UI path.
- `tasks/README.md` marks T04 DONE and recommends T05; no completion appendix added here.

## STOP CONDITION

Stop when the unified workspace acceptance passes. Do not redesign Providers/Prompts, delete compatibility core, add V1-Full features, or begin release packaging.
