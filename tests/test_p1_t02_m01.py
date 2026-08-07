"""P1-T02-M01: shared manifest and open-directory Project container.

The open directory is authoritative as ``manifest.json + project.sqlite`` plus
declared attachments. Creating one must produce a clean container, reopening
must keep the same Project identity, and the manifest must be fail-closed:
unknown format/schema versions, entries outside the root (absolute paths,
drives, UNC, ``..``, normalization escapes), link/junction entries, duplicate
or case/Unicode-equivalent entries, and any size/hash mismatch are rejected
before the container is used.
"""

from __future__ import annotations

import json
import os
import subprocess
import unicodedata
from pathlib import Path

import pytest

from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.open_directory import (
    ATTACHMENT_ENTRY_TYPE,
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_FORMAT_VERSION,
    FileIntegrityError,
    ManifestEntry,
    ManifestError,
    ManifestInfo,
    OpenDirectoryError,
    PathValidationError,
    build_manifest,
    canonical_relpath,
    compute_entry,
    is_link,
    load_manifest,
    validate_manifest,
    write_manifest,
)

APP_VERSION = "0.1.0"
_HASH = "sha256:" + "0" * 64


def _file_entry(type_: str = CRITICAL_ENTRY_TYPE, *, size: object = 3) -> dict[str, object]:
    """Return a structurally valid file entry dict for manifest payloads."""
    return {"type": type_, "size": size, "hash": _HASH}


def _project_dir(tmp_path: Path) -> Path:
    return tmp_path / "proj"


def _valid_manifest_dict(
    *,
    format_version: object = MANIFEST_FORMAT_VERSION,
    schema_version: object = 1,
    software: object = APP_VERSION,
    files: object = None,
) -> dict[str, object]:
    """Return a structurally valid manifest dict with overridable fields."""
    if files is None:
        files = {"project.sqlite": {"type": CRITICAL_ENTRY_TYPE, "size": 3, "hash": _HASH}}
    return {
        "format_version": format_version,
        "schema_version": schema_version,
        "software": software,
        "files": files,
    }


