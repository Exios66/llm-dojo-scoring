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
         {"score": 10 ** 400, "wrong": False}, "junk", {"wrong": "yes"}],
        thresholds=[0.5, float("inf"), "x", True, 10 ** 400],
    )
    assert curve["n_no_score"] == 4 and curve["n_unscorable"] == 2
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


def test_slot_summary_counts_unverified_approval_checks():
    """llm-mailroom's approval checks record ``unverified`` when the gate cannot confirm an approval."""
    records = [
        {"final_stage": "archived", "wrong_archive": True,
         "decision_slot_outcomes": {"judge_check": {"action": "unverified"}}},
        {"final_stage": "review", "wrong_archive": None,
         "decision_slot_outcomes": {"judge_check": {"action": "park", "route": "human_review"}},
         "decision_slot_marks": ["seen:judge_check", "park:judge_check"]},
    ]
    slot = slot_decision_summary(records)["slots"]["judge_check"]
    assert slot["actions"] == {"park": 1, "unverified": 1}
    assert slot["park_rate"] == 0.5


def test_slot_summary_empty():
    """No records: empty rates, no slots."""
    out = slot_decision_summary([])
    assert out == {"pipeline": {"n": 0, "archived": 0, "reviewed": 0, "other": 0, "review_rate": None, "n_scorable_archives": 0,
                                "wrong_archives": 0, "wrong_archive_rate": None, "wrong_archive_upper95": None,
                                "wrong_per_1000": None}, "slots": {}}


def test_slot_summary_counts_parks_from_the_durable_marks():
    """A park whose outcome was cleared (a person resolved it) still counts as the slot's park."""
    records = [
        {"final_stage": "archived", "wrong_archive": False,
         "decision_slot_marks": ["seen:archive_gate", "park:archive_gate"], "decision_slot_outcomes": {}},
        {"final_stage": "archived", "wrong_archive": False,
         "decision_slot_marks": ["seen:archive_gate", "release:archive_gate"],
         "decision_slot_outcomes": {"archive_gate": {"action": "agree"}}},
    ]
    gate = slot_decision_summary(records)["slots"]["archive_gate"]
    assert gate["actions"] == {"park": 1, "release": 1}
    assert gate["park_rate"] == 0.5 and gate["release_rate"] == 0.5


def test_slot_summary_keeps_crashes_out_of_the_review_rate():
    """A crashed document is neither archived nor reviewed, as the sandbox slice gate counts it."""
    records = [{"final_stage": "crashed"}, {"final_stage": "review"},
               {"final_stage": "archived", "wrong_archive": True}, {"final_stage": "archived", "wrong_archive": False}]
    pipe = slot_decision_summary(records)["pipeline"]
    assert (pipe["reviewed"], pipe["other"], pipe["review_rate"]) == (1, 1, 0.25)
    assert pipe["wrong_per_1000"] == pytest.approx(333.333)  # 1 wrong over 2 scorable archives + 1 reviewed


def test_slot_summary_reads_final_stage_from_a_dumped_run_record():
    """A RunRecord model dump nests final_stage under actual; the top-level key wins when present."""
    records = [{"actual": {"final_stage": "archived"}, "wrong_archive": True},
               {"actual": {"final_stage": "review"}},
               {"final_stage": "review", "actual": {"final_stage": "archived"}}]
    pipe = slot_decision_summary(records)["pipeline"]
    assert (pipe["archived"], pipe["reviewed"], pipe["other"]) == (1, 2, 0)


def test_observed_operating_point_compares_the_unrounded_rate():
    """1 wrong of 3 archived is 0.333...: over a 0.333333 budget, within 0.34."""
    curve = risk_coverage_curve([{"score": 0.9, "wrong": True}, {"score": 0.8, "wrong": False},
                                 {"score": 0.7, "wrong": False}], thresholds=[0.7, 1.01])
    # The archive-nothing point has no rate, so nothing fits the tighter budget.
    assert operating_point(curve, max_wrong_archive_rate=0.333333, use_upper=False) is None
    assert operating_point(curve, max_wrong_archive_rate=0.34, use_upper=False)["threshold"] == 0.7


def test_slot_summary_uses_the_later_mark_when_a_slot_both_parked_and_released():
    """A later release mark wins, including after the outcome was cleared; a later park mark wins too."""
    records = [
        {"final_stage": "archived", "wrong_archive": False,
         "decision_slot_marks": ["seen:archive_gate", "park:archive_gate", "release:archive_gate"],
         "decision_slot_outcomes": {}},
        {"final_stage": "review",
         "decision_slot_marks": ["seen:sorter_reviewer", "release:sorter_reviewer", "park:sorter_reviewer"],
         "decision_slot_outcomes": {"sorter_reviewer": {"action": "agree"}}},
    ]
    out = slot_decision_summary(records)
    assert out["slots"]["archive_gate"]["actions"] == {"release": 1}
    assert out["slots"]["sorter_reviewer"]["actions"] == {"park": 1}


def test_tied_scores_archive_together_at_their_cutoff():
    """Rows with the same score are archived by the same cutoff (score >= t)."""
    rows = [{"score": 0.5, "wrong": True}, {"score": 0.5, "wrong": False}, {"score": 0.2, "wrong": False}]
    points = {p["threshold"]: p for p in risk_coverage_curve(rows)["points"]}
    assert (points[0.5]["archived"], points[0.5]["wrong_archives"]) == (2, 1)
    assert (points[0.2]["archived"], points[1.01]["archived"]) == (3, 0)

