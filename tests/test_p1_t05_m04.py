"""P1-T05-M04: Windows green-version candidate gate.

Verifies the candidate produced by ``scripts/build_release.py`` is launchable
and fully provisioned in the supported environment: unzip in a clean directory,
start against a writable data directory, migration application, Qt plugin
presence, graceful close and cleanup semantics (deleting the program directory
never deletes external data).

The candidate is built by the milestone action (``scripts/build_release.py``);
these tests validate the actual artifact when present and skip loudly otherwise.
The full create/import/translate/export journey is covered at source level by the
P1-T03 / P0-T08 real-window tests; the frozen bundle runs the identical code, so
this file covers the frozen-specific risks (migrations collection, Qt plugins,
entry point, data-directory provisioning, close and cleanup).
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import cast

import pytest

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
BUNDLE = DIST / "transrealm"
EXE = BUNDLE / "transrealm.exe"
MANIFEST = DIST / "build_manifest.json"
SRC_MIGRATIONS = REPO / "src" / "transrealm" / "migrations"
MIGRATION_COUNT = 12
RUN_PY = REPO / "run.py"
BUILD_SCRIPT = REPO / "scripts" / "build_release.py"

WINDOW_TITLE = "TransRealm"
WM_CLOSE = 0x0010


def _candidate_ready() -> bool:
    return EXE.is_file() and MANIFEST.is_file()


def _load_manifest() -> dict[str, object]:
    return cast(dict[str, object], json.loads(MANIFEST.read_text(encoding="utf-8")))


def _dir_size_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def _find_window_for_process(title: str, pid: int) -> int:
    """Return the visible top-level window with ``title`` owned by ``pid``."""
    user32 = ctypes.windll.user32
    found = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _callback(hwnd: ctypes.c_void_p, _lparam: ctypes.c_void_p) -> bool:
        nonlocal found
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == title:
                found = int(hwnd or 0)
                return False
        return True

    user32.EnumWindows(_callback, 0)
    return found


def _post_close(hwnd: int) -> None:
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _migration_count(db_path: Path) -> int:
    if not db_path.is_file():
        return -1
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
        return int(row[0]) if row else -1
    finally:
        conn.close()


def _launch(exe: Path, data_root: Path) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["USERPROFILE"] = str(data_root)
    return subprocess.Popen(
        [str(exe)],
        env=env,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture(scope="module")
def candidate_zip() -> Path | None:
    """Return the green artifact zip, or None when the candidate is absent."""
    zips = sorted(DIST.glob("transrealm-*-win-x64.zip"))
    return zips[0] if zips else None


def test_build_tooling_exists() -> None:
    """The build entry and script exist and carry the required packaging flags."""
    assert RUN_PY.is_file(), f"{RUN_PY} missing (PyInstaller entry script)"
    text = RUN_PY.read_text(encoding="utf-8")
    assert "from transrealm.ui.main_window import main" in text
    assert "main()" in text

    assert BUILD_SCRIPT.is_file(), f"{BUILD_SCRIPT} missing (build script)"
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    for needle in (
        "--onedir",
        "--windowed",
        "--name",
        "--paths",
        "--add-data",
        "transrealm/migrations",
    ):
        assert needle in script, f"build script lacks {needle!r}"

    assert len(list(SRC_MIGRATIONS.glob("*.sql"))) == MIGRATION_COUNT, (
        f"expected {MIGRATION_COUNT} migration SQL files"
    )


@pytest.mark.skipif(
    not _candidate_ready(),
    reason="candidate not built — run `py -3.12 scripts/build_release.py`",
)
def test_candidate_built_and_manifest_matches_artifact() -> None:
    """The manifest records the artifact identity and matches the frozen bundle."""
    manifest = _load_manifest()
    for key in (
        "candidate",
        "version",
        "built_at",
        "git_commit",
        "git_dirty",
        "python",
        "pyinstaller",
        "pyside6",
        "exe_sha256",
        "onedir_size_bytes",
        "zip_sha256",
        "zip_size_bytes",
        "migration_files",
        "qt_plugins",
    ):
        assert key in manifest, f"manifest missing {key!r}"

    # Candidate identity must be a verifiable baseline (09 §6 / RELEASE_CHECKLIST §1).
    head = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
    )
    assert manifest["git_commit"] == head

    import hashlib

    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    assert EXE.is_file()
    assert _sha256(EXE) == manifest["exe_sha256"], "exe sha256 drifts from manifest"
    assert _dir_size_bytes(BUNDLE) == manifest["onedir_size_bytes"], (
        "onedir size drifts from manifest"
    )

    zip_name = manifest["candidate"]
    assert isinstance(zip_name, str)
    zip_path = DIST / zip_name
    assert zip_path.is_file(), f"candidate zip missing: {zip_path}"
    assert _sha256(zip_path) == manifest["zip_sha256"], "zip sha256 drifts from manifest"
    assert manifest["zip_size_bytes"] == zip_path.stat().st_size, (
        "zip size drifts from manifest"
    )

    frozen_migrations = [p.name for p in BUNDLE.rglob("*.sql") if "migrations" in p.parts]
    assert len(frozen_migrations) == MIGRATION_COUNT
    assert manifest["migration_files"] == MIGRATION_COUNT
    assert sorted(frozen_migrations) == sorted(p.name for p in SRC_MIGRATIONS.glob("*.sql"))

    plugins = list(BUNDLE.rglob("qwindows.dll"))
    assert plugins, "Qt platform plugin platforms/qwindows.dll missing"
    qt_plugins = manifest["qt_plugins"]
    assert isinstance(qt_plugins, dict)
    assert "platforms_qwindows" in qt_plugins


@pytest.mark.skipif(
    not (candidate_zip and _candidate_ready()),
    reason="candidate zip not built — run `py -3.12 scripts/build_release.py`",
)
def test_candidate_artifact_contains_no_user_data(candidate_zip: Path) -> None:
    """The green artifact carries only the onedir: no user data, no build residue."""
    blocked_suffixes = (".sqlite", ".sqlite3", ".db", ".db.bak", ".log", ".aiproject")
    with zipfile.ZipFile(candidate_zip) as zf:
        names = zf.namelist()
    assert names, "artifact is empty"
    for name in names:
        assert name.startswith("transrealm/"), f"artifact has non-onedir entry {name}"
        lower = name.lower()
        assert not lower.endswith(blocked_suffixes), f"artifact contains user-data file {name}"
        assert ".env" not in lower, f"artifact contains environment file {name}"
        if lower.endswith(".zip"):
            # PyInstaller bundles stdlib bytecode in _internal/base_library.zip;
            # anything else is a nested artifact or residue.
            assert lower.endswith("transrealm/_internal/base_library.zip"), (
                f"artifact contains a nested zip entry {name}"
            )
        assert "/.work/" not in "/" + lower, f"artifact contains build residue {name}"
        assert not lower.endswith("build_manifest.json"), (
            f"artifact contains a stray manifest {name}"
        )
    assert any(n.endswith("transrealm.exe") for n in names)


@pytest.mark.skipif(
    not (candidate_zip and _candidate_ready()),
    reason="candidate zip not built — run `py -3.12 scripts/build_release.py`",
)
def test_candidate_unzip_launch_provision_close_cleanup(candidate_zip: Path) -> None:
    """Clean unzip, launch, data-dir provisioning, graceful close and cleanup.

    Exercises the frozen app end to end: unzip to a clean directory, launch with
    USERPROFILE pointed at a fresh writable data root, wait for the main window and
    a fully migrated database, confirm the program directory is never written,
    close the window (graceful closeEvent path), confirm data survives the close,
    then delete the program directory and confirm external data is untouched.
    """
    install_dir = Path(tempfile.mkdtemp(prefix="transrealm_m04_install_"))
    data_root = Path(tempfile.mkdtemp(prefix="transrealm_m04_data_"))
    proc: subprocess.Popen[str] | None = None
    try:
        with zipfile.ZipFile(candidate_zip) as zf:
            zf.extractall(install_dir)
        app_dir = install_dir / "transrealm"
        exe = app_dir / "transrealm.exe"
        assert exe.is_file(), f"unzipped candidate has no entry exe: {exe}"

        before = _tree_snapshot(app_dir)

        proc = _launch(exe, data_root)
        db_path = data_root / ".transrealm" / "project.sqlite"

        deadline = time.monotonic() + 180
        hwnd = 0
        db_count = -1
        while time.monotonic() < deadline:
            hwnd = _find_window_for_process(WINDOW_TITLE, proc.pid)
            db_count = _migration_count(db_path)
            if hwnd and db_count == MIGRATION_COUNT:
                break
            if proc.poll() is not None:
                break
            time.sleep(1)

        assert proc.poll() is None, (
            f"frozen app exited early with code {proc.returncode} before provisioning"
        )
        assert hwnd, f"main window {WINDOW_TITLE!r} did not appear (db migrations={db_count})"
        assert db_count == MIGRATION_COUNT, (
            f"frozen app applied {db_count} migrations, expected {MIGRATION_COUNT}"
        )

        after_launch = _tree_snapshot(app_dir)
        assert after_launch == before, "frozen app wrote into its own program directory"

        _post_close(hwnd)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
            raise AssertionError("frozen app did not exit gracefully after WM_CLOSE")
        assert proc.returncode == 0, f"frozen app exited with code {proc.returncode}"
        proc = None

        assert db_path.is_file(), "database lost after graceful close"
        assert _migration_count(db_path) == MIGRATION_COUNT, (
            "database damaged by graceful close"
        )

        shutil.rmtree(install_dir)
        assert data_root.exists(), "deleting the program directory removed external data"
        assert _migration_count(db_path) == MIGRATION_COUNT, (
            "external data damaged by program-directory deletion"
        )
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(install_dir, ignore_errors=True)
        shutil.rmtree(data_root, ignore_errors=True)
