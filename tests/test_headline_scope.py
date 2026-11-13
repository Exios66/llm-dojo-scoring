"""Headline scope (issue #95): a partial or MAUD-only headline is never unflagged.

The merger headline was MAUD answer accuracy alone, yet it sat in the same
grid column as classes scored on their whole field map. These tests pin the
scope labels on the honest aggregate, the grid rows and the Markdown report.
"""

from __future__ import annotations

import pytest

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


def test_nothing_scored_has_no_scope():
    """Nothing scored (no per-document context) makes no scope claim."""
    assert headline_scope("contract", {})["headline_scope"] is None
    assert headline_scope("contract", {"parties": 0})["headline_scope"] is None
    assert headline_scope("not_a_class", [])["headline_scope"] is None


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


# --- adversarial findings -------------------------------------------------


def test_aggregate_unknown_when_some_scored_docs_lack_fields():
    """The honest aggregate reports 'field data for k of n' rather than a scope over a subset."""
    rows = [{"overall_score": 0.5, "field_scores": {"maud_clauses": 0.5}}] + [
        {"overall_score": 0.5} for _ in range(99)
    ]
    out = aggregate_quality_honest(rows, doc_class="merger_agreement")
    assert out["headline_scope"] == "unknown"
    assert out["headline_label"] == "field data for 1 of 100 scored documents"
    assert aggregate_quality_honest(rows, doc_class="nonsense")["headline_scope"] == "unknown"


def test_headline_scope_rejects_str_and_skips_bad_counts():
    """A bare string is a TypeError; non-numeric or non-positive counts are skipped."""
    with pytest.raises(TypeError):
        headline_scope("contract", "parties")
    out = headline_scope(
        "contract", {"parties": "3", "document_name": None, "x": -1, "y": float("nan"), "z": True}
    )
    assert out["headline_scope"] is None
    assert out["scored_fields"] == {}
    ok = headline_scope("merger_agreement", {"maud_clauses": 2.0, "parties": "n/a"})
    assert ok["headline_scope"] == "maud_only"
    assert ok["scored_fields"] == {"maud_clauses": 2}
    assert headline_scope("contract", {"parties": 1}, n_docs=1)["headline_scope"] == "partial"
    assert headline_scope("contract", {}, n_docs=1)["headline_scope"] == "unknown"
    assert headline_scope("contract", ["parties"], n_docs=1, n_docs_with_fields=1)["headline_scope"] == "partial"
    assert headline_scope("contract", set(DEFAULT_FIELD_TYPES["contract"]))["headline_scope"] == "full"


def test_aggregate_field_score_lookup_skips_empty_holders():
    """An empty top-level ``field_scores`` does not hide the nested ``scores.field_scores``."""
    row = {"overall_score": 0.5, "field_scores": {}, "scores": {"field_scores": {"maud_clauses": 0.5}}}
    out = aggregate_quality_honest([row], doc_class="merger_agreement")
    assert out["scored_fields"] == {"maud_clauses": 1}
