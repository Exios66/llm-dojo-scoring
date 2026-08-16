import json
from pathlib import Path

import pytest

from llm_dojo_scoring.experiment import (
    append_experiment,
    dotted_get,
    git_snapshot,
    load_records,
    record_date,
)


def test_append_and_load(tmp_path):
    log = tmp_path / "log.jsonl"
    append_experiment({"experiment_name": "a", "n_rows": 10}, log)
    append_experiment({"experiment_name": "b", "n_rows": 20}, log)
    records = load_records(log)
    assert [r["experiment_name"] for r in records] == ["a", "b"]
    assert all("timestamp" in r for r in records)


def test_dotted_get():
    record = {"scores": {"sorter": {"subtype_accuracy": 0.9}}}
    assert dotted_get(record, "scores.sorter.subtype_accuracy") == 0.9
    assert dotted_get(record, "missing.path") is None
    assert dotted_get(record, "missing.path", 42) == 42


def test_record_date():
    assert record_date({"timestamp": "2026-08-15T12:00:00+00:00"}).isoformat() == "2026-08-15T00:00:00"
    assert record_date({"timestamp": None}) is None


def test_git_snapshot_runs():
    snap = git_snapshot()
    assert "commit" in snap and "dirty" in snap