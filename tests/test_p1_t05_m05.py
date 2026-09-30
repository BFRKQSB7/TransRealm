"""Current authoritative documents stay present and linked after Product Reset.

Candidate-specific user guidance and known-issue evidence belong to T06. This
module checks the live documents that replaced the archived V0.2 guides.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = {
    "product": REPO_ROOT / "docs" / "PRODUCT.md",
    "architecture": REPO_ROOT / "docs" / "ARCHITECTURE.md",
    "database": REPO_ROOT / "docs" / "DATABASE.md",
    "development": REPO_ROOT / "docs" / "DEVELOPMENT.md",
    "release": REPO_ROOT / "docs" / "RELEASE.md",
    "third-party-licenses": REPO_ROOT / "docs" / "third-party-licenses.md",
}


def _doc_text(name: str) -> str:
    path = DOCS[name]
    assert path.exists(), f"missing doc: {path}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"empty doc: {path}"
    return text


def test_current_docs_exist_and_nonempty() -> None:
    for name in DOCS:
        _doc_text(name)


def test_readme_links_to_authoritative_docs() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for path in (
        "docs/PRODUCT.md",
        "docs/ARCHITECTURE.md",
        "docs/DATABASE.md",
        "docs/DEVELOPMENT.md",
        "docs/RELEASE.md",
    ):
        assert path in readme, f"README missing link to {path}"


def test_development_data_boundary_and_runtime_path() -> None:
    development = _doc_text("development")
    assert "D:/TransRealm/" in development
    main_window = (REPO_ROOT / "src" / "transrealm" / "ui" / "main_window.py").read_text(
        encoding="utf-8",
    )
    assert 'Path.home() / ".transrealm"' in main_window


def test_release_doc_requires_candidate_identity_and_recovery() -> None:
    release = _doc_text("release")
    for required in ("Git commit", "git_dirty", "ZIP", "hash", "Project", "回滚"):
        assert required in release
