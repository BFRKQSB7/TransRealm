"""P1-T05-M01: 冻结可判定矩阵 —— 支持环境、依赖锁与矩阵契约的可重复断言。

矩阵冻结值见 03 §12（2026-08-08 实测）。依赖或环境变化必须同步
requirements.lock 与本文件；断言失败即 Gate 判定候选不通过（release-blocking）。
"""
from __future__ import annotations

import importlib.metadata
import platform
import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "requirements.lock"
PYPROJECT_FILE = ROOT / "pyproject.toml"

SUPPORTED_OS = "Windows"
SUPPORTED_ARCHS = {"AMD64", "x86_64"}
WINDOWS_11_MIN_BUILD = 22000
PYTHON_MAJOR = 3
PYTHON_MINOR = 12
DEV_TOOLS = {"pytest", "pytest-qt", "ruff", "mypy"}
PACKAGING_TOOLS = {"pyinstaller", "pyinstaller-hooks-contrib"}
NOT_LOCKED = {"transrealm", "pip"}
_LOCK_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([\w.+]+)")


def _lock_entries() -> dict[str, str]:
    """解析 requirements.lock 为 {规范化包名: 版本}，仅接受 `name==version` 行。"""
    entries: dict[str, str] = {}
    for raw in LOCK_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-e ", "git+")):
            continue
        match = _LOCK_RE.fullmatch(line)
        assert match is not None, f"malformed lock entry: {line!r}"
        name = match.group(1)
        norm = name.lower().replace("_", "-")
        assert norm not in entries, f"duplicate lock entry: {name!r}"
        assert norm not in NOT_LOCKED, f"lock must not contain {name!r}"
        entries[norm] = match.group(2)
    return entries


def _pyproject_runtime_specs() -> dict[str, SpecifierSet]:
    with PYPROJECT_FILE.open("rb") as fh:
        data = tomllib.load(fh)
    return {
        req.name.lower(): req.specifier
        for req in (Requirement(dep) for dep in data["project"]["dependencies"])
    }


def _pyproject_dev_specs() -> dict[str, SpecifierSet]:
    with PYPROJECT_FILE.open("rb") as fh:
        data = tomllib.load(fh)
    dev = data["project"]["optional-dependencies"]["dev"]
    return {
        req.name.lower(): req.specifier
        for req in (Requirement(dep) for dep in dev)
    }


def test_lock_file_exists() -> None:
    assert LOCK_FILE.is_file(), (
        f"missing {LOCK_FILE} — run `py -3.12 -m pip freeze | "
        "grep -vE '^(-e |pip==|transrealm )' > requirements.lock`"
    )


def test_lock_excludes_application_and_installer() -> None:
    locked = _lock_entries()
    assert not locked.keys() & NOT_LOCKED


def test_lock_matches_installed_packages() -> None:
    locked = _lock_entries()
    assert locked, "empty lock file"
    for norm, version in locked.items():
        installed = importlib.metadata.version(norm)
        assert installed == version, f"{norm}: installed {installed} != locked {version}"


def test_lock_satisfies_pyproject_runtime_specs() -> None:
    locked = _lock_entries()
    specs = _pyproject_runtime_specs()
    assert specs, "no runtime dependencies declared in pyproject"
    for name, spec in specs.items():
        assert name in locked, f"runtime dep {name!r} missing from lock"
        assert spec.contains(locked[name], prereleases=True), (
            f"{name} {locked[name]} violates pyproject spec {spec}"
        )


def test_dev_toolchain_locked() -> None:
    locked = _lock_entries()
    specs = _pyproject_dev_specs()
    assert specs, "no dev dependencies declared in pyproject"
    for name, spec in specs.items():
        assert name in locked, f"dev dep {name!r} missing from lock"
        assert spec.contains(locked[name], prereleases=True), (
            f"{name} {locked[name]} violates pyproject dev spec {spec}"
        )
    missing = sorted(DEV_TOOLS - locked.keys())
    assert not missing, f"dev tools not locked: {missing}"


def test_packaging_tools_recorded() -> None:
    locked = _lock_entries()
    missing = sorted(PACKAGING_TOOLS - locked.keys())
    assert not missing, f"packaging tools not locked: {missing}"


def test_supported_environment() -> None:
    assert platform.system() == SUPPORTED_OS
    assert sys.getwindowsversion().build >= WINDOWS_11_MIN_BUILD
    assert platform.machine() in SUPPORTED_ARCHS
    assert (sys.version_info.major, sys.version_info.minor) == (
        PYTHON_MAJOR,
        PYTHON_MINOR,
    )
