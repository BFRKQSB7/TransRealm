"""V02-T05-M01: keep runtime and candidate version identity aligned."""

import tomllib
from pathlib import Path

from scripts.build_release import _version_from_pyproject

import transrealm
from transrealm.ui.main_window import APP_VERSION

REPO = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.2.0"


def test_v02_version_identity_matches_candidate_source() -> None:
    metadata = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["version"] == EXPECTED_VERSION
    assert transrealm.__version__ == EXPECTED_VERSION
    assert APP_VERSION == EXPECTED_VERSION
    assert _version_from_pyproject() == EXPECTED_VERSION
