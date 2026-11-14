#!/usr/bin/env python3
"""Run the repository's CI gates in order: one command for CircleCI and contributors.

    python scripts/ci.py --tier full  [--json PATH]   # what CircleCI runs
    python scripts/ci.py --tier smoke [--json PATH]   # ruff + the contract tests, seconds

The run stops at the first failing step and exits with its code. ``--json`` writes each
step's name, exit code and wall time. Steps run inside the current environment
(``uv run --frozen --no-sync`` in CI); ruff runs through ``uvx`` at the pinned version.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUFF = ["uvx", "ruff@0.17.3", "check", "llm_dojo_scoring", "tests", "scripts", "examples"]
SMOKE_TESTS = (
    "tests/test_consumer_compat.py",
    "tests/test_root_surface.py",
    "tests/test_doc_classes.py",
    "tests/test_golden_scores.py",
)

Step = tuple[str, list[str]]


def steps(tier: str, junit: str | None = None) -> list[Step]:
    """The ordered ``(name, command)`` steps of ``tier`` (``full`` or ``smoke``)."""
    py = sys.executable
    if tier == "smoke":
        return [("ruff", RUFF), ("pytest-smoke", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *SMOKE_TESTS])]
    if tier != "full":
        raise ValueError(f"unknown tier {tier!r}; use 'full' or 'smoke'")
    pytest_cmd = [py, "-m", "pytest", "tests", "-q", "-rs", "-p", "no:cacheprovider"]
    if junit:
        pytest_cmd.append(f"--junitxml={junit}")
    return [
        ("ruff", RUFF),
        ("lock", ["uv", "lock", "--check"]),
        ("pytest", pytest_cmd),
        ("goldens", [py, "scripts/freeze_goldens.py", "--check"]),
        ("gt-coverage", [py, "scripts/render_gt_coverage.py", "--check"]),
    ]


def run(plan: Sequence[Step], json_path: Path | None = None) -> int:
    """Run ``plan`` in order, stop at the first failure, and return its exit code."""
    report: list[dict] = []
    code = 0
    for name, cmd in plan:
        print(f"==> {name}: {' '.join(cmd)}", flush=True)
        start = time.monotonic()
        code = subprocess.run(cmd, cwd=ROOT).returncode
        report.append({"name": name, "exit_code": code, "seconds": round(time.monotonic() - start, 2)})
        if code:
            print(f"==> {name} failed (exit {code})", flush=True)
            break
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({"exit_code": code, "steps": report}, indent=2) + "\n")
    return code


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the chosen tier."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", choices=("full", "smoke"), default="full")
    parser.add_argument("--json", type=Path, help="write a per-step report here")
    parser.add_argument("--junit", help="pytest --junitxml path (full tier)")
    args = parser.parse_args(argv)
    return run(steps(args.tier, args.junit), args.json)


if __name__ == "__main__":
    raise SystemExit(main())
