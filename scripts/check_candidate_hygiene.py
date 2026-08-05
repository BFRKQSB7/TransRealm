"""Reject tracked files that must never enter a source candidate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

BLOCKED_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".aiproject", ".log")
BLOCKED_PARTS = {"__pycache__", "build", "dist", ".venv"}
BLOCKED_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def is_blocked(path: str) -> bool:
    candidate = PurePosixPath(path)
    name = candidate.name.lower()
    return (
        name in BLOCKED_NAMES
        or name.endswith(BLOCKED_SUFFIXES)
        or any(part.lower() in BLOCKED_PARTS for part in candidate.parts)
    )


def main() -> int:
    blocked = [path for path in tracked_files() if is_blocked(path)]
    if blocked:
        print("Blocked tracked candidate files:", file=sys.stderr)
        print("\n".join(blocked), file=sys.stderr)
        return 1
    print("Candidate hygiene passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
