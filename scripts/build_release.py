"""Build the Windows green-version release candidate from the locked environment.

Produces a PyInstaller ``--onedir --windowed`` bundle named ``transrealm`` plus a
zipped green artifact and a ``build_manifest.json`` recording tool versions,
source identity, artifact hashes and sizes. The manifest fills the candidate
identity items of ``RELEASE_CHECKLIST.md`` (section 1/4) with recorded facts.

Usage::

    py -3.12 scripts/build_release.py [--output <dir>] [--skip-zip]

The default output directory is ``<repo>/dist`` (gitignored). Building a
candidate is not a release: this script never commits, pushes or publishes
anything. External actions (build upload / push / release) stay user-authorized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
MIGRATIONS = SRC / "transrealm" / "migrations"
I18N = SRC / "transrealm" / "ui" / "i18n"
PYPROJECT = REPO / "pyproject.toml"
LOCK = REPO / "requirements.lock"
RUN_PY = REPO / "run.py"
BUNDLE_NAME = "transrealm"


def _version_from_pyproject() -> str:
    for line in PYPROJECT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("pyproject.toml has no version field.")


def _locked_version(package: str) -> str | None:
    prefix = f"{package.lower()}=="
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith(prefix):
            return line.split("==", 1)[1].strip()
    return None


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dir_size_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _bundle_dir(bundle: Path) -> Path:
    return bundle / BUNDLE_NAME


def _isolated_build_path() -> str:
    """Keep unrelated native DLL directories out of PyInstaller resolution."""
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    paths = [
        Path(sys.executable).parent,
        Path(sys.prefix),
        Path(sys.base_prefix),
        system_root / "System32",
        system_root,
    ]
    git = shutil.which("git")
    if git:
        paths.insert(0, Path(git).parent)
    unique = dict.fromkeys(str(path) for path in paths if path.is_dir())
    return os.pathsep.join(unique)


def _validate_bundle(bundle: Path) -> dict[str, object]:
    """Verify the frozen bundle has migrations, i18n resources and Qt plugins."""
    exe = bundle / f"{BUNDLE_NAME}.exe"
    if not exe.is_file():
        raise SystemExit(f"Frozen entry exe missing: {exe}")
    frozen_migrations = sorted(
        path for path in bundle.rglob("*.sql") if "migrations" in path.parts
    )
    source_migrations = sorted(MIGRATIONS.glob("*.sql"))
    if len(frozen_migrations) != len(source_migrations):
        raise SystemExit(
            f"Frozen migrations {len(frozen_migrations)} != source "
            f"{len(source_migrations)}; --add-data likely missing.",
        )
    frozen_translations = sorted(
        path for path in bundle.rglob("*.qm") if "i18n" in path.parts
    )
    source_translations = sorted(I18N.glob("*.qm"))
    frozen_translation_names = sorted(path.name for path in frozen_translations)
    source_translation_names = sorted(path.name for path in source_translations)
    if frozen_translation_names != source_translation_names:
        raise SystemExit(
            f"Frozen translations {frozen_translation_names} != source "
            f"{source_translation_names}; --add-data likely missing.",
        )
    platform_plugins = sorted(bundle.rglob("qwindows.dll"))
    if not platform_plugins:
        raise SystemExit("Qt platform plugin platforms/qwindows.dll missing from bundle.")
    return {
        "exe": str(exe.relative_to(bundle.parent)),
        "migration_files": len(frozen_migrations),
        "migration_ids": [p.name for p in frozen_migrations],
        "translation_files": frozen_translation_names,
        "qt_plugins": {
            "platforms_qwindows": str(platform_plugins[0].relative_to(bundle)),
            "plugin_root": str(platform_plugins[0].parent.parent.relative_to(bundle)),
        },
        "plugin_categories": sorted(
            {
                path.name
                for path in (platform_plugins[0].parent.parent).glob("*/")
                if path.is_dir()
            }
        ),
    }


def _build(output: Path, work: Path) -> Path:
    from PyInstaller.__main__ import run as pyinstaller_main  # type: ignore[import-untyped]

    bundle_output = output.resolve()
    bundle_output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    argv = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name", BUNDLE_NAME,
        "--paths", str(SRC.resolve()),
        "--distpath", str(bundle_output),
        "--workpath", str(work),
        "--specpath", str(work),
        "--add-data", f"{MIGRATIONS.resolve()}{os.pathsep}transrealm/migrations",
        "--add-data", f"{I18N.resolve()}{os.pathsep}transrealm/ui/i18n",
        str(RUN_PY.resolve()),
    ]
    original_path = os.environ.get("PATH")
    os.environ["PATH"] = _isolated_build_path()
    try:
        pyinstaller_main(argv)
    finally:
        if original_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = original_path
    bundle = _bundle_dir(bundle_output)
    if not bundle.is_dir():
        raise SystemExit(f"PyInstaller produced no onedir at {bundle}")
    return bundle


def _write_manifest(
    manifest: dict[str, object],
    output: Path,
    bundle: Path,
    version: str,
    zip_path: Path | None,
) -> None:
    manifest.update(
        {
            "candidate": f"transrealm-{version}-win-x64.zip",
            "version": version,
            "built_at": datetime.now(UTC).isoformat(),
            "git_commit": _git("rev-parse", "HEAD"),
            "git_branch": _git("branch", "--show-current"),
            "git_dirty": bool(_git("status", "--porcelain")),
            "python": sys.version.split()[0],
            "pyinstaller": _locked_version("pyinstaller"),
            "pyside6": _locked_version("pyside6"),
            "exe_sha256": _sha256(bundle / f"{BUNDLE_NAME}.exe"),
            "onedir_size_bytes": _dir_size_bytes(bundle),
        }
    )
    if zip_path is not None:
        manifest.update(
            {
                "zip_sha256": _sha256(zip_path),
                "zip_size_bytes": zip_path.stat().st_size,
            }
        )
    target = output / "build_manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest written: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(REPO / "dist"),
        help="Output directory for the onedir, zip and manifest (default: <repo>/dist)",
    )
    parser.add_argument(
        "--skip-zip",
        action="store_true",
        help="Skip zipping the green artifact (manifest omits zip fields)",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="PyInstaller work/spec directory (default: <output>/.work)",
    )
    args = parser.parse_args()

    version = _version_from_pyproject()
    output = Path(args.output).resolve()
    work = Path(args.workdir).resolve() if args.workdir else (output / ".work")

    print(f"Building {BUNDLE_NAME} {version} -> {output}")
    print(f"PyInstaller locked: {_locked_version('pyinstaller')}")

    started = datetime.now(UTC)
    bundle = _build(output, work)
    validation = _validate_bundle(bundle)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    print(f"Build+validate OK in {elapsed:.1f}s; {validation['migration_files']} migrations; "
          f"Qt plugin categories: {validation['plugin_categories']}")

    zip_path: Path | None = None
    if not args.skip_zip:
        zip_base = output / f"transrealm-{version}-win-x64"
        zip_path = Path(
            shutil.make_archive(
                str(zip_base),
                "zip",
                root_dir=output,
                base_dir=BUNDLE_NAME,
            )
        )
        print(f"Green artifact: {zip_path} ({zip_path.stat().st_size} bytes)")

    _write_manifest(validation, output, bundle, version, zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
