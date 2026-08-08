"""P1-T05-M05: user documentation is present and consistent with the candidate.

The documentation-only milestone's gate is: install/use/modes/Profile/Glossary/
migration/backup/recovery/cleanup/known-issues/license docs consistent with the
candidate, independent review, and the full command suite. These guards make
the "docs match the actual paths/behavior" claim boolean instead of review-only
(after the same anti-drift pattern as the P1-T05-M02/M03 fixed fixtures).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = {
    "user-guide": REPO_ROOT / "docs" / "user-guide.md",
    "data-safety": REPO_ROOT / "docs" / "data-safety.md",
    "known-issues": REPO_ROOT / "docs" / "known-issues.md",
    "third-party-licenses": REPO_ROOT / "docs" / "third-party-licenses.md",
}


def _doc_text(name: str) -> str:
    path = DOCS[name]
    assert path.exists(), f"missing doc: {path}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"empty doc: {path}"
    return text


def test_all_user_docs_exist_and_nonempty() -> None:
    for name in DOCS:
        _doc_text(name)


def test_readme_links_to_user_docs() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for path in (
        "docs/user-guide.md",
        "docs/data-safety.md",
        "docs/known-issues.md",
        "docs/third-party-licenses.md",
    ):
        assert path in readme, f"README missing link to {path}"


def test_user_guide_data_dir_matches_source() -> None:
    guide = _doc_text("user-guide")
    assert "%USERPROFILE%\\.transrealm" in guide
    main_window = (REPO_ROOT / "src" / "transrealm" / "ui" / "main_window.py").read_text(
        encoding="utf-8",
    )
    assert 'Path.home() / ".transrealm"' in main_window


def test_known_issues_zip_sha256_matches_manifest() -> None:
    manifest = REPO_ROOT / "dist" / "build_manifest.json"
    if not manifest.exists():
        pytest.skip(
            "candidate manifest not present; build first: py -3.12 scripts/build_release.py",
        )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["zip_sha256"] in _doc_text("known-issues")
    assert data["version"] in _doc_text("user-guide")
