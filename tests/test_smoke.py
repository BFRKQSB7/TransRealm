"""Smoke tests for the TransRealm project skeleton."""

import importlib
import importlib.util
import sys

import transrealm
import transrealm.adapters
import transrealm.application
import transrealm.domain
import transrealm.infrastructure
import transrealm.ui


def test_package_version() -> None:
    """The root package exposes a version string."""
    assert transrealm.__version__ == "0.1.0"


def test_layer_packages_are_importable() -> None:
    """All required layer packages can be imported."""
    assert transrealm.ui is not None
    assert transrealm.application is not None
    assert transrealm.domain is not None
    assert transrealm.infrastructure is not None
    assert transrealm.adapters is not None


def test_domain_layer_has_no_forbidden_runtime_dependencies() -> None:
    """Domain layer does not depend on Qt/SQLite/HTTP SDKs at import time."""
    forbidden = {"PySide6", "sqlite3", "urllib3", "httpx", "requests", "aiohttp"}
    loaded = set(sys.modules.keys())
    domain_modules = {
        name for name in loaded if name.startswith("transrealm.domain")
    }
    assert domain_modules, "expected at least one loaded transrealm.domain module"
    assert not (forbidden & loaded), f"domain layer loaded forbidden deps: {forbidden & loaded}"


def test_all_layer_packages_have_dunder_init() -> None:
    """Each layer package has an __init__.py defining it as a package."""
    packages = [
        transrealm,
        transrealm.ui,
        transrealm.application,
        transrealm.domain,
        transrealm.infrastructure,
        transrealm.adapters,
    ]
    for pkg in packages:
        spec = importlib.util.find_spec(pkg.__name__)
        assert spec is not None, f"{pkg.__name__} has no import spec"
        assert spec.origin is not None, f"{pkg.__name__} is not a regular package"
        assert spec.origin.endswith("__init__.py")