def _write_raw_manifest(directory: Path, payload: object) -> Path:
    """Write arbitrary JSON to the manifest, bypassing validation helpers."""
    manifest_path = directory / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def _db_entry_hash(db_path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(db_path.read_bytes()).hexdigest()


def _load_manifest_raises(directory: Path, payload: object, error: type[Exception]) -> None:
    _write_raw_manifest(directory, payload)
    with pytest.raises(error):
        load_manifest(directory)


# ---------------------------------------------------------------------------
# create_open_directory_project
# ---------------------------------------------------------------------------


def test_create_produces_clean_container(tmp_path: Path) -> None:
    """Creating a project leaves only manifest.json and project.sqlite."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ):
        pass
    names = sorted(p.name for p in directory.iterdir())
    assert names == [MANIFEST_FILENAME, DATABASE_FILENAME]


def test_create_manifest_records_versions_and_entry(tmp_path: Path) -> None:
    """The manifest fixes format/schema/software and the database entry."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ):
        pass
    manifest = load_manifest(directory)
    assert manifest.format_version == MANIFEST_FORMAT_VERSION
    assert manifest.schema_version == 1
    assert manifest.software == APP_VERSION
    (entry,) = manifest.entries
    assert entry.relpath == DATABASE_FILENAME
    assert entry.type == CRITICAL_ENTRY_TYPE
    assert entry.size == (directory / DATABASE_FILENAME).stat().st_size
    assert entry.hash == _db_entry_hash(directory / DATABASE_FILENAME)


def test_create_reopen_keeps_same_project(tmp_path: Path) -> None:
    """Reopening the container returns the same Project identity."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="持久项目",
        source_language="ja",
        target_language="zh",
        app_version=APP_VERSION,
    ) as created:
        project_id = created.project.id
    with open_open_directory_project(directory, app_version=APP_VERSION) as reopened:
        assert reopened.project.id == project_id
        assert reopened.project.name == "持久项目"
        assert reopened.project.source_language == "ja"
        assert reopened.project.target_language == "zh"
        assert reopened.project.schema_version == 1


def test_create_into_existing_empty_directory(tmp_path: Path) -> None:
    """Creating into a pre-existing empty directory is allowed."""
    directory = _project_dir(tmp_path)
    directory.mkdir()
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="a",
        target_language="b",
        app_version=APP_VERSION,
    ) as created:
        assert created.project.name == "Alpha"


def test_create_refuses_non_empty_directory(tmp_path: Path) -> None:
    """Creating into a non-empty directory never overwrites existing files."""
    directory = _project_dir(tmp_path)
    directory.mkdir()
    (directory / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(OpenDirectoryError):
        create_open_directory_project(
            directory,
            name="Alpha",
            source_language="a",
            target_language="b",
            app_version=APP_VERSION,
        )
    assert (directory / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_create_refuses_file_as_directory(tmp_path: Path) -> None:
    """A path that is a regular file is not a valid project directory."""
    directory = _project_dir(tmp_path)
    directory.write_text("not a dir", encoding="utf-8")
    with pytest.raises(OpenDirectoryError):
        create_open_directory_project(
            directory,
            name="Alpha",
            source_language="a",
            target_language="b",
            app_version=APP_VERSION,
        )


def test_create_cleans_up_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed create leaves no partial container behind."""
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated initialization failure")

    monkeypatch.setattr(
        "transrealm.application.open_directory_service._initialize_database",
        boom,
    )
    directory = _project_dir(tmp_path)
    with pytest.raises(RuntimeError):
        create_open_directory_project(
            directory,
            name="Alpha",
            source_language="a",
            target_language="b",
            app_version=APP_VERSION,
        )
    assert not directory.exists()


def test_create_failure_keeps_preexisting_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed create into a user-owned empty dir leaves the dir itself intact."""
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated initialization failure")

    monkeypatch.setattr(
        "transrealm.application.open_directory_service._initialize_database",
        boom,
    )
    directory = _project_dir(tmp_path)
    directory.mkdir()
    with pytest.raises(RuntimeError):
        create_open_directory_project(
            directory,
            name="Alpha",
            source_language="a",
            target_language="b",
            app_version=APP_VERSION,
        )
    assert directory.is_dir()
    assert list(directory.iterdir()) == []


# ---------------------------------------------------------------------------
# open_open_directory_project
# ---------------------------------------------------------------------------


def test_open_missing_directory_fails(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    with pytest.raises(OpenDirectoryError):
        open_open_directory_project(directory, app_version=APP_VERSION)


def test_open_file_as_directory_fails(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    directory.write_text("x", encoding="utf-8")
    with pytest.raises(OpenDirectoryError):
        open_open_directory_project(directory, app_version=APP_VERSION)


def test_open_requires_single_project_identity(tmp_path: Path) -> None:
    """A container database holding two Projects is rejected, not silently picked."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="a",
        target_language="b",
        app_version=APP_VERSION,
    ):
        pass
    with ProjectService(directory / DATABASE_FILENAME, app_version=APP_VERSION) as service:
        service.create_project(name="Beta", source_language="c", target_language="d")
    manifest = build_manifest(ManifestInfo(1, 1, APP_VERSION, tuple(_current_entries(directory))))
    _write_raw_manifest(directory, manifest)
    with pytest.raises(OpenDirectoryError):
        open_open_directory_project(directory, app_version=APP_VERSION)


