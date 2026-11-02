"""Headline scope (issue #95): a partial or MAUD-only headline is never unflagged.

The merger headline was MAUD answer accuracy alone, yet it sat in the same
grid column as classes scored on their whole field map. These tests pin the
scope labels on the honest aggregate, the grid rows and the Markdown report.
"""

from __future__ import annotations

import pytest

from llm_dojo_scoring.analysis.grid import build_grid_report, specialist_grid_rows
from llm_dojo_scoring.metrics.scorecard_honesty import (
    aggregate_quality_honest,
    headline_scope,
)
from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES

CORRESPONDENCE_GT_FIELDS = ("intent", "sender", "communication_date")


def _full(doc_class):
    """Field scores covering every live field of *doc_class*."""
    return {field: 1.0 for field in DEFAULT_FIELD_TYPES[doc_class]}


def _grid_doc(specialist, score, field_scores=None, **kw):
    """One grid document with optional per-field scores."""
    doc = {"experiment": "e1", "specialist": specialist, "score": score, "ok": True}
    if field_scores is not None:
        doc["field_scores"] = field_scores
    doc.update(kw)
    return doc


def test_merger_scored_on_maud_alone_is_maud_only():
    """A merger headline from ``maud_clauses`` alone is labelled MAUD accuracy."""
    scope = headline_scope("merger_agreement", {"maud_clauses": 12})
    assert scope["headline_scope"] == "maud_only"
    assert "MAUD" in scope["headline_label"]
    assert scope["scored_fields"] == {"maud_clauses": 12}
    assert "maud_clauses" not in scope["unscored_fields"]
    assert len(scope["unscored_fields"]) == len(DEFAULT_FIELD_TYPES["merger_agreement"]) - 1


def test_correspondence_with_three_gt_fields_is_partial():
    """Correspondence scored on 3 of its live fields says so (#94/#95)."""
    scope = headline_scope("correspondence", list(CORRESPONDENCE_GT_FIELDS))
    n_live = len(DEFAULT_FIELD_TYPES["correspondence"])
    assert scope["headline_scope"] == "partial"
    assert scope["headline_label"].startswith(f"3 of {n_live} fields")
    assert scope["field_coverage"] == pytest.approx(3 / n_live, abs=1e-6)


def test_full_field_map_is_full():
    """Every live field scored at least once is a full headline."""
    scope = headline_scope("contract", list(DEFAULT_FIELD_TYPES["contract"]))
    assert scope["headline_scope"] == "full"
    assert scope["unscored_fields"] == []


def test_no_fields_or_unknown_class_has_no_scope():
    """Nothing scored, or a class without a field map, makes no scope claim."""
    assert headline_scope("contract", {})["headline_scope"] is None
    assert headline_scope("contract", {"parties": 0})["headline_scope"] is None
    assert headline_scope("not_a_class", ["x"])["headline_scope"] is None


def test_honest_aggregate_reports_scope_only_when_asked():
    """``doc_class=`` adds the population keys; the legacy shape is unchanged."""
    rows = [
        {"overall_score": 0.5, "field_scores": {"maud_clauses": 0.5}},
        {"overall_score": 0.7, "extraction": {"field_scores": {"maud_clauses": 0.7}}},
        {"status": "unscorable", "field_scores": {"parties": 0.0}},
    ]
    legacy = aggregate_quality_honest(rows)
    assert "headline_scope" not in legacy
    out = aggregate_quality_honest(rows, doc_class="merger_agreement")
    assert out["headline_scope"] == "maud_only"
    assert out["scored_fields"] == {"maud_clauses": 2}  # unscorable row excluded
    assert out["quality_mean"] == legacy["quality_mean"]


def test_honest_aggregate_without_field_data_stays_legacy():
    """Rows without ``field_scores`` make no scope claim even with ``doc_class``."""
    out = aggregate_quality_honest([{"overall_score": 0.4}], doc_class="contract")
    assert "headline_scope" not in out


def test_grid_rows_flag_maud_only_and_partial_specialists():
    """Grid rows carry the scope for a specialist name or an explicit class."""
    rows = specialist_grid_rows(
        [
            _grid_doc("merger_agreement_specialist", 0.9, {"maud_clauses": 0.9}),
            _grid_doc("correspondence", 0.6, dict.fromkeys(CORRESPONDENCE_GT_FIELDS, 0.6)),
            _grid_doc("contracts_x", 0.8, _full("contract"), doc_class="contract"),
            _grid_doc("legacy", 0.5),
        ]
    )
    by_name = {r["specialist"]: r for r in rows}
    assert by_name["merger_agreement_specialist"]["headline_scope"] == "maud_only"
    assert by_name["correspondence"]["headline_scope"] == "partial"
    assert by_name["contracts_x"]["headline_scope"] == "full"
    assert by_name["legacy"]["headline_scope"] is None


