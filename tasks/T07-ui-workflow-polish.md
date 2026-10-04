# T07 — Desktop UI and workflow polish

## Scope

User-authorized on 2026-10-04: modernize the desktop UI in a restrained Codex-like style and improve the operating flow. Preserve Translation / Providers / Prompts, native Qt, existing application services, credential isolation, six-format fidelity and local-only acceptance.

## Delivery

- Fixed sidebar, restrained light theme, compact controls, readable segment previews, source and translation beside the segment list, and visible retry/retranslate actions.
- Clear empty/configuration states, provider-to-model setup progression, return-to-translation links, truthful idle progress, and preservation of manual drafts while switching segments/documents within the current window.
- Meaningful workflow regressions and native Windows visual checks in English and Chinese, including a small window and scaled display. Simulate imports and endpoint responses with isolated project-local fixtures; avoid interactive file choosers during acceptance.
- Commit reviewed source before building a clean local EXE/ZIP; archive the previous candidate and verify the new artifact. No AV scan, clean-Windows/VM gate, push or public publication.

## Source boundary

`src/transrealm/ui/`, UI tests and translation resources. This changes presentation and interaction, not schema, adapter protocols, model capabilities or the translation pipeline. Read `docs/PRODUCT.md` and `docs/DEVELOPMENT.md` by risk.

## Risk and recovery

The main risks are stale asynchronous reads, accidental loss of unsaved text, and clipped controls. Preserve actual terminal errors, distinguish a clean editor from a manual draft, suppress stale refreshes, and verify native small-window layouts. Drafts are retained in the current window, not persisted as revisions until Save; closing with unsaved changes must offer cancellation. Restore the archived T06 application folder to roll back this UI; there is no schema change and no authorization to overwrite user data.

## Acceptance

Import → configure/select model → translate → stop/resume → edit/save/lock → retry/retranslate → export remains usable. Unsaved text survives in-window navigation; a clean editor displays newly persisted AI output after refresh. Task status exists only in `tasks/README.md`. Evidence and artifacts stay under `D:/TransRealm/`.

Completion requires source review, full regression and quality checks, native English/Chinese checks at 100%/150% scale, a clean committed-source build, and actual frozen startup/core-flow acceptance with a candidate-bound report.