def test_open_rejects_tampered_db_content(tmp_path: Path) -> None:
    """A modified database fails the manifest hash/size verification."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="a",
        target_language="b",
        app_version=APP_VERSION,
    ):
        pass
    db_path = directory / DATABASE_FILENAME
    db_path.write_bytes(db_path.read_bytes() + b"X")
    with pytest.raises(FileIntegrityError):
        open_open_directory_project(directory, app_version=APP_VERSION)


def test_reopen_keeps_container_clean(tmp_path: Path) -> None:
    """Reopening and closing leaves no backup or WAL sidecar files."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="a",
        target_language="b",
        app_version=APP_VERSION,
    ):
        pass
    for _ in range(2):
        with open_open_directory_project(directory, app_version=APP_VERSION):
            pass
    names = sorted(p.name for p in directory.iterdir())
    assert names == [MANIFEST_FILENAME, DATABASE_FILENAME]


def test_open_accepts_declared_attachment(tmp_path: Path) -> None:
    """A container with a valid declared attachment opens successfully."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="a",
        target_language="b",
        app_version=APP_VERSION,
    ):
        pass
    attachment_dir = directory / "attachments"
    attachment_dir.mkdir()
    notes = attachment_dir / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    entries = list(_current_entries(directory))
    entries.append(compute_entry("attachments/notes.txt", notes, entry_type=ATTACHMENT_ENTRY_TYPE))
    write_manifest(directory, ManifestInfo(1, 1, APP_VERSION, tuple(entries)))
    with open_open_directory_project(directory, app_version=APP_VERSION) as opened:
        relpaths = {entry.relpath for entry in opened.manifest.entries}
        assert relpaths == {DATABASE_FILENAME, "attachments/notes.txt"}


def test_open_rejects_tampered_manifest_format_version(tmp_path: Path) -> None:
    """Round-trip integrity: a tampered manifest version is rejected on open."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="a",
        target_language="b",
        app_version=APP_VERSION,
    ):
        pass
    _write_raw_manifest(directory, _valid_manifest_dict(format_version=2))
    with pytest.raises(ManifestError):
        open_open_directory_project(directory, app_version=APP_VERSION)


# ---------------------------------------------------------------------------
# load_manifest structural validation
# ---------------------------------------------------------------------------