def test_grid_scope_reads_nested_scores_and_explicit_lists():
    """``scores.field_scores`` and ``scored_fields`` both feed the scope."""
    rows = specialist_grid_rows(
        [
            _grid_doc("merger_agreement", 0.9, scores={"field_scores": {"maud_clauses": 1.0}}),
            _grid_doc("merger_agreement", 0.7, scored_fields=["maud_clauses"]),
        ]
    )
    assert rows[0]["headline_scope"] == "maud_only"
    assert rows[0]["scored_fields"] == {"maud_clauses": 2}


def test_grid_report_marks_and_footnotes_non_comparable_headlines():
    """The Markdown table cannot show a MAUD-only score unflagged."""
    md = build_grid_report(
        documents=[
            _grid_doc("merger_agreement", 0.9, {"maud_clauses": 0.9}),
            _grid_doc("correspondence", 0.6, dict.fromkeys(CORRESPONDENCE_GT_FIELDS, 0.6)),
            _grid_doc("contract", 0.8, _full("contract")),
        ],
        experiments=[{"name": "e1"}],
    )
    assert "0.900 †" in md
    assert "0.600 ‡" in md
    assert "0.800 |" in md
    assert "† **merger_agreement**: MAUD answers only" in md
    assert "‡ **correspondence**: 3 of" in md
    assert "Not comparable with full-field headlines." in md


def test_off_map_fields_do_not_claim_scope():
    """Scored fields outside the live map are reported, never counted as scope."""
    only_junk = headline_scope("merger_agreement", {"junk": 2})
    assert only_junk["headline_scope"] is None
    assert only_junk["off_map_fields"] == ["junk"]
    assert only_junk["field_coverage"] == 0.0
    mixed = headline_scope("merger_agreement", {"maud_clauses": 3, "junk": 1})
    assert mixed["headline_scope"] == "maud_only"
    assert mixed["off_map_fields"] == ["junk"]
    assert mixed["scored_fields"] == {"junk": 1, "maud_clauses": 3}
    n_live = len(DEFAULT_FIELD_TYPES["merger_agreement"])
    assert mixed["field_coverage"] == pytest.approx(1 / n_live, abs=1e-6)
    assert "junk" not in mixed["unscored_fields"]
    assert headline_scope("contract", list(DEFAULT_FIELD_TYPES["contract"]))["off_map_fields"] == []


def test_field_score_lookup_skips_empty_holders():
    """An empty top-level ``field_scores`` does not hide nested data (aggregate and grid)."""
    row = {"overall_score": 0.5, "field_scores": {}, "scores": {"field_scores": {"maud_clauses": 0.5}}}
    out = aggregate_quality_honest([row], doc_class="merger_agreement")
    assert out["scored_fields"] == {"maud_clauses": 1}
    grid = specialist_grid_rows(
        [_grid_doc("merger_agreement", 0.5, {}, extraction={"field_scores": {"maud_clauses": 0.5}})]
    )
    assert grid[0]["scored_fields"] == {"maud_clauses": 1}
    explicit = specialist_grid_rows(
        [_grid_doc("merger_agreement", 0.5, {"parties": 1.0}, scored_fields=["maud_clauses"])]
    )
    assert explicit[0]["scored_fields"] == {"maud_clauses": 1}


def test_grid_footnotes_dedupe_by_specialist_and_scope():
    """The same specialist flagged ``†`` and ``‡`` in two experiments gets both notes."""
    md = build_grid_report(
        documents=[
            _grid_doc("merger_agreement", 0.9, {"maud_clauses": 0.9}, experiment="e1"),
            _grid_doc("merger_agreement", 0.9, {"maud_clauses": 0.9, "parties": 0.9}, experiment="e2"),
        ],
        experiments=[{"name": "e1"}, {"name": "e2"}],
    )
    assert "0.900 †" in md
    assert "0.900 ‡" in md
    assert "† **merger_agreement**" in md
    assert "‡ **merger_agreement**" in md


def test_grid_row_makes_no_scope_claim_when_some_docs_lack_fields():
    """A headline mixing documents with unknown fields is not labelled MAUD-only."""
    rows = specialist_grid_rows(
        [
            _grid_doc("merger_agreement", 0.9, {"maud_clauses": 0.9}),
            _grid_doc("merger_agreement", 0.5),
        ]
    )
    assert rows[0]["headline_scope"] is None
    assert rows[0]["scored_fields"] is None
    assert rows[0]["unscored_fields"] is None
