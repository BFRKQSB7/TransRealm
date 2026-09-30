# T05 — Providers, Prompts, and three-page navigation

STATUS:
See `tasks/README.md`.

MILESTONE:
M2 — Product Surface

---

## GOAL

Finish the Product Reset surface as exactly Translation / Providers / Prompts, preserve capability-driven configuration and prompt inheritance, and remove now-unreferenced old upper-layer Auto/Workbench/Project UI code.

## USER VALUE

The app has three clear destinations: do translation, configure local/online compatible endpoints and models, or manage prompt templates—without Workflow/Profile jargon or duplicate settings paths.

## WHY NOW

T04 supplies the replacement Translation caller. Only now can navigation and obsolete upper-layer callers be removed without risking a feature gap or confusing dual product models.

---

## SIZE

L — about 0.5–1.5 days

## RISK

HIGH — caller removal, Provider/Prompt configuration compatibility, i18n, and credential-safe UI behavior.

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

Most mechanics exist, but caller removal still needs compatibility judgment. Radar's Daily development pick favors Astra MEDIUM; escalate to HIGH only if the first run cannot prove the caller/compatibility boundary.

### MODEL RECHECK

YES — this task is several steps away and current model cost/reliability may change.

## CAN DOWNGRADE MODEL

YES

Minimum recommended capability level: LEVEL 2, only if T04 left clean facade boundaries and the work is demonstrably mechanical after Reality Check.

---

## DEPENDS ON

T04

## BLOCKS

T06

---

## REQUIRED READING

### Always

- This task file

### Source files to inspect

- `src/transrealm/ui/main_window.py`
- `src/transrealm/ui/settings_page.py`
- `src/transrealm/ui/translation_page.py`
- `src/transrealm/ui/project_page.py`
- `src/transrealm/ui/pages.py`
- `src/transrealm/ui/workbench.py`
- `src/transrealm/application/provider_connection_service.py`
- `src/transrealm/application/model_profile_service.py`
- `src/transrealm/application/preset_templates.py`
- `src/transrealm/application/adapter_factory.py`
- `tests/test_v02_t01_m02.py`
- `tests/test_v02_t03_m01.py`
- `tests/test_v02_t03_m02.py`

### Additional docs

- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`

---

## EXPECTED BASELINE

T04 supplies the unified Translation page and its Provider/model/Prompt selectors. Current Settings combines connection and ModelProfile CRUD; PromptOverride editing and Workbench parameter controls may still live in translation-related modules. The schema and services still need ModelProfile, PromptOverride, builtin Workflow, active profile, and legacy `projects.mode` for compatibility even though the new product language hides them.

## START REALITY CHECK

Confirm T04 is DONE and search all real callers before deleting anything. Run Provider/Profile/PromptOverride, credential, shell/i18n, and T04 journey tests. Treat a class/module as removable only if it has no UI caller, no compatibility/API caller, and no data interpretation responsibility. If that proof fails, retain it behind the new surface rather than forcing cleanup.

---

## CONTRACT

- Main navigation has exactly three pages in this order: Translation, Providers, Prompts. Glossary and Notes remain inside Translation.
- Providers manages OpenAI-compatible connections plus model/capability-driven parameters. Local and online endpoints share the same narrow model; TransRealm does not download/run models or manage GPU/runtime.
- Credentials remain references (`env:`/`wincred:`), never secret plaintext in SQLite, widgets after save, logs, errors, screenshots, archives, or tests.
- Prompts supports preset viewing and copy/edit/rename/delete behavior using the existing version/override contract. Stale overrides fail closed; no executable template language or general DSL.
- UI may say Provider, Model, and Prompt. It must not expose Workflow, ModelProfile envelope, Auto, or Workbench as product concepts.
- Do not delete `projects.mode`, Workflow tables/FKs/snapshots, ModelProfile fields/FKs, PromptOverride history semantics, builtin Workflow seed, or legacy project/container compatibility.
- Removal is limited to proven dead upper-layer callers and compatibility reexports that no supported caller needs.

## IN SCOPE

- Split/adapt Settings into a Providers page and a Prompts page using existing services and T03/T04 boundaries.
- Finish shell navigation, cross-page setup links, i18n, first-use guidance, safe errors, capability-specific parameter editing, and prompt selection refresh.
- Remove or reduce obsolete Project/Auto/Workbench widgets and direct callers only after replacement coverage exists.
- Update tests that asserted retired labels/layout while retaining behavioral/data compatibility coverage.

## OUT OF SCOPE

- Schema cleanup, migration deletion, ModelProfile table splitting, Workflow editor, plugin API, model discovery/download/runtime, automatic model routing, or Provider-specific SDKs.
- New prompt DSL, cloud prompt marketplace, History Retrieval, broad theme redesign, or release packaging.
- Removing legacy `.aiproject`/Open Directory behavior.

## IMPLEMENTATION TARGET

Reuse existing connection/profile/override services and capability widgets. Rename/recompose only the user-facing surface needed for the three-page model. Deletion should follow a caller search plus focused regression, not a filename-based assumption; leaving a small internal compatibility module is preferable to breaking old Projects.

## FILES EXPECTED

- `src/transrealm/ui/main_window.py`
- `src/transrealm/ui/settings_page.py` or new narrow `providers_page.py` / `prompts_page.py`
- `src/transrealm/ui/pages.py`
- `src/transrealm/ui/workbench.py` and old page modules only where caller proof permits
- `src/transrealm/ui/i18n/`
- focused tests under `tests/`

## MINIMUM TESTS

1. Shell contains exactly Translation / Providers / Prompts in English and Simplified Chinese; setup links navigate to the correct destination.
2. Provider/Model create/edit/delete and capability-driven parameter behavior still compose a real adapter; unsupported parameters are not sent.
3. Credential references save/resolve safely, UI/errors/screenshots never reveal secret text, and cross-origin or HTTPS-downgrade redirect protections remain green.
4. Prompt preset copy/edit/rename/delete/select works; stale parent version fails closed and historical Attempts remain explainable.
5. Old Project/archive with legacy mode/Profile/Workflow/PromptOverride opens and translates through the new surface; removed UI modules have no remaining supported callers.

## VALIDATION

- Targeted shell, Providers, Prompts, capability, credential, PromptOverride, and compatibility tests.
- Actual three-page GUI smoke in both languages and representative DPI, with project-local evidence.
- T04 end-to-end journey plus full pytest, Ruff, and mypy.

## ACCEPTANCE

- Navigation and terminology match the three-page product definition.
- Provider/model and Prompt workflows remain complete, capability-driven, and credential-safe.
- Auto/Workbench/Project product paths have no visible caller; only proven-dead upper-layer code is removed.
- Legacy database/container interpretation and reliable translation behavior remain intact.

## REGRESSION

Must preserve active Profile resolution, PromptOverride versioning, adapter capabilities, credentials/redirect safety, builtin Workflow Run snapshots, old mode reads, Translation journey, i18n, archives, and all T04 behavior.

## ROLLBACK / RECOVERY

Because schema is untouched, rollback is limited to upper-layer composition. If a removed caller proves required, restore the smallest internal compatibility path without restoring retired product navigation. Never recover by reintroducing plaintext credentials or editing historical migrations.

## DELIVERABLES / DEFINITION OF DONE

- Exactly three product pages with complete Providers and Prompts workflows.
- Proven-dead old UI callers removed or isolated without touching compatibility storage.
- Focused/full validation and GUI evidence.
- `tasks/README.md` marks T05 DONE and recommends T06; this packet remains static.

## STOP CONDITION

Stop when the three-page surface and compatibility acceptance pass. Do not clean core schema/services, add Provider ecosystems, implement V1-Full, or build a release candidate.
