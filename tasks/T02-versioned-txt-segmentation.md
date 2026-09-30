# T02 — Versioned format-aware TXT segmentation

STATUS:
See `tasks/README.md`.

MILESTONE:
M1 — Reliable Product Core

---

## GOAL

Replace new TXT imports' one-nonempty-line mapping with a deterministic, versioned, format-aware segmentation algorithm while preserving byte-accurate export and all existing document/revision identities.

## USER VALUE

Novel, game-script, and general text imports produce translation-sized units with useful paragraph/dialogue boundaries, without corrupting whitespace, encoding, line endings, or previously translated documents.

## WHY NOW

Smart TXT segmentation is a V1-Release quality requirement and a high-risk identity/fidelity boundary. It must be stable before the unified workspace promises production import behavior.

---

## SIZE

XL — about 1–2 days

## RISK

CRITICAL — parser identity, stable Segment mapping, raw byte spans, exporter fidelity, and old-project compatibility.

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

This remains an L4 parser/fidelity task, but Radar's hard-problem station pick measures Astra MEDIUM and HIGH at the same IQ while MEDIUM is faster and cheaper. Start at MEDIUM and escalate to HIGH only if the first run misses an identity or round-trip acceptance gate.

### MODEL RECHECK

NO — this task is immediately claimable and its risk profile clearly warrants the flagship model.

## CAN DOWNGRADE MODEL

NO

---

## DEPENDS ON

NONE

## BLOCKS

T04

---

## REQUIRED READING

### Always

- This task file

### Source files to inspect

- `src/transrealm/infrastructure/parsers/txt_parser.py`
- `src/transrealm/infrastructure/fidelity.py`
- `src/transrealm/application/import_service.py`
- `src/transrealm/application/exporter.py`
- `src/transrealm/domain/segment.py`
- `src/transrealm/infrastructure/repositories/segment_repository.py`
- `tests/test_txt_parser.py`
- `tests/test_p1_t01_m01.py`
- `tests/test_p1_t03_m05.py`

### Additional docs

- `docs/ARCHITECTURE.md`
- `docs/DATABASE.md`

---

## EXPECTED BASELINE

`TxtParser` version `1.0.0` creates one Segment per stripped non-empty line and stores byte spans in versioned fidelity metadata. SourceDocument reuse already includes source hash, format, and parser version. Exporter replaces verified spans and preserves non-target bytes. JSON string values, subtitle cues, and ASS/SSA Dialogue events already have separate atomic parsers and are not part of this change.

## START REALITY CHECK

Confirm the expected parser version, unique identity, fidelity envelope, exporter checks, and existing translated-document behavior from real code/tests. Run the current TXT parser/exporter round-trip tests before editing. If source identity no longer includes parser version or span replacement cannot support a continuous multi-line TXT target, stop and report the exact blocker rather than weakening fidelity.

---

## CONTRACT

- Existing SourceDocument/Segment rows and Revisions are immutable mappings. Never resegment them in place or guess a Revision remap.
- New mapping behavior requires a new TXT parser identity/version. The same source bytes under the new parser version may create a new SourceDocument; the old version remains readable/exportable.
- Every new TXT Segment maps to one continuous, verifiable byte span. Non-target bytes, encoding, BOM, newline form, leading/trailing whitespace, and untouched regions must round-trip exactly.
- `stable_key` excludes raw byte offsets and is deterministic only within the same logical parser version/result. Duplicate text must still produce distinct stable identities.
- Prefer paragraph and dialogue boundaries, then sentence punctuation and a fixed length threshold. Do not split inside unsafe encoding boundaries or manufacture overlapping/gapped replacement spans.
- JSON, SRT, VTT, ASS, and SSA atomic-unit behavior is unchanged. Oversized non-TXT units remain an actionable error, not a hidden split.
- Segmentation settings are versioned constants for V1, not a new user-configurable framework or plugin API.

## IN SCOPE

- Design and implement a deterministic TXT segmentation policy for common Chinese/English prose, dialogue, blank-line paragraphs, long lines, and length fallback.
- Version parser/fidelity metadata so old mappings remain explainable and new imports are distinguishable.
- Keep ImportService deduplication correct across parser versions.
- Extend exporter/fidelity handling only as required for verified continuous multi-line spans.
- Add fixtures for encodings, BOM, newline varieties, punctuation/dialogue boundaries, duplicate text, blank regions, long units, and round-trip replacement.

## OUT OF SCOPE

- Resegmenting existing documents, migrating old Revisions, or automatic old/new alignment.
- NLP libraries, language detection packages, tokenizer dependencies, ML segmentation, per-language plugin systems, or settings UI.
- Changes to the five non-TXT parsers except shared regression fixes strictly required to preserve behavior.
- History Retrieval or multi-target batching.

## IMPLEMENTATION TARGET

Keep the parser small and explicit. Produce ordered target spans in one deterministic pass or a similarly auditable method; store enough algorithm/version metadata to validate export. Sentence/length splitting may combine adjacent physical lines only when the resulting target is a continuous original span and preservation of interior bytes is well-defined. If preserving an internal formatting boundary cannot be guaranteed, keep it as a boundary instead of normalizing it away.

## FILES EXPECTED

- `src/transrealm/infrastructure/parsers/txt_parser.py`
- `src/transrealm/infrastructure/fidelity.py`
- `src/transrealm/application/import_service.py`
- `src/transrealm/application/exporter.py`
- focused parser/fidelity tests and fixtures under `tests/`

## MINIMUM TESTS

1. Golden segmentation for prose paragraphs, dialogue lines, mixed Chinese/English punctuation, very long text, blank lines, and duplicate text is deterministic across repeated parses.
2. UTF-8/UTF-8 BOM/UTF-16 coverage plus CRLF/LF and representative legacy line breaks produces valid non-overlapping continuous byte spans.
3. Export after translating every generated Segment preserves every non-target byte and atomically replaces only verified targets.
4. The same bytes imported with old versus new parser identity never mutate/reuse an incompatible mapping; existing old-version documents and Revisions still open and export.
5. JSON/SRT/VTT/ASS/SSA parser/exporter fidelity regressions remain green and no atomic cue/event/value is split.

## VALIDATION

- Targeted TXT parser, ImportService, SourceDocument identity, fidelity, and exporter tests.
- Full six-format parser/exporter/fidelity regression because shared identity/envelope behavior is high risk.
- Full pytest, Ruff, and mypy.

## ACCEPTANCE

- New TXT imports use the documented deterministic mapping and parser identity.
- Old TXT documents remain untouched and usable.
- Byte-accurate round trips pass across representative encodings/newlines and failure paths leave existing targets unchanged.
- No external segmentation dependency or configuration subsystem was added.

## REGRESSION

Must preserve atomic non-TXT units, source hash rules, import idempotency, existing Revision ownership, missing-Revision export failure, temporary-file cleanup, and atomic target replacement.

## ROLLBACK / RECOVERY

Rollback is code-level for unreleased behavior; never rewrite user rows to the old mapping. If a new parser version has been used in a development database, retain that identity or advance to another parser version for corrections. Do not reuse the same version for incompatible mapping behavior.

## DELIVERABLES / DEFINITION OF DONE

- Versioned deterministic TXT segmenter and any minimal fidelity/export support.
- Golden and round-trip tests protecting identity and bytes.
- Required regressions pass.
- `tasks/README.md` marks T02 DONE and selects the next claimable task; this packet stays otherwise unchanged.

## STOP CONDITION

Stop after the new TXT mapping and fidelity contract pass. Do not add UI controls, resegment old projects, tune every language, or start T04.
