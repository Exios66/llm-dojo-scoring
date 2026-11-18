"""Risk-coverage curve, operating point and per-slot decision summary (analysis/risk_coverage.py)."""

import pytest

from llm_dojo_scoring.analysis.risk_coverage import operating_point, risk_coverage_curve, slot_decision_summary

ROWS = [
    {"score": 0.95, "wrong": False},
    {"score": 0.90, "wrong": False},
    {"score": 0.80, "wrong": True},
    {"score": 0.60, "wrong": False},
    {"score": 0.40, "wrong": True},
    {"score": None, "wrong": False},   # scorable, no score: always reviewed
    {"score": 0.99, "wrong": None},    # unscorable: out of every rate
]


def _point(curve, t):
    """The curve point at cutoff ``t``."""
    return next(p for p in curve["points"] if p["threshold"] == t)


def test_counts_and_default_thresholds():
    """Rows are split into scorable, unscorable and unscored; cutoffs default to every score plus 1.01."""
    curve = risk_coverage_curve(ROWS)
    assert (curve["n"], curve["n_scorable"], curve["n_unscorable"], curve["n_no_score"]) == (7, 6, 1, 1)
    assert [p["threshold"] for p in curve["points"]] == [0.4, 0.6, 0.8, 0.9, 0.95, 1.01]


def test_rates_at_a_cutoff():
    """Coverage, review rate, wrong-archive rate (among archived) and per 1,000 at one cutoff."""
    p = _point(risk_coverage_curve(ROWS), 0.8)
    assert p["archived"] == 3 and p["wrong_archives"] == 1
    assert p["coverage"] == pytest.approx(0.5) and p["review_rate"] == pytest.approx(0.5)
    assert p["wrong_archive_rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert p["wrong_per_1000"] == pytest.approx(166.667)
    assert p["wrong_archive_upper95"] > p["wrong_archive_rate"]


def test_lowest_cutoff_archives_every_scored_row_and_the_top_archives_none():
    """The lowest cutoff archives every scored row; the top one archives none."""
    curve = risk_coverage_curve(ROWS)
    low, top = _point(curve, 0.4), _point(curve, 1.01)
    assert low["archived"] == 5 and low["review_rate"] == pytest.approx(1 / 6, abs=1e-6)
    assert top["archived"] == 0 and top["review_rate"] == 1.0 and top["wrong_archive_rate"] is None
    assert top["wrong_per_1000"] == 0.0


def test_aurc_rewards_a_ranking_that_archives_the_right_rows_first():
    """A ranking that archives right rows first has the lower area."""
    perfect = [{"score": 0.9, "wrong": False}, {"score": 0.8, "wrong": False}, {"score": 0.1, "wrong": True}]
    reversed_ = [{"score": 0.1, "wrong": False}, {"score": 0.2, "wrong": False}, {"score": 0.9, "wrong": True}]
    # Coverage 1/3 -> 2/3 -> 1: risks 0, 0, 1/3 against 1, 1/2, 1/3.
    assert risk_coverage_curve(perfect)["aurc"] == pytest.approx(1 / 18, abs=1e-5)
    assert risk_coverage_curve(reversed_)["aurc"] == pytest.approx((0.75 + 5 / 12) / 3, abs=1e-5)


def test_explicit_thresholds_and_hostile_values():
    """Booleans, NaN and out-of-range scores never clear a cutoff; bad cutoffs are dropped."""
    curve = risk_coverage_curve(
        [{"score": True, "wrong": False}, {"score": float("nan"), "wrong": True}, {"score": 1.5, "wrong": False},
         "junk", {"wrong": "yes"}],
        thresholds=[0.5, float("inf"), "x", True],
    )
    assert curve["n_no_score"] == 3 and curve["n_unscorable"] == 2
    assert [p["threshold"] for p in curve["points"]] == [0.5]
    assert curve["points"][0]["archived"] == 0


def test_empty_input():
    """No rows: one empty point and no area."""
    curve = risk_coverage_curve([])
    assert curve["n"] == 0 and curve["aurc"] is None
    assert curve["points"] == [{"threshold": 1.01, "archived": 0, "coverage": None, "review_rate": None,
                                "wrong_archives": 0, "wrong_archive_rate": None, "wrong_archive_upper95": None,
                                "wrong_per_1000": None}]


def test_operating_point_holds_the_upper_bound_to_the_budget():
    """The operating point holds the Wilson upper bound (or the exact rate) to the budget."""
    rows = [{"score": i / 100, "wrong": i < 5} for i in range(100)]
    curve = risk_coverage_curve(rows)
    exact = operating_point(curve, max_wrong_archive_rate=0.0, use_upper=False)
    assert exact["threshold"] == 0.05 and exact["review_rate"] == pytest.approx(0.05)
    upper = operating_point(curve, max_wrong_archive_rate=0.06)
    assert upper["wrong_archive_upper95"] <= 0.06 and upper["review_rate"] < 0.5
    assert upper["threshold"] < exact["threshold"]  # the budget buys back review
    assert operating_point(curve, max_wrong_archive_rate=-1) is None


def test_slot_summary_reads_mailroom_outcomes():
    """Per-slot action rates and the pipeline's review and wrong-archive rates."""
    records = [
        {"final_stage": "archived", "wrong_archive": False,
         "decision_slot_marks": ["seen:archive_gate"],
         "decision_slot_outcomes": {"archive_gate": {"action": "agree"}}},
        {"final_stage": "review", "decision_slot_marks": ["seen:archive_gate", "park:archive_gate"],
         "decision_slot_outcomes": {"archive_gate": {"action": "park", "route": "human_review"}}},
        {"final_stage": "archived", "wrong_archive": True,
         "decision_slot_marks": ["seen:archive_gate", "seen:arbiter_veto"],
         "decision_slot_outcomes": {"archive_gate": {"action": "capped"}, "arbiter_veto": {"action": "weird"}}},
        {"final_stage": "archived", "wrong_archive": None},
        "junk",
    ]
    out = slot_decision_summary(records)
    pipe = out["pipeline"]
    assert (pipe["n"], pipe["archived"], pipe["n_scorable_archives"], pipe["wrong_archives"]) == (4, 3, 2, 1)
    assert pipe["review_rate"] == pytest.approx(0.25)
    assert pipe["wrong_archive_rate"] == pytest.approx(0.5)
    assert pipe["wrong_per_1000"] == pytest.approx(333.333)
    gate = out["slots"]["archive_gate"]
    assert gate["n_seen"] == 3 and gate["actions"] == {"agree": 1, "capped": 1, "park": 1}
    assert gate["park_rate"] == pytest.approx(1 / 3, abs=1e-6) and gate["release_rate"] == 0.0
    assert out["slots"]["arbiter_veto"]["actions"] == {"none": 1}


def test_slot_summary_empty():
    """No records: empty rates, no slots."""
    out = slot_decision_summary([])
    assert out == {"pipeline": {"n": 0, "archived": 0, "review_rate": None, "n_scorable_archives": 0,
                                "wrong_archives": 0, "wrong_archive_rate": None, "wrong_archive_upper95": None,
                                "wrong_per_1000": None}, "slots": {}}
