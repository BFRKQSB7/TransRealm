# Execution Index

Current milestone: M4 — Local UI and workflow polish

Planning basis: current `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/DEVELOPMENT.md`, `docs/RELEASE.md`, and the code/schema/tests present when these packets were written. Historical material under `docs/archive/` is not an execution source.

Model allocation last rechecked against Codex Radar on 2026-09-20. Radar's current hard-problem data makes GPT-6 Astra MEDIUM the baseline; HIGH is an escalation after an acceptance failure, not a task-risk downgrade.

| Task | Title | Status | Size | Model | Thinking | Depends |
|---|---|---:|---:|---:|---:|---|
| [T01](T01-job-notes-context.md) | Job Notes persistence and context integration | DONE | L | L3 / `gpt-5.6-sol` | MEDIUM | - |
| [T02](T02-versioned-txt-segmentation.md) | Versioned format-aware TXT segmentation | DONE | XL | L4 / `gpt-6-astra` | MEDIUM | - |
| [T03](T03-translation-facade-reliable-pipeline.md) | Translation facade and reliable single-segment pipeline | DONE | XL | L4 / `gpt-6-astra` | MEDIUM | T01 |
| [T04](T04-unified-translation-workspace.md) | Unified Translation workspace | DONE | XL | L3 / `gpt-6-astra` | MEDIUM | T01, T02, T03 |
| [T05](T05-providers-prompts-navigation.md) | Providers, Prompts, and three-page navigation | DONE | L | L3 / `gpt-6-astra` | MEDIUM | T04 |
| [T06](T06-v1-release-candidate.md) | V1 regression and local Windows EXE/ZIP candidate | DONE | L | L3 / `gpt-6-astra` | MEDIUM | T05 |
| [T07](T07-ui-workflow-polish.md) | Desktop UI and workflow polish | DONE | L | Current session | Current session | T06 |
| [T08](T08-application-icon.md) | Application icon and Windows integration | IN_PROGRESS | S | Current session | Current session | T07 |

Recommended next action: **Finish T08's user-requested icon redesign and rebuild the local candidate**. The abstract speech-page mark was rejected; replace it with explicit A / 文 speech bubbles. Integration code is already accepted; this follow-up changes only icon assets and design/task records. Revised evidence belongs under `.local/verification/t08-icon-v2/`; preserve source-first packaging, previous candidates and project-local simulated acceptance. AV and clean-machine requirements remain outside scope; the symbol-link privilege limitation remains recorded.

## Milestones

- **M1 — Reliable Product Core:** T01–T03. Add the missing Notes contract, version TXT mapping safely, and expose the existing reliable core through one product-facing facade/pipeline.
- **M2 — Product Surface:** T04–T05. Replace Auto/Workbench and Settings/Project product concepts with Translation / Providers / Prompts while preserving legacy data compatibility.
- **M3 — V1 Local Acceptance:** T06. Run the regression, build the authorized Windows EXE/ZIP candidate, and record evidence from actual acceptance on the user's current computer.
- **M4 — Local UI and workflow polish:** T07–T08. Refine the desktop layout and interaction using real-use feedback, add the application icon, then rebuild and accept the local candidate.

## Dependency Graph

```text
T01 ──→ T03 ──┐
  │            ├──→ T04 ──→ T05 ──→ T06 ──→ T07 ──→ T08
  └────────────┘
T02 ───────────┘
```

This graph contains only code or contract dependencies. Suggested ordering is controlled by **Recommended next task**, not by adding artificial edges.

## State Rules

- This file is the only task status source. Task packets are static execution contracts and do not receive completion logs or handoffs.
- Claim and execute one task at a time. Change a task to `IN_PROGRESS` only when work actually starts; use `DONE` only after its acceptance and validation pass.
- After completion, update only this table and **Recommended next task**. Report changed files, validation, known issues, new risks, and the next recommendation in the final response.
- `UNKNOWN`, unavailable, skipped, or not run is never equivalent to passed. If code/schema differs materially from a packet, stop the conflicting part and report `REPLAN` rather than silently widening scope.
- V1-Full History Retrieval, debug views, search, batch retranslate, suggestions, statistics, and layout persistence are intentionally not activated. Create later packets only after T06 and real-use evidence satisfy `docs/PRODUCT.md`; do not pull them into these tasks.

## Planning Summary

- **Total tasks:** 8
- **Critical path:** T01 → T03 → T04 → T05 → T06 → T07 → T08; T02 must also finish before T04.
- **Level 4:** T02, T03.
- **Level 3:** T01, T04, T05, T06.
- **Estimated development range:** about 7–11 focused working days for a strong agent, excluding external endpoint availability, independent review scheduling, signing, and release authorization.
