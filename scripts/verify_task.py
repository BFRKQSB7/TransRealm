"""Validate a task's scope and declared regression tests."""

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


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def changed_paths(base_commit: str) -> list[str]:
    return git_lines("diff", "--name-only", f"{base_commit}...HEAD")


def deleted_tests(base_commit: str) -> list[str]:
    return [
        line[1:]
        for line in git_lines("diff", "--name-status", f"{base_commit}...HEAD")
        if line.startswith("D") and line[1:].lstrip().startswith("tests/")
    ]


def permitted(path: str, allowed_paths: tuple[str, ...]) -> bool:
    return any(
        path == allowed or path.startswith(f"{allowed.rstrip('/')}/")
        for allowed in allowed_paths
    )


def run_tests(test_ids: list[str]) -> dict[str, object]:
    command = ["py", "-3.12", "-m", "pytest", "-q", *test_ids]
    result = subprocess.run(command, capture_output=True, text=True)
    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--allow", action="append", required=True)
    parser.add_argument("--baseline-test", action="append", required=True)
    parser.add_argument("--new-test", action="append", required=True)
    parser.add_argument("--test-change-reason")
    args = parser.parse_args()

    paths = changed_paths(args.base_commit)
    removed_tests = deleted_tests(args.base_commit)
    outside_scope = [path for path in paths if not permitted(path, tuple(args.allow))]
    baseline_result = run_tests(args.baseline_test)
    new_result = run_tests(args.new_test)
    report = {
        "task": args.task,
        "base_commit": args.base_commit,
        "changed_paths": paths,
        "outside_scope": outside_scope,
        "high_risk_paths": [
            path for path in paths if path.startswith(HIGH_RISK_PREFIXES)
        ],
        "removed_tests": removed_tests,
        "test_change_reason": args.test_change_reason,
        "baseline_tests": baseline_result,
        "new_tests": new_result,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if outside_scope or baseline_result["exit_code"] or new_result["exit_code"]:
        return 1
    if removed_tests and not args.test_change_reason:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
