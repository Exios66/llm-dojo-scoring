"""Unlabelled-value rates, breakdowns and their ScoreRecord form."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.grounding.audit import UnlabelledValueAudit
from llm_dojo_scoring.grounding.summary import (
    METRIC_IDS,
    GroundingCounts,
    grounding_score_records,
    summarize_grounding,
)
from llm_dojo_scoring.metrics.registry import MetricTier, get_registry


def _audit(verdict: str, doc_class: str = "insurance_claim", field: str = "insurer") -> UnlabelledValueAudit:
    """A minimal audit record with the given verdict, class and field."""
    return UnlabelledValueAudit(
        run_id="r1", doc_id="d1", doc_class=doc_class, doc_subclass=None, field=field,
        field_type="name", value="x", item_index=None, verdict=verdict, coverage=None,
        gt_status="absent", doc_text_sha256=None, extractor=None, audited_at=0.0,
    )


def test_not_found_rate_excludes_unverifiable():
    """Unverifiable values are left out of the hallucination rate's denominator."""
    counts = GroundingCounts(grounded=3, not_found=1, unverifiable=4)
    assert counts.not_found_rate == 0.25
    assert counts.unverifiable_rate == 0.5
    assert counts.n_audited == 8


@pytest.mark.parametrize("audits", [[], [_audit("unverifiable"), _audit("unverifiable")]])
def test_rates_are_none_without_a_denominator(audits):
    """No checkable value means no rate, not a perfect 0.0."""
    summary = summarize_grounding(audits)
    assert summary.overall.not_found_rate is None
    if not audits:
        assert summary.overall.unverifiable_rate is None


def test_breakdowns_add_up_to_the_overall_counts():
    """Per-class and per-field counts partition the run."""
    audits = [
        _audit("grounded"), _audit("not_found", field="adjuster"),
        _audit("unverifiable", doc_class="correspondence", field="sender"),
        _audit("grounded", doc_class="correspondence", field="sender"),
    ]
    summary = summarize_grounding(audits)
    assert summary.overall == GroundingCounts(2, 1, 1)
    assert sum(c.n_audited for c in summary.by_class.values()) == 4
    assert sum(c.n_audited for c in summary.by_field.values()) == 4
    assert summary.by_field[("insurance_claim", "adjuster")] == GroundingCounts(0, 1, 0)
    assert "correspondence.sender" in summary.as_dict()["by_field"]
    assert summary.as_dict()["schema_version"] == 1


def test_score_records_use_registered_ids_and_tiers():
    """Every emitted id is registered with the tier the spec fixes."""
    registry = get_registry()
    expected_tiers = {
        "grounding_not_found_rate": MetricTier.CORE,
        "grounding_unverifiable_rate": MetricTier.DEEP,
        "grounding_n_audited": MetricTier.LOG,
    }
    assert set(METRIC_IDS) == set(expected_tiers)
    records = grounding_score_records(summarize_grounding([_audit("grounded")]), agent="specialist")
    for record in records:
        assert registry.get(record.metric).tier == expected_tiers[record.metric]


def test_score_records_order_scope_and_denominator():
    """Run records first, then class, then field; each carries its denominator."""
    summary = summarize_grounding([_audit("grounded"), _audit("not_found"), _audit("unverifiable")])
    records = grounding_score_records(summary, agent="specialist", run_id="r1")
    assert [r.metadata["scope"] for r in records] == ["run"] * 3 + ["class"] * 3 + ["field"] * 3
    run_rate = records[0]
    assert (run_rate.metric, run_rate.value, run_rate.metadata["denominator"]) == (
        "grounding_not_found_rate", 0.5, 2)
    assert records[-1].metadata == {"scope": "field", "doc_class": "insurance_claim",
                                    "field": "insurer", "denominator": 3}
    assert all(r.run_id == "r1" and r.agent == "specialist" for r in records)


def test_unknown_verdict_raises_instead_of_undercounting():
    """A record with a verdict outside VERDICTS is an error, not a silent drop."""
    with pytest.raises(ValueError, match="unknown grounding verdict"):
        summarize_grounding([_audit("maybe")])
