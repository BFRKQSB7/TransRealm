"""Validate a task's changed paths against its approved scope."""

from __future__ import annotations

import argparse
import json
import subprocess

HIGH_RISK_PREFIXES = (
    "src/transrealm/migrations/",
    "src/transrealm/infrastructure/migrations/",
    "src/transrealm/adapters/credential_resolvers.py",
    "src/transrealm/adapters/http_transport.py",
    ".github/",
)


def changed_paths(base_commit: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_commit}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def permitted(path: str, allowed_paths: tuple[str, ...]) -> bool:
    return any(
        path == allowed or path.startswith(f"{allowed.rstrip('/')}/")
        for allowed in allowed_paths
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--allow", action="append", required=True)
    args = parser.parse_args()

    paths = changed_paths(args.base_commit)
    outside_scope = [path for path in paths if not permitted(path, tuple(args.allow))]
    report = {
        "task": args.task,
        "base_commit": args.base_commit,
        "changed_paths": paths,
        "outside_scope": outside_scope,
        "high_risk_paths": [
            path for path in paths if path.startswith(HIGH_RISK_PREFIXES)
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if outside_scope:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
