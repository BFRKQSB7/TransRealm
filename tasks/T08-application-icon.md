# T08 — Application icon

## Scope

Generate an original icon for TransRealm / 译境, matching the rounded monochrome UI. Integrate it in the sidebar, window/application icon and Windows EXE. Keep the generated PNG and a multi-resolution ICO in `src/transrealm/ui/assets/`; record the generation prompt in `docs/design/app-icon.md`.

## Implementation boundary

Use native Qt icon support and the existing PyInstaller build. Include the runtime icon in the bundle and verify its identity. Source changes are limited to UI icon wiring, asset conversion, packaging verification, assets and task/design documentation. No new runtime dependencies or changes to user data and translation behavior.

## Acceptance and recovery

Inspect small icon sizes and native English/Chinese windows at 100%/150% scale. Follow `docs/RELEASE.md` for full quality checks and committed-source packaging. Verify icon resources in the actual EXE, window icon, ZIP startup and the existing controlled core journey. Use project-local simulated inputs without file choosers. Archive the prior candidate, verify rollback on independent data, and record candidate-bound results under `.local/verification/t08-icon/`.

Task status exists only in `tasks/README.md`. All controlled outputs stay within `D:/TransRealm/`; the built-in image tool's returned image is copied into the project before use. Local-only acceptance applies; no AV, clean-machine, publication or signing gate.