def test_missing_manifest_fails(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    with pytest.raises(ManifestError):
        load_manifest(directory)


def test_invalid_json_manifest_fails(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    _write_raw_manifest(directory, "{ not json ")
    with pytest.raises(ManifestError):
        load_manifest(directory)


def test_manifest_root_must_be_object(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    _load_manifest_raises(directory, [1, 2], ManifestError)


@pytest.mark.parametrize(
    "override",
    [
        {"format_version": None},
        {"format_version": "1"},
        {"format_version": 2},
        {"format_version": 0},
        {"format_version": 1.5},
    ],
)
def test_format_version_validation(tmp_path: Path, override: dict[str, object]) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    _load_manifest_raises(directory, _valid_manifest_dict(**override), ManifestError)


@pytest.mark.parametrize(
    "override",
    [
        {"schema_version": None},
        {"schema_version": "1"},
        {"schema_version": 0},
        {"schema_version": -1},
        {"schema_version": 2},
        {"schema_version": 1.0},
    ],
)
def test_schema_version_validation(tmp_path: Path, override: dict[str, object]) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    _load_manifest_raises(directory, _valid_manifest_dict(**override), ManifestError)


@pytest.mark.parametrize(
    "software",
    [None, "", "   "],
)
def test_software_version_validation(tmp_path: Path, software: object) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    _load_manifest_raises(directory, _valid_manifest_dict(software=software), ManifestError)


def test_files_missing_fails(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    payload = _valid_manifest_dict()
    del payload["files"]
    _load_manifest_raises(directory, payload, ManifestError)


def test_files_not_object_fails(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    _load_manifest_raises(directory, _valid_manifest_dict(files=["x"]), ManifestError)


@pytest.mark.parametrize(
    "files",
    [
        {"project.sqlite": "not-an-object"},
        {"project.sqlite": {"type": "weird", "size": 3, "hash": _HASH}},
        {"project.sqlite": {"type": CRITICAL_ENTRY_TYPE, "size": -1, "hash": _HASH}},
        {"project.sqlite": {"type": CRITICAL_ENTRY_TYPE, "size": 3, "hash": "md5:abc"}},
        {"project.sqlite": {"type": CRITICAL_ENTRY_TYPE, "size": 3, "hash": "sha256:short"}},
        {"project.sqlite": {"type": CRITICAL_ENTRY_TYPE, "size": "3", "hash": _HASH}},
    ],
)
def test_entry_structure_validation(tmp_path: Path, files: object) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    _load_manifest_raises(directory, _valid_manifest_dict(files=files), ManifestError)


def test_duplicate_json_keys_fails(tmp_path: Path) -> None:
    """Duplicate keys in the files object cannot shadow a critical entry."""
    directory = _project_dir(tmp_path)
    directory.mkdir()
    raw = (
        '{"format_version": 1, "schema_version": 1, "software": "0.1.0", '
        '"files": {"project.sqlite": {"type": "database", "size": 1, '
        '"hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000"}, '
        '"project.sqlite": {"type": "database", "size": 999, '
        '"hash": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}}}'
    )
    (directory / MANIFEST_FILENAME).write_text(raw, encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(directory)


def test_duplicate_nested_json_keys_fails(tmp_path: Path) -> None:
    """Duplicate keys inside an entry object cannot shadow a declared value."""
    directory = _project_dir(tmp_path)
    directory.mkdir()
    zeros = "0" * 64
    raw = (
        '{"format_version": 1, "schema_version": 1, "software": "0.1.0", '
        '"files": {"project.sqlite": {"type": "database", "type": "attachment", '
        '"size": 1, "hash": "sha256:'
        + zeros
        + '"}}}'
    )
    (directory / MANIFEST_FILENAME).write_text(raw, encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(directory)


# ---------------------------------------------------------------------------
# validate_manifest: critical entry and normalized duplicates
# ---------------------------------------------------------------------------


def _info(entries: list[ManifestEntry]) -> ManifestInfo:
    return ManifestInfo(
        format_version=1,
        schema_version=1,
        software=APP_VERSION,
        entries=tuple(entries),
    )


def _critical(size: int = 3) -> ManifestEntry:
    return ManifestEntry(DATABASE_FILENAME, CRITICAL_ENTRY_TYPE, size, _HASH)


def test_validate_requires_critical_entry() -> None:
    with pytest.raises(FileIntegrityError):
        validate_manifest(_info([]))


def test_validate_rejects_duplicate_critical_entries() -> None:
    entries = [_critical(), ManifestEntry("db2.sqlite", CRITICAL_ENTRY_TYPE, 3, _HASH)]
    with pytest.raises(FileIntegrityError):
        validate_manifest(_info(entries))


def test_validate_rejects_renamed_critical_entry() -> None:
    entries = [ManifestEntry("other.sqlite", CRITICAL_ENTRY_TYPE, 3, _HASH)]
    with pytest.raises(FileIntegrityError):
        validate_manifest(_info(entries))


def test_validate_rejects_manifest_self_reference() -> None:
    entries = [_critical(), ManifestEntry(MANIFEST_FILENAME, ATTACHMENT_ENTRY_TYPE, 1, _HASH)]
    with pytest.raises(PathValidationError):
        validate_manifest(_info(entries))


def test_validate_rejects_case_equivalent_duplicates() -> None:
    entries = [
        _critical(),
        ManifestEntry("Attachments/Readme.txt", ATTACHMENT_ENTRY_TYPE, 1, _HASH),
        ManifestEntry("attachments/readme.txt", ATTACHMENT_ENTRY_TYPE, 1, _HASH),
    ]
    with pytest.raises(PathValidationError):
        validate_manifest(_info(entries))


def test_validate_rejects_unicode_equivalent_duplicates() -> None:
    composed = "attachments/\u00e9.txt"  # NFC
    decomposed = "attachments/e\u0301.txt"  # NFD e + combining acute
    assert unicodedata.normalize("NFC", composed) == unicodedata.normalize("NFC", decomposed)
    assert composed != decomposed
    entries = [
        _critical(),
        ManifestEntry(composed, ATTACHMENT_ENTRY_TYPE, 1, _HASH),
        ManifestEntry(decomposed, ATTACHMENT_ENTRY_TYPE, 1, _HASH),
    ]
    with pytest.raises(PathValidationError):
        validate_manifest(_info(entries))


def test_validate_rejects_trailing_dot_alias() -> None:
    """Windows trims trailing dots, so a dotted twin collides with the entry."""
    entries = [
        _critical(),
        ManifestEntry("project.sqlite.", ATTACHMENT_ENTRY_TYPE, 3, _HASH),
    ]
    with pytest.raises(PathValidationError):
        validate_manifest(_info(entries))


def test_validate_rejects_manifest_trailing_dot_self_alias() -> None:
    """A trailing dot makes an entry alias the manifest itself on Windows."""
    entries = [
        _critical(),
        ManifestEntry("manifest.json.", ATTACHMENT_ENTRY_TYPE, 1, _HASH),
    ]
    with pytest.raises(PathValidationError):
        validate_manifest(_info(entries))


# ---------------------------------------------------------------------------
# canonical_relpath: entries outside the root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relpath",
    [
        "C:\\evil.txt",
        "c:/evil.txt",
        "/evil.txt",
        "\\evil.txt",
        "\\\\server\\share",
        "//server/share",
        "..\\evil.txt",
        "../evil.txt",
        "attachments/../../evil.txt",
        "..\\..\\evil.txt",
        "C:evil.txt",
        "",
        "   ",
        "attachments/a\x00b.txt",
        "a\nb.txt",
        "a\tb.txt",
    ],
)
def test_canonical_relpath_rejects_escape_paths(relpath: str) -> None:
    with pytest.raises(PathValidationError):
        canonical_relpath(relpath)


def test_canonical_relpath_normalizes_separators() -> None:
    assert canonical_relpath("attachments\\notes.txt") == "attachments/notes.txt"
    assert canonical_relpath("attachments//notes.txt") == "attachments/notes.txt"


def test_resolve_within_root_detects_escape(tmp_path: Path) -> None:
    directory = _project_dir(tmp_path)
    directory.mkdir()
    from transrealm.infrastructure.open_directory import resolve_within_root

    with pytest.raises(PathValidationError):
        resolve_within_root(directory, "../outside.txt")


# ---------------------------------------------------------------------------
# verify_entries: file integrity and links
# ---------------------------------------------------------------------------


def _materialize(tmp_path: Path, *, extra_entries: list[ManifestEntry] | None = None) -> Path:
    """Create a real container and return its directory."""
    directory = _project_dir(tmp_path)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="a",
        target_language="b",
        app_version=APP_VERSION,
    ):
        pass
    return directory


def test_verify_missing_declared_file(tmp_path: Path) -> None:
    directory = _materialize(tmp_path)
    from transrealm.infrastructure.open_directory import verify_entries

    entries = list(_current_entries(directory))
    entries.append(ManifestEntry("attachments/missing.txt", ATTACHMENT_ENTRY_TYPE, 1, _HASH))
    with pytest.raises(FileIntegrityError):
        verify_entries(directory, _info(entries))


def test_verify_size_mismatch(tmp_path: Path) -> None:
    directory = _materialize(tmp_path)
    from transrealm.infrastructure.open_directory import verify_entries

    real = _current_entries(directory)
    tampered = [
        ManifestEntry(entry.relpath, entry.type, entry.size + 1, entry.hash)
        for entry in real
    ]
    with pytest.raises(FileIntegrityError):
        verify_entries(directory, _info(tampered))


def test_verify_hash_mismatch(tmp_path: Path) -> None:
    directory = _materialize(tmp_path)
    from transrealm.infrastructure.open_directory import verify_entries

    real = _current_entries(directory)
    tampered = [ManifestEntry(entry.relpath, entry.type, entry.size, _HASH) for entry in real]
    with pytest.raises(FileIntegrityError):
        verify_entries(directory, _info(tampered))


def test_verify_rejects_directory_entry(tmp_path: Path) -> None:
    directory = _materialize(tmp_path)
    from transrealm.infrastructure.open_directory import verify_entries

    (directory / "attachments").mkdir()
    entries = list(_current_entries(directory))
    entries.append(ManifestEntry("attachments", ATTACHMENT_ENTRY_TYPE, 0, _HASH))
    with pytest.raises(FileIntegrityError):
        verify_entries(directory, _info(entries))


def test_verify_rejects_junction_entry(tmp_path: Path) -> None:
    """A junction declared as an entry is rejected as a link."""
    directory = _materialize(tmp_path)
    real_dir = directory / "real_dir"
    real_dir.mkdir()
    junction = directory / "attachments"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(real_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"cannot create junction: {result.stderr.strip()}")
    from transrealm.infrastructure.open_directory import verify_entries

    entries = list(_current_entries(directory))
    entries.append(ManifestEntry("attachments", ATTACHMENT_ENTRY_TYPE, 0, _HASH))
    with pytest.raises(PathValidationError):
        verify_entries(directory, _info(entries))


def test_verify_rejects_symlink_entry(tmp_path: Path) -> None:
    """A symbolic link declared as an entry is rejected as a link."""
    directory = _materialize(tmp_path)
    target = directory / "real.txt"
    target.write_text("hello", encoding="utf-8")
    link = directory / "linked.txt"
    try:
        os.symlink(str(target), str(link))
    except OSError as exc:
        pytest.skip(f"cannot create symlink: {exc}")
    from transrealm.infrastructure.open_directory import verify_entries

    entries = list(_current_entries(directory))
    entries.append(ManifestEntry("linked.txt", ATTACHMENT_ENTRY_TYPE, 5, _db_entry_hash(link)))
    with pytest.raises(PathValidationError):
        verify_entries(directory, _info(entries))


def test_verify_rejects_entry_under_escaping_parent_link(tmp_path: Path) -> None:
    """An entry reached through a parent junction pointing outside the root fails."""
    directory = _materialize(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    junction = directory / "attachments"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"cannot create junction: {result.stderr.strip()}")
    from transrealm.infrastructure.open_directory import verify_entries

    entries = list(_current_entries(directory))
    secret = compute_entry(
        "attachments/secret.txt",
        outside / "secret.txt",
        entry_type=ATTACHMENT_ENTRY_TYPE,
    )
    entries.append(secret)
    with pytest.raises(PathValidationError):
        verify_entries(directory, _info(entries))


def test_is_link_detects_reparse_point() -> None:
    """is_link recognizes the Windows reparse-point attribute directly."""
    import stat as stat_module

    class FakeStat:
        st_mode = stat_module.S_IFREG
        st_file_attributes = stat_module.FILE_ATTRIBUTE_REPARSE_POINT

    class FakePath:
        def lstat(self) -> object:
            return FakeStat()

    assert is_link(FakePath())  # type: ignore[arg-type]


def test_is_link_false_for_regular_file(tmp_path: Path) -> None:
    directory = _materialize(tmp_path)
    assert not is_link(directory / DATABASE_FILENAME)


# ---------------------------------------------------------------------------
# helpers used by arrangement tests
# ---------------------------------------------------------------------------


def _current_entries(directory: Path) -> list[ManifestEntry]:
    db_path = directory / DATABASE_FILENAME
    return [compute_entry(DATABASE_FILENAME, db_path, entry_type=CRITICAL_ENTRY_TYPE)]
