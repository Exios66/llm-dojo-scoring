"""Regressions for the PR #104 review findings (calibration, enum hints,
reviewer cost / operating points, rescore, registry scope, consumer audit)."""

from __future__ import annotations

import ast
import json
import random

import numpy as np
import pytest

from conftest import load_script
from llm_dojo_scoring.analysis.calibration import (
    clopper_pearson_upper,
    cutoff_for_precision,
    required_samples,
)
from llm_dojo_scoring.metrics.registry import load_registry
from llm_dojo_scoring.metrics.score_changelog import SCORE_CHANGELOG
from llm_dojo_scoring.metrics.scorecard_honesty import SCORER_VERSION
from llm_dojo_scoring.schemas.scored_enums import SCORED_ENUM_FIELDS, enum_hint_violations
from llm_dojo_scoring.scoring.rescore import rescore_record
from llm_dojo_scoring.scoring.reviewer import (
    ReviewRecord,
    _operating_points,
    score_review_lane,
)


def test_counts_accept_numpy_integers_but_not_bool():
    """NumPy / pandas counts work; bools are still rejected."""
    assert clopper_pearson_upper(np.int64(1), np.int64(20)) == clopper_pearson_upper(1, 20)
    assert required_samples(np.int32(0), risk=0.1) == required_samples(0, risk=0.1)
    with pytest.raises(TypeError):
        clopper_pearson_upper(True, 20)


def test_precision_cutoff_is_not_rounded_below_an_excluded_error():
    """A rounded cutoff must not admit the error the precision excluded."""
    out = cutoff_for_precision([0.8000004, 0.8000001], [True, False], 1.0)
    assert out["cutoff"] == 0.8000004
    assert out["precision"] == 1.0


def test_empty_vendored_hints_report_every_scored_field():
    """Omitting a scored field is a violation, not a pass."""
    problems = enum_hint_violations("correspondence", {})
    for field in SCORED_ENUM_FIELDS["correspondence"]:
        assert any(f"correspondence.{field}: scored enum field missing" in p for p in problems)


