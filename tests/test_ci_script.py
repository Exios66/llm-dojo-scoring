"""``scripts/ci.py``: the one command CI and contributors run."""

from __future__ import annotations

import json
import sys

from conftest import load_script

ci = load_script("ci")


def _step(name: str, code: int) -> tuple[str, list[str]]:
    """A stub step whose command exits with ``code``."""
    return name, [sys.executable, "-c", f"raise SystemExit({code})"]


def test_full_tier_runs_every_gate_in_order():
    """``full`` runs ruff, the lock check, pytest, the golden check and the coverage page."""
    names = [name for name, _ in ci.steps("full")]
    assert names == ["ruff", "lock", "pytest", "goldens", "gt-coverage"]


def test_smoke_tier_is_ruff_plus_the_contract_tests():
    """``smoke`` runs ruff and the consumer / registry / golden tests only."""
    steps = dict(ci.steps("smoke"))
    assert list(steps) == ["ruff", "pytest-smoke"]
    for test in ("test_consumer_compat.py", "test_root_surface.py", "test_doc_classes.py", "test_golden_scores.py"):
        assert any(arg.endswith(test) for arg in steps["pytest-smoke"])


def test_failing_step_stops_the_run_and_is_reported(tmp_path):
    """The first failure stops the run, sets the exit code and is recorded in the JSON."""
    out = tmp_path / "ci.json"
    code = ci.run([_step("a", 0), _step("b", 3), _step("c", 0)], json_path=out)
    assert code == 3
    report = json.loads(out.read_text())
    assert [s["name"] for s in report["steps"]] == ["a", "b"]
    assert [s["exit_code"] for s in report["steps"]] == [0, 3]
    assert all(s["seconds"] >= 0 for s in report["steps"])
    assert report["exit_code"] == 3


def test_all_green_exits_zero(tmp_path):
    """Every step passing exits 0."""
    assert ci.run([_step("a", 0), _step("b", 0)], json_path=tmp_path / "ci.json") == 0
