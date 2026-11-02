"""Supported re-score path for stored runs (issue #97)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_dojo_scoring.cli import _cli_rescore
from llm_dojo_scoring.metrics.scorecard_honesty import SCORER_VERSION
from llm_dojo_scoring.scoring.rescore import (
    RescoreError,
    diff_scorecards,
    rescore_file,
    rescore_record,
    rescore_records,
)

CONTRACT_EXPECTED = {
    "document_name": "Service Agreement",
    "parties": ["Acme Corp"],
    "effective_date": "2024-01-01",
    "governing_law": "Delaware",
}


def _extraction_record(**overrides):
    """One already-correct contract row with a deliberately stale headline."""
    record = {
        "doc_id": "doc-1",
        "task": "extraction",
        "doc_class": "contract",
        "expected": dict(CONTRACT_EXPECTED),
        "predicted": dict(CONTRACT_EXPECTED),
        "old_score": 0.25,
        "scorer_version": "0.21.0",
    }
    record.update(overrides)
    return record


def test_rescore_extraction_recomputes_and_bumps_version():
    """A correct row re-scores to 1.0 and carries the current release."""
    out = rescore_record(_extraction_record())
    assert out["score"] == 1.0
    assert out["payload"]["provenance"]["metric_id"] == "pipeline.extraction.overall"
    assert out["provenance"]["scorer_version"] == SCORER_VERSION
    assert out["rescored_from"]["scorer_version"] == "0.21.0"
    assert out["rescored_from"]["score"] == 0.25


def test_rescore_classification_dispatches_by_task():
    """A label task keeps its own metric shape and current provenance."""
    out = rescore_record(
        {
            "doc_id": "doc-2",
            "task": "docclass",
            "expected": ["contract", "contract"],
            "predicted": ["contract", "correspondence"],
        }
    )
    assert out["score"] == 0.5
    assert out["payload"]["kind"] == "docclass"
    assert out["provenance"]["scorer_version"] == SCORER_VERSION


def test_rescore_refuses_a_missing_side():
    """Never reconstruct a prediction from a stored score."""
    with pytest.raises(RescoreError, match="no predicted"):
        rescore_record(
            {"task": "extraction", "doc_class": "contract", "expected": CONTRACT_EXPECTED}
        )
    with pytest.raises(RescoreError, match="no expected"):
        rescore_record(
            {"task": "docclass", "predicted": ["contract"]}
        )


def test_rescore_refuses_serving_records():
    """Timings and hardware counters cannot be reproduced from a card."""
    with pytest.raises(RescoreError, match="serving"):
        rescore_record({"task": "serving", "expected": {}, "predicted": {}})


def test_rescore_output_is_idempotent():
    """Re-running a current output is a no-op, not a missing-evidence error."""
    first = rescore_record(_extraction_record())
    again = rescore_record(first)
    assert again["already_current"] is True
    assert again["score"] == first["score"]
    assert again["payload"] == first["payload"]


def test_rescore_batch_reports_skips_without_shifting_scores():
    """A skipped record is named and does not fabricate a score."""
    result = rescore_records(
        [
            _extraction_record(),
            {"doc_id": "bad", "task": "extraction", "doc_class": "contract"},
        ]
    )
    assert result["n_records"] == 2
    assert result["n_rescored"] == 1
    assert result["n_skipped"] == 1
    assert result["skipped"][0]["doc_id"] == "bad"


def test_diff_scorecards_aligns_by_doc_id_when_a_row_is_skipped():
    """A skipped leading row must not shift every later comparison."""
    before = [
        {"doc_id": "bad", "score": None},
        {"doc_id": "good", "score": 0.25},
    ]
    after = [{"doc_id": "good", "score": 1.0}]
    moves = diff_scorecards(before, after)
    assert moves["n"] == 1
    assert moves["n_changed"] == 1
    assert moves["delta"] == 0.75


def test_rescore_file_joins_dataset_and_writes_jsonl(tmp_path: Path):
    """The CLI-shaped file path joins GT by id and writes one line per row."""
    items = tmp_path / "items.jsonl"
    dataset = tmp_path / "dataset.jsonl"
    out = tmp_path / "out.jsonl"
    items.write_text(
        json.dumps(
            {
                "item_id": "doc-1",
                "ok": True,
                "pred": dict(CONTRACT_EXPECTED),
                "score": 0.25,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    dataset.write_text(
        json.dumps(
            {
                "id": "doc-1",
                "expected_doc_class": "contract",
                "expected_fields": json.dumps(CONTRACT_EXPECTED),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = rescore_file(items, dataset_path=dataset, out_path=out)
    assert result["n_rescored"] == 1
    assert result["records"][0]["score"] == 1.0
    written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert written[0]["provenance"]["scorer_version"] == SCORER_VERSION


def test_rescore_cli_prints_a_summary(tmp_path: Path, capsys):
    """The console entry point returns 0 and names the output file."""
    items = tmp_path / "items.jsonl"
    items.write_text(
        json.dumps(
            {
                "doc_id": "doc-1",
                "task": "docclass",
                "expected": ["contract"],
                "predicted": ["contract"],
                "score": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"
    code = _cli_rescore(["--items", str(items), "--task", "docclass", "--out", str(out), "--compare"])
    assert code == 0
    text = capsys.readouterr().out
    assert "1 re-scored" in text
    assert "moves:" in text
    assert out.is_file()