def _row(**overrides):
    """One reviewer row mapping with overrides."""
    values = {
        "doc_id": "d",
        "expected_doc_type": "contract",
        "sorter_doc_type": "contract",
        "reviewer_doc_type": "contract",
        "reviewer_confidence": 0.9,
        "route": "extract",
        "cutoff": 0.5,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_cost_is_unpriced(bad):
    """NaN / inf costs never reach the totals or the strict JSON card."""
    record = ReviewRecord.from_mapping(_row(cost_usd=bad))
    assert record.cost_usd is None
    card = score_review_lane([_row(doc_id="a", cost_usd=0.01), _row(doc_id="b", cost_usd=bad)])
    assert card["cost"]["complete"] is False
    json.dumps(card, allow_nan=False)


def test_risk_cutoff_matches_brute_force():
    """The single-pass cutoff equals the lowest inclusive cutoff that clears risk."""
    rng = random.Random(7)
    rows = [
        ReviewRecord.from_mapping(
            _row(
                doc_id=f"d{i}",
                reviewer_confidence=round(rng.random(), 2),
                expected_doc_type="contract" if rng.random() < 0.97 else "insurance_claim",
            )
        )
        for i in range(400)
    ]
    out = _operating_points(rows, target_accuracy=0.95, risk=0.05, confidence=0.95)
    pairs = [(r.reviewer_confidence, r.expected_doc_type == "contract") for r in rows]
    expected = None
    for cutoff in sorted({c for c, _ in pairs}):
        accepted = [ok for c, ok in pairs if c >= cutoff]
        upper = clopper_pearson_upper(sum(not ok for ok in accepted), len(accepted))
        if upper is not None and upper <= 0.05:
            expected = cutoff
            break
    assert out["contract"]["risk_cutoff"] == expected


def _reviewer_record():
    """A stored reviewer record from an older release."""
    return {"doc_id": "r", "task": "reviewer", "scorer_version": "0.25.0",
            "review_records": [_row(reviewer_confidence=0.95)]}


def test_rescore_reviewer_keeps_canonical_metric_id():
    """Caller provenance cannot relabel the reviewer lane's metric."""
    out = rescore_record(_reviewer_record(), provenance={"metric_id": "other.metric", "split": "test"})
    assert out["provenance"]["metric_id"] != "other.metric"
    assert out["provenance"]["split"] == "test"


def test_rescore_current_reviewer_record_keeps_its_headline():
    """Re-running a current reviewer output keeps class_accuracy as the score."""
    first = rescore_record(_reviewer_record())
    assert first["provenance"]["scorer_version"] == SCORER_VERSION
    again = rescore_record(first)
    assert again["already_current"] is True
    assert again["score"] == first["score"] == 1.0


def test_rescore_transcription_accepts_scalar_text():
    """Scalar-text tasks are not forced through the array parser."""
    out = rescore_record({"task": "transcription", "expected": "hello world", "predicted": "hello world"})
    assert out["payload"]["task"] == "transcription"


def test_reviewer_metrics_scoped_to_sorter_reviewer():
    """Reviewer metrics do not leak into the sorter / judge bundles."""
    registry = load_registry()
    reviewer = [m for name, m in registry.metrics.items() if name.startswith("reviewer_")]
    assert reviewer
    for metric in reviewer:
        agents = set(getattr(metric, "applicable_agents", None) or metric.get("applicable_agents"))
        assert agents == {"sorter_reviewer"}


def test_v025_changelog_names_no_document_label_metrics():
    """0.25.0 moved subclass scores only."""
    entry = next(e for e in SCORE_CHANGELOG if e["version"] == "0.25.0")
    assert "pipeline.classification.accuracy" not in entry["metric_ids"]
    assert "pipeline.classification.f1_macro" not in entry["metric_ids"]


def _collect(source):
    """Scan one consumer source string into a fresh surface."""
    audit = load_script("audit_consumer_surface")
    surface = audit.Surface(index=audit.PackageIndex())
    surface.collect_file("MAIL", "src/x.py", ast.parse(source))
    return surface


def test_audit_pins_keyword_dispatch_literals():
    """``get_suite(name="sorter")`` pins the literal, not ``<no-argument>``."""
    surface = _collect(
        "from llm_dojo_scoring import get_suite, score_task\n"
        "get_suite(name='sorter')\n"
        "score_task(task='docclass', expected=[], predicted=[])\n"
    )
    assert "sorter" in surface.dispatch_literals["get_suite"]
    assert "docclass" in surface.dispatch_literals["score_task"]
    assert not surface.dispatch_dynamic["get_suite"]


def test_audit_pins_star_import_names():
    """A wildcard import pins every exported name instead of none."""
    import llm_dojo_scoring as dojo

    surface = _collect("from llm_dojo_scoring import *\n")
    assert set(dojo.__all__) <= set(surface.top_level)


def test_audit_defined_in_names_the_defining_module():
    """A re-exported attribute records its defining module, not the import path."""
    data = json.loads(
        (load_script("audit_consumer_surface").FIXTURE_PATH).read_text(encoding="utf-8")
    )
    serving = data["modules"]["analysis.serving"]["attrs"]
    assert serving["estimate_cost"]["defined_in"] == "analysis.cost"


# --- second review round ---------------------------------------------------


def test_non_finite_primary_cost_falls_back_to_finite_alternative():
    """A NaN ``cost_usd`` must not hide a finite ``cost``."""
    from llm_dojo_scoring.scoring.reviewer import _cost

    assert _cost(float("nan"), 0.02) == 0.02
    assert _cost(float("inf"), None) is None


def test_risk_cutoff_is_exact():
    """The returned cutoff is the value the bound was checked at, unrounded."""
    rows = [
        ReviewRecord.from_mapping(_row(doc_id=f"d{i}", reviewer_confidence=0.8000004))
        for i in range(80)
    ] + [
        ReviewRecord.from_mapping(
            _row(doc_id="bad", reviewer_confidence=0.8000001, expected_doc_type="insurance_claim")
        )
    ]
    out = _operating_points(rows, target_accuracy=0.95, risk=0.05, confidence=0.95)
    assert out["contract"]["risk_cutoff"] == 0.8000004


@pytest.mark.parametrize("task", ["transcription", "wer", "cer"])
def test_rescore_transcription_aliases_take_raw_path_with_headline(task):
    """``wer`` / ``cer`` resolve to transcription and score word accuracy."""
    out = rescore_record({"task": task, "expected": "hello world", "predicted": "hello world"})
    assert out["payload"]["task"] == "transcription"
    assert out["score"] == 1.0


def test_rescore_transcription_decodes_serialized_batches():
    """A stored JSON array is still scored as a batch of documents."""
    out = rescore_record(
        {
            "task": "transcription",
            "expected": json.dumps(["a b", "c d"]),
            "predicted": ("a b", "c x"),
        }
    )
    assert out["payload"]["n"] == 2
    assert out["score"] == 0.75


def test_rescore_maud_clause_alias_takes_raw_path():
    """``maud_clause`` resolves to maud_extraction and is not forced to an array."""
    out = rescore_record({"task": "maud_clause", "expected": {}, "predicted": {}})
    assert out["task"] == "maud_clause"
    assert "maud_question_accuracy" in out["payload"]


def test_audit_star_import_binds_dispatch_aliases():
    """``from ... import *`` then ``get_suite("sorter")`` pins the literal."""
    surface = _collect(
        "from llm_dojo_scoring.scoring.suites import *\n"
        "get_suite('sorter')\n"
    )
    assert "sorter" in surface.dispatch_literals["get_suite"]


def test_freeze_goldens_stages_each_write_uniquely(tmp_path, monkeypatch):
    """Each write gets its own staging file; no shared ``.tmp`` path remains."""
    module = load_script("freeze_goldens")
    target = tmp_path / "scores.json"
    seen = []
    real_replace = module.os.replace

    def spy(src, dst):
        """Record each staging path, then replace for real."""
        seen.append(src)
        real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", spy)
    module._atomic_write(target, "one")
    module._atomic_write(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert len(set(map(str, seen))) == 2
    assert list(tmp_path.iterdir()) == [target]
